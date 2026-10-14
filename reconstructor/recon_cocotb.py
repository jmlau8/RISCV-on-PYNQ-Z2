"""
Cocotb test that drives the PicoRV32 replay harness (rtl/recon_top.v).

Not run directly: reconstruct.py builds the design and launches it, passing
parameters through environment variables:

  RECON_IMAGE      path to the workload binary (little-endian, loaded at 0)
  RECON_OUT        path of the JSON file to write
  RECON_MODE       "replay" (stop at a checkpoint) or "trace" (record every
                   instruction boundary, used to validate against the ISS)
  RECON_TARGET     replay: number of instructions completed at the checkpoint
  RECON_TARGET_PC  replay fallback if RECON_TARGET is unset: stop at the first
                   fetch of this PC
  RECON_MAXN       trace: stop after this many instructions
  RECON_CONTEXT    replay: extra clock cycles to simulate after the checkpoint
                   (so the waveform shows what happens next)

An "instruction boundary" sample is taken the cycle after the core's own
instruction counter (count_instr) goes n -> n+1, i.e. as instruction n is
decoded: instructions 0..n-1 have fully retired and the register file holds
their results; the PC is the address of instruction n.
"""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

MAX_CYCLES = 3_000_000


def _safe_int(sig):
    """int value of a signal, or None while it is still X/Z (e.g. mem_addr before the first fetch)."""
    try:
        return int(sig.value)
    except ValueError:
        return None


def _regs(dut):
    return [int(getattr(dut, "x%d" % i).value) for i in range(32)]


@cocotb.test()
async def run(dut):
    image = open(os.environ["RECON_IMAGE"], "rb").read()
    out_path = os.environ["RECON_OUT"]
    mode = os.environ.get("RECON_MODE", "replay")
    target = os.environ.get("RECON_TARGET")
    target = int(target) if target not in (None, "") else None
    target_pc = os.environ.get("RECON_TARGET_PC")
    target_pc = int(target_pc, 0) if target_pc else None
    max_n = int(os.environ.get("RECON_MAXN", "100000"))
    context = int(os.environ.get("RECON_CONTEXT", "20"))
    assert mode in ("replay", "trace")
    if mode == "replay":
        assert target is not None or target_pc is not None, "need RECON_TARGET or RECON_TARGET_PC"

    # load the workload into the harness memory, then reset the core
    padded = image + b"\x00" * (-len(image) % 4)
    for i in range(0, len(padded), 4):
        dut.mem[i // 4].value = int.from_bytes(padded[i:i + 4], "little")
    dut.resetn.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for _ in range(10):
        await RisingEdge(dut.clk)
    dut.resetn.value = 1

    fetch_log = []        # [n, pc, insn] for every instruction boundary seen
    samples = []          # trace mode: full state at every boundary
    hit = None
    cycles_after = None
    prev_started = None   # core's instruction counter (count_instr) last cycle

    def snapshot(n):
        pc = int(dut.reg_pc.value)
        insn = int(dut.mem[(pc >> 2) & 0x3FFF].value)
        return {"n": n, "pc": pc, "insn": insn, "regs": _regs(dut),
                "reg_next_pc": int(dut.reg_next_pc.value)}

    for cycle in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if cycles_after is not None:
            cycles_after += 1
            if cycles_after >= context:
                break
            continue
        started = _safe_int(dut.instr_started)
        if started is None or int(dut.resetn.value) != 1:
            continue
        if prev_started is None:
            prev_started = started          # first cycle after reset: counter is 0
            continue
        if started == prev_started:
            continue
        # count_instr just went n -> n+1: instruction n was decoded this cycle and
        # instructions 0..n-1 have retired (their results are in the register file).
        n = prev_started
        prev_started = started
        snap = snapshot(n)
        fetch_log.append([snap["n"], snap["pc"], snap["insn"]])
        if mode == "trace":
            samples.append(snap)
            if n >= max_n:
                break
        else:
            reached = (n == target) if target is not None else (snap["pc"] == target_pc)
            if reached:
                hit = dict(snap, cycle=cycle)
                cycles_after = 0
    else:
        raise AssertionError("did not reach the checkpoint within %d cycles" % MAX_CYCLES)

    if mode == "replay" and hit is None:
        raise AssertionError("workload never reached the requested checkpoint")

    result = {"mode": mode, "fetch_log": fetch_log}
    if mode == "trace":
        result["samples"] = samples
        result["mem_words"] = [int(dut.mem[i].value) for i in range(0x3FC // 4, 0x420 // 4)]
    else:
        result["checkpoint"] = hit
    with open(out_path, "w") as f:
        json.dump(result, f)
