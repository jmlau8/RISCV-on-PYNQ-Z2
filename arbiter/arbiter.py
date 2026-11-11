"""
FERIVer arbiter (paper section 3.1.1), PS side.

Drives the checking loop: every `strobe_counter` instructions it brings the DUT (the
PicoRV32 on the FPGA, read out through the PCAP bridge) and the ISS (QEMU) to the same
instruction count N, takes the PC and all 32 registers from each, compares them, and
writes a checkpoint .json (read by the re-constructor) when they differ.

Interfaces (both sides stay stopped between calls):
    dut.state_at(n) -> {"pc": int, "regs": {0..31: int}}      (dut_board.BoardDUT, dut_sim.SimDUT)
    iss.state_at(n) -> (pc, regs)  or  {"pc", "regs"}           (qemu_state.QemuState)
n only moves forward on both sides, so the arbiter walks n = 0, S, 2S, ... max_instructions.

Address handling: the board holds a mix of 0x8000xxxx (lui-built) and 0x0000xxxx (auipc /
return-address) values and its PC is 0-based, while QEMU runs the same program linked at
0x80000000. Both sides are passed through checkpoint.normalize() before any comparison.

Instruction count n means: n instructions have completed and the next one is at `pc`.
That is the definition the re-constructor replays to, so checkpoints line up exactly.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(os.path.dirname(HERE), "reconstructor")
for _p in (HERE, RECON):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from checkpoint import normalize, write_checkpoint   # noqa: E402
from rv32i import disasm                              # noqa: E402

COUNT_MASK = (1 << 30) - 1


def checked_state(pc, regs):
    """Require complete, unsigned architectural state; never fill missing values."""
    if set(regs) != set(range(32)):
        raise ValueError("state must contain exactly x0..x31")
    for value in [pc, *regs.values()]:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("state contains a non-32-bit value")
    if regs[0] != 0:
        raise ValueError("x0 must be zero")
    return {"pc": pc, "regs": dict(regs)}


def normalized_state(pc, regs):
    """Validate, then map addresses in the program's RAM window to 0-based offsets."""
    s = checked_state(pc, regs)
    return {"pc": normalize(s["pc"]), "regs": {i: normalize(v) for i, v in s["regs"].items()}}


def _as_state(result):
    """ISS drivers return (pc, regs); DUT drivers return {"pc", "regs"}."""
    if isinstance(result, dict):
        return normalized_state(result["pc"], result["regs"])
    pc, regs = result
    return normalized_state(pc, regs)


class Arbiter:
    """Compare PC and all GPRs at equal instruction counts, recording mismatches.

    mode "fail-fast": stop at the first mismatch (the DUT and ISS stay halted there).
    mode "fail-through": keep going and record every mismatching checkpoint, up to
    `max_checkpoints` files (the comparisons log still records every check).
    """

    def __init__(self, dut, iss, image, output_dir, strobe_counter=1,
                 mode="fail-fast", max_checkpoints=None):
        if not isinstance(strobe_counter, int) or strobe_counter <= 0:
            raise ValueError("strobe_counter must be a positive integer")
        if mode not in ("fail-fast", "fail-through"):
            raise ValueError("mode must be fail-fast or fail-through")
        if max_checkpoints is not None and max_checkpoints <= 0:
            raise ValueError("max_checkpoints must be positive")
        self.dut, self.iss = dut, iss
        self.image = bytes(image)
        self.output_dir = Path(output_dir)
        self.strobe_counter, self.mode = strobe_counter, mode
        self.max_checkpoints = max_checkpoints
        self.summary = None

    def _mnemonic(self, pc):
        # pc is already 0-based (normalized); the image is loaded at address 0 on the board
        if pc + 4 <= len(self.image) and pc % 4 == 0:
            return disasm(int.from_bytes(self.image[pc:pc + 4], "little"))
        return "?"

    def run(self, max_instructions):
        if not isinstance(max_instructions, int) or not 0 <= max_instructions <= COUNT_MASK:
            raise ValueError("max_instructions must fit 30 bits")
        # Never overwrite evidence from a previous verification run.
        self.output_dir.mkdir(parents=True, exist_ok=False)
        results = []
        n_checkpoints = 0
        t_start = time.monotonic()
        t_dut = t_iss = 0.0
        n = 0
        with (self.output_dir / "comparisons.jsonl").open("x") as log, \
                ThreadPoolExecutor(max_workers=2) as workers:
            while True:
                # The fast side waits at its checkpoint until the slow side reaches the same N.
                def timed(fn, n=n):
                    t0 = time.monotonic()
                    out = fn(n)
                    return out, time.monotonic() - t0
                hw_pending = workers.submit(timed, self.dut.state_at)
                iss_pending = workers.submit(timed, self.iss.state_at)
                hw_raw, dt_h = hw_pending.result()
                iss_raw, dt_i = iss_pending.result()
                t_dut += dt_h
                t_iss += dt_i
                hw, iss = _as_state(hw_raw), _as_state(iss_raw)

                diff = ["x%d" % i for i in range(32) if hw["regs"][i] != iss["regs"][i]]
                if hw["pc"] != iss["pc"]:
                    diff.insert(0, "pc")
                record = {"checkpoint_id": len(results), "instr_count": n,
                          "pc_bitstream": hw["pc"], "pc_iss": iss["pc"], "mismatch": diff}
                if diff and (self.max_checkpoints is None or n_checkpoints < self.max_checkpoints):
                    path = self.output_dir / ("checkpoint_%06d.json" % len(results))
                    write_checkpoint(path, len(results), hw["pc"], self._mnemonic(hw["pc"]),
                                     hw["regs"], iss["regs"], instr_count=n, pc_iss=iss["pc"])
                    record["checkpoint"] = str(path)
                    n_checkpoints += 1
                log.write(json.dumps(record) + "\n")
                log.flush()
                results.append(record)
                if (diff and self.mode == "fail-fast") or n == max_instructions:
                    break
                n = min(n + self.strobe_counter, max_instructions)

        mismatches = [r for r in results if r["mismatch"]]
        self.summary = {
            "comparisons": len(results),
            "mismatches": len(mismatches),
            "first_mismatch_instr_count": mismatches[0]["instr_count"] if mismatches else None,
            "last_instr_count": results[-1]["instr_count"],
            "strobe_counter": self.strobe_counter,
            "mode": self.mode,
            "seconds_total": round(time.monotonic() - t_start, 4),
            "seconds_in_dut_state_at": round(t_dut, 4),
            "seconds_in_iss_state_at": round(t_iss, 4),
        }
        with (self.output_dir / "summary.json").open("w") as f:
            json.dump(self.summary, f, indent=2)
            f.write("\n")
        return results
