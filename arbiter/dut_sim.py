"""
Software stand-ins for the board, so the arbiter can be developed and tested without
hardware.

  SimDUT          the DUT as the PicoRV32 RTL run in Icarus Verilog (the same trace the
                  re-constructor uses). Returns RAW RTL values, i.e. the same mix of
                  0x8000xxxx / 0x0000xxxx values the board holds, so the arbiter's address
                  normalization is exercised. Optional fault injection.
  MailboxModel    a Python model of the PL step mailbox (see dut_board.py for the register
                  layout). Lets BoardDUT's handshake run against something with the same
                  behavior as the planned hardware.
  MockBridge      stands in for PCAPBridge: capture() returns the model's current state.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(os.path.dirname(HERE), "reconstructor")
for _p in (HERE, RECON):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HALTED, TRAPPED, COUNT_MASK = 1 << 31, 1 << 30, (1 << 30) - 1


class SimDUT:
    """state_at(n) from an RTL simulation of the workload.

    faults: list of dicts, applied to every n >= from_n (a persistent corruption):
        {"from_n": 300, "reg": 10, "xor": 0x4}      flip bits of a register
        {"from_n": 300, "pc_xor": 0x4}              flip bits of the PC
    """

    def __init__(self, image_path, max_n, faults=(), workdir=None):
        import reconstruct          # needs cocotb + iverilog
        self.faults = [dict(f) for f in faults]
        workdir = workdir or tempfile.mkdtemp(prefix="simdut_")
        out = os.path.join(workdir, "trace.json")
        reconstruct.run_sim(image_path, out, os.path.join(workdir, "sim"), "trace", maxn=max_n)
        self._samples = {s["n"]: s for s in json.load(open(out))["samples"]}
        self.max_n = max(self._samples)
        self.current = 0

    def clone(self, faults=()):
        """A fresh DUT (back at n=0) over the same simulated trace, with its own faults.
        Avoids re-running the simulation for every test case."""
        other = object.__new__(SimDUT)
        other.faults = [dict(f) for f in faults]
        other._samples, other.max_n, other.current = self._samples, self.max_n, 0
        return other

    def state_at(self, n):
        if n < self.current:
            raise ValueError("DUT cannot move backward")
        if n not in self._samples:
            raise ValueError("no simulated state for n=%d (max %d)" % (n, self.max_n))
        self.current = n
        s = self._samples[n]
        pc, regs = s["pc"], {i: v for i, v in enumerate(s["regs"])}
        for f in self.faults:
            if n >= f["from_n"]:
                if "reg" in f:
                    regs[f["reg"]] ^= f["xor"]
                if "pc_xor" in f:
                    pc ^= f["pc_xor"]
        return {"pc": pc, "regs": regs}


class MailboxModel:
    """Python model of the PL step mailbox.

    write(0, v): bit31 = request toggle, bits[29:0] = instructions to run. A changed toggle
                 starts a request; the same toggle is ignored.
    read(8):     bit31 HALTED, bit30 TRAPPED, bits[29:0] instructions completed since reset.
    read(0):     last value written.

    After reset the core runs until n=0 and halts (the initial synchronization). `latency`
    is how many status reads a run takes to complete. `states` maps n -> {"pc", "regs"}.
    """

    def __init__(self, states, latency=3, trap_at=None):
        self.states, self.latency, self.trap_at = states, latency, trap_at
        self.reset()

    def reset(self):
        self.n_done, self.trapped, self.halted = 0, False, False
        self.last_toggle = 0           # baseline: BoardDUT.load() writes 0 while in reset
        self.written = 0
        self._pending, self._reads_left = 0, self.latency   # initial run to n=0

    def write(self, offset, value):
        assert offset == 0, "only channel 1 (offset 0) is writable"
        self.written = value
        toggle = (value >> 31) & 1
        if toggle != self.last_toggle:
            self.last_toggle = toggle
            self._pending = value & COUNT_MASK
            self.halted = False
            self._reads_left = self.latency

    def read(self, offset):
        if offset == 0:
            return self.written
        assert offset == 8, "unknown register 0x%x" % offset
        if not self.halted:
            self._reads_left -= 1
            if self._reads_left <= 0:
                target = self.n_done + self._pending
                if self.trap_at is not None and target >= self.trap_at > self.n_done:
                    self.n_done, self.trapped = self.trap_at, True
                else:
                    self.n_done = target
                self._pending = 0
                self.halted = True
        return (HALTED if self.halted else 0) | (TRAPPED if self.trapped else 0) | self.n_done


class MockBridge:
    """PCAPBridge stand-in: capture() returns the model's state at its current count.
    advance_during_capture=True simulates a DUT that keeps running during readback."""

    def __init__(self, model, advance_during_capture=False):
        self.model, self.advance = model, advance_during_capture
        self.captures = 0

    def capture(self):
        s = self.model.states[self.model.n_done]
        self.captures += 1
        if self.advance:
            self.model.n_done += 1
        return {"pc": s["pc"], "regs": dict(s["regs"])}
