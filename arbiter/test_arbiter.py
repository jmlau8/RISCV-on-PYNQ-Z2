"""
Software-only tests for the arbiter. No board needed:

    python3 arbiter/test_arbiter.py          (from the repo root; needs iverilog, cocotb 2.1.0,
                                              qemu-system-riscv32)

The DUT is the RTL simulation (dut_sim.SimDUT), the ISS is real QEMU, and mismatches
are sent through the real re-constructor, so the whole FERIVer software chain is exercised.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECON = os.path.join(ROOT, "reconstructor")
QDIR = os.path.join(ROOT, "qemu_reference", "quicksort")
ELF = os.path.join(QDIR, "quicksort_qemu.elf")
IMAGE = os.path.join(QDIR, "quicksort_unified.bin")
for p in (HERE, RECON):
    if p not in sys.path:
        sys.path.insert(0, p)

from arbiter import Arbiter, checked_state             # noqa: E402
from checkpoint import load_checkpoint                  # noqa: E402
from dut_board import BoardDUT                          # noqa: E402
from dut_sim import MailboxModel, MockBridge, SimDUT    # noqa: E402
from qemu_state import QemuState                        # noqa: E402

MAX_N = 1250
_base = None


def base_dut():
    global _base
    if _base is None:
        _base = SimDUT(IMAGE, MAX_N)
    return _base


class FaultyISS:
    """Wraps QemuState and corrupts its state from instruction `from_n` on."""

    def __init__(self, inner, from_n, reg, xor):
        self.inner, self.from_n, self.reg, self.xor = inner, from_n, reg, xor

    def state_at(self, n):
        pc, regs = self.inner.state_at(n)
        regs = dict(regs)
        if n >= self.from_n:
            regs[self.reg] ^= self.xor
        return pc, regs


class ArbiterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arbiter_test_")
        self.out = os.path.join(self.tmp, "run")
        self.image = open(IMAGE, "rb").read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def arbiter(self, dut, iss, **kw):
        return Arbiter(dut, iss, self.image, self.out, **kw)

    def reconstruct(self, checkpoint):
        out = os.path.join(self.tmp, "recon")
        subprocess.run([sys.executable, os.path.join(RECON, "reconstruct.py"), "--checkpoint",
                        checkpoint, "--image", IMAGE, "--out", out, "--no-vcd"],
                       check=True, capture_output=True)
        return json.load(open(os.path.join(out, "report.json")))

    # -- healthy runs ----------------------------------------------------------
    def test_healthy_run_strobe_7(self):
        with QemuState(ELF) as iss:
            res = self.arbiter(base_dut().clone(), iss, strobe_counter=7).run(MAX_N)
        self.assertEqual([r["mismatch"] for r in res if r["mismatch"]], [])
        counts = [r["instr_count"] for r in res]
        self.assertEqual(counts[:3], [0, 7, 14])
        self.assertEqual(counts[-1], MAX_N)
        lines = open(os.path.join(self.out, "comparisons.jsonl")).read().splitlines()
        self.assertEqual(len(lines), len(res))
        summary = json.load(open(os.path.join(self.out, "summary.json")))
        self.assertEqual(summary["mismatches"], 0)

    def test_healthy_run_every_instruction(self):
        with QemuState(ELF) as iss:
            res = self.arbiter(base_dut().clone(), iss, strobe_counter=1).run(MAX_N)
        self.assertEqual(len(res), MAX_N + 1)
        self.assertFalse(any(r["mismatch"] for r in res))

    def test_raw_dut_values_really_are_mixed_addresses(self):
        # guards the normalization test: the raw RTL state must contain 0x8000xxxx values
        # alongside 0-based ones, like the board
        raw = base_dut().clone().state_at(MAX_N)
        vals = list(raw["regs"].values())
        self.assertTrue(any(v >= 0x80000000 for v in vals))
        self.assertTrue(any(0 < v < 0x10000 for v in vals))

    # -- faults ----------------------------------------------------------------
    def test_register_fault_on_dut(self):
        dut = base_dut().clone([{"from_n": 300, "reg": 10, "xor": 0x4}])
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=7).run(MAX_N)
        self.assertEqual(res[-1]["mismatch"], ["x10"])
        self.assertEqual(res[-1]["instr_count"], 301)          # first multiple of 7 past 300
        cp = load_checkpoint(res[-1]["checkpoint"])
        self.assertEqual(cp["instr_count"], 301)
        self.assertEqual(cp["mismatch"], [10])
        report = self.reconstruct(res[-1]["checkpoint"])
        self.assertIn("hardware deviates", report["verdict"])
        self.assertEqual(report["registers_differing_rtl_vs_hw"], ["x10"])
        self.assertEqual(report["registers_differing_rtl_vs_iss"], [])

    def test_register_fault_on_iss(self):
        with QemuState(ELF) as q:
            iss = FaultyISS(q, 300, 10, 0x4)
            res = self.arbiter(base_dut().clone(), iss, strobe_counter=7).run(MAX_N)
        self.assertEqual(res[-1]["mismatch"], ["x10"])
        report = self.reconstruct(res[-1]["checkpoint"])
        self.assertIn("ISS deviates", report["verdict"])

    def test_pc_fault_on_dut(self):
        dut = base_dut().clone([{"from_n": 300, "pc_xor": 0x4}])
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=7).run(MAX_N)
        self.assertEqual(res[-1]["mismatch"], ["pc"])
        cp = load_checkpoint(res[-1]["checkpoint"])
        self.assertNotEqual(cp["pc"], cp["pc_iss"])
        report = self.reconstruct(res[-1]["checkpoint"])
        self.assertIn("PC: hardware deviates", report["verdict"])

    def test_fail_through_caps_checkpoints(self):
        dut = base_dut().clone([{"from_n": 300, "reg": 10, "xor": 0x4}])
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=10, mode="fail-through",
                               max_checkpoints=3).run(MAX_N)
        self.assertEqual(res[-1]["instr_count"], MAX_N)
        bad = [r for r in res if r["mismatch"]]
        self.assertGreater(len(bad), 3)
        self.assertEqual(len([r for r in bad if "checkpoint" in r]), 3)
        files = [f for f in os.listdir(self.out) if f.startswith("checkpoint_")]
        self.assertEqual(len(files), 3)

    def test_fail_fast_stops_and_never_overwrites(self):
        dut = base_dut().clone([{"from_n": 10, "reg": 5, "xor": 1}])
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=1).run(MAX_N)
        self.assertEqual(res[-1]["instr_count"], 10)
        with QemuState(ELF) as iss:
            with self.assertRaises(FileExistsError):
                self.arbiter(base_dut().clone(), iss).run(5)

    def test_constructor_validation(self):
        for kw in ({"strobe_counter": 0}, {"strobe_counter": "x"}, {"mode": "nope"},
                   {"max_checkpoints": 0}):
            with self.assertRaises(ValueError):
                Arbiter(None, None, b"", self.out, **kw)

    # -- through the board driver and a model of the PL mailbox -------------------
    def board_dut(self, **model_kw):
        sim = base_dut().clone()
        states = {n: sim.state_at(n) for n in range(0, MAX_N + 1)}
        model = MailboxModel(states, **model_kw)
        return BoardDUT(MockBridge(model), mmio=model, timeout_s=2.0), model

    def test_board_driver_full_run_matches_qemu(self):
        dut, model = self.board_dut()
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=5).run(400)
        self.assertFalse(any(r["mismatch"] for r in res))
        self.assertEqual(res[-1]["instr_count"], 400)
        self.assertEqual(model.n_done, 400)

    def test_board_driver_detects_fault_in_mailbox_path(self):
        dut, model = self.board_dut()
        for n in range(300, MAX_N + 1):
            model.states[n]["regs"][11] ^= 0x10
        with QemuState(ELF) as iss:
            res = self.arbiter(dut, iss, strobe_counter=50).run(MAX_N)
        self.assertEqual(res[-1]["mismatch"], ["x11"])
        self.assertEqual(res[-1]["instr_count"], 300)

    def test_board_driver_error_paths(self):
        dut, _ = self.board_dut()
        dut.state_at(10)
        with self.assertRaises(ValueError):
            dut.state_at(5)                                   # cannot move backward
        for bad in (-1, 1 << 30, 1.5, True):
            with self.assertRaises(ValueError):
                dut.state_at(bad)
        dut, _ = self.board_dut(trap_at=50)
        with self.assertRaises(RuntimeError):
            dut.state_at(100)                                 # trapped before n=100
        sim = base_dut().clone()
        model = MailboxModel({0: sim.state_at(0)}, latency=10 ** 9)
        slow = BoardDUT(MockBridge(model), mmio=model, timeout_s=0.05)
        with self.assertRaises(TimeoutError):
            slow.state_at(0)                                  # never halts
        sim = base_dut().clone()
        states = {n: sim.state_at(n) for n in range(0, 40)}
        model = MailboxModel(states)
        racing = BoardDUT(MockBridge(model, advance_during_capture=True), mmio=model,
                          timeout_s=2.0)
        with self.assertRaises(RuntimeError):
            racing.state_at(10)                               # DUT ran during PCAP readback

    # -- live ISS over the network -------------------------------------------------
    def test_remote_iss_matches_local_qemu(self):
        import socket
        import time
        from iss_remote import RemoteISS
        with socket.socket() as t:
            t.bind(("127.0.0.1", 0))
            port = t.getsockname()[1]
        srv = subprocess.Popen([sys.executable, os.path.join(HERE, "iss_remote.py"), "serve",
                                "--host", "127.0.0.1", "--port", str(port), "--token", "x"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            with self.assertRaises(RuntimeError):
                RemoteISS("127.0.0.1", port, self.image, token="wrong")
            iss = RemoteISS("127.0.0.1", port, self.image, token="x")
            res = self.arbiter(base_dut().clone(), iss, strobe_counter=25).run(MAX_N)
            iss.close()
            self.assertFalse(any(r["mismatch"] for r in res))
            self.assertEqual(res[-1]["instr_count"], MAX_N)
        finally:
            srv.kill()
            srv.wait()

    # -- state validation ---------------------------------------------------------
    def test_checked_state_rejects_bad_state(self):
        good = {i: 0 for i in range(32)}
        checked_state(0, good)
        with self.assertRaises(ValueError):
            checked_state(0, {i: 0 for i in range(31)})        # missing x31
        with self.assertRaises(ValueError):
            checked_state(0, {**good, 0: 1})                   # x0 != 0
        with self.assertRaises(ValueError):
            checked_state(0, {**good, 3: 1 << 32})             # not 32-bit
        with self.assertRaises(ValueError):
            checked_state(-1, good)
        with self.assertRaises(ValueError):
            checked_state(True, good)


if __name__ == "__main__":
    unittest.main(verbosity=2)
