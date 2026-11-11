"""cocotb test for step_top: drives the step mailbox like BoardDUT does and compares the frozen
core state with the re-constructor's trace (the reference). Parameters via environment:
STEP_IMAGE, STEP_REF (trace JSON from recon_top), STEP_TARGETS (comma list of n, increasing),
STEP_MODE ("compare" | "trap" | "reset")."""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

HALTED, TRAPPED = 1 << 31, 1 << 30
M = (1 << 30) - 1


async def cycles(dut, c):
    for _ in range(c):
        await RisingEdge(dut.clk)


def state(dut):
    return int(dut.pc.value), [int(getattr(dut, "x%d" % i).value) for i in range(32)]


async def start(dut, image, req0=0):
    padded = image + b"\x00" * (-len(image) % 4)
    for i in range(0, len(padded), 4):
        dut.mem[i // 4].value = int.from_bytes(padded[i:i + 4], "little")
    dut.req.value = req0
    dut.resetn.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await cycles(dut, 10)
    dut.resetn.value = 1


async def wait_halt(dut, limit=20000):
    for _ in range(limit):
        await RisingEdge(dut.clk)
        s = int(dut.status.value)
        if s & HALTED:
            return s
    raise AssertionError("never halted")


@cocotb.test()
async def run(dut):
    image = open(os.environ["STEP_IMAGE"], "rb").read()
    mode = os.environ.get("STEP_MODE", "compare")
    if mode == "compare":
        ref = {s["n"]: s for s in json.load(open(os.environ["STEP_REF"]))["samples"]}
        targets = [int(x) for x in os.environ["STEP_TARGETS"].split(",")]
        await start(dut, image)
        s = await wait_halt(dut)
        assert s == HALTED | 0, "initial halt should be n=0, got 0x%08x" % s
        toggle, cur, checked = 0, 0, 0
        for t in [0] + targets:
            if t > cur:
                toggle ^= HALTED
                dut.req.value = toggle | (t - cur)
                await cycles(dut, 2)
                s = await wait_halt(dut)
                cur = t
            else:
                s = int(dut.status.value)
            assert s == HALTED | t, "status 0x%08x, wanted n=%d" % (s, t)
            snap = state(dut)
            await cycles(dut, 40)                       # frozen: nothing may move
            assert state(dut) == snap, "state changed while halted at n=%d" % t
            assert int(dut.status.value) == s
            pc, regs = snap
            assert pc == ref[t]["pc"], "n=%d pc 0x%x != ref 0x%x" % (t, pc, ref[t]["pc"])
            assert regs == ref[t]["regs"], "n=%d regs differ: %s" % (
                t, [i for i in range(32) if regs[i] != ref[t]["regs"][i]])
            checked += 1
        dut._log.info("STEP_OK checked %d boundaries" % checked)
    elif mode == "trap":
        await start(dut, image)
        assert (await wait_halt(dut)) == HALTED
        dut.req.value = HALTED | 100                    # toggle 0 -> 1, run 100 instructions
        await cycles(dut, 2)
        s = await wait_halt(dut)
        assert s & TRAPPED, "expected trap, status 0x%08x" % s
        dut._log.info("STEP_OK trapped status 0x%08x" % s)
    elif mode == "reset":
        # stale toggle=1 left over from an earlier run must not start a request after reset
        await start(dut, image, req0=HALTED | 5)
        s = await wait_halt(dut)
        assert s == HALTED, "stale toggle started a run: 0x%08x" % s
        await cycles(dut, 100)
        assert int(dut.status.value) == HALTED
        dut.req.value = 0 | 3                            # toggle 1 -> 0 is a new request
        await cycles(dut, 2)
        s = await wait_halt(dut)
        assert s == HALTED | 3, "0x%08x" % s
        dut.req.value = 0                                # k = 0 with new toggle... same toggle: ignored
        await cycles(dut, 20)
        assert int(dut.status.value) == HALTED | 3
        dut.req.value = HALTED | 0                       # k = 0, new toggle: consumed, no run
        await cycles(dut, 20)
        assert int(dut.status.value) == HALTED | 3
        dut.req.value = 0 | 2                            # toggle 1 -> 0: runs 2 more
        await cycles(dut, 2)
        s = await wait_halt(dut)
        assert s == HALTED | 5, "0x%08x" % s
        dut._log.info("STEP_OK reset/baseline")
