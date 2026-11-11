"""
Board test for the PL step/pause block. Run in Jupyter on the PYNQ-Z2 (a FRESH kernel: Kernel > Restart,
because resetn does not clear the LUTRAM register file).

Put these in one folder on the board:
    step.bit, step.hwh                         the new build (design_1_wrapper.bit / design_1.hwh, renamed)
    quicksort_unified.bin
    pcap_bridge.py, decoder.py                 (decoder.py with DECODER_SUFFIX support)
    full_decoder_table_step.json, pc_decoder_table_step.json    tables for the NEW bitstream
    dut_board.py                               from arbiter/
    expected_states.json                       RTL-simulation states of the same program at 20 instruction counts

What it does:
  1. loads the bitstream, reads the mailbox: after reset the core must be HALTED at n=0 (status 0x80000000)
  2. steps the core to n = 0, 1, 2, 3, ... 1250 through the mailbox, captures PC + x0..x31 over PCAP at
     each stop, and compares with the RTL simulation (addresses normalized as in the arbiter)
  3. checks that a capture never moves the core (status unchanged after every capture)
Nothing here needs QEMU; the expected states come from the RTL simulation, which was already checked
against QEMU at all 1251 instruction boundaries.

If step 1 fails, print the raw status and stop: tell Claude the value.
"""
import json
import os
import time

os.environ["DECODER_SUFFIX"] = "_step"          # must be set before pcap_bridge / decoder are imported
from pynq import Overlay                        # noqa: E402
from pcap_bridge import PCAPBridge              # noqa: E402
from dut_board import BoardDUT, STATUS_REG      # noqa: E402

# IMAGE / EXPECTED can be overridden before running, e.g.  os.environ["IMAGE"]="patterns.bin"; os.environ["EXPECTED"]="expected_patterns.json"
BITSTREAM = "step.bit"
IMAGE = os.environ.get("IMAGE", "quicksort_unified.bin")
EXPECTED = os.environ.get("EXPECTED", "expected_states.json")


def norm(v, base=0x80000000):
    """Program addresses appear as 0x8000xxxx or 0x0000xxxx on the board; compare them as offsets."""
    return v - base if base <= v <= base + 0x10000 else v


ol = Overlay(BITSTREAM)                         # PL must be programmed before any MMIO
expected = {int(k): v for k, v in json.load(open(EXPECTED)).items()}
image = open(IMAGE, "rb").read()

bridge = PCAPBridge(settle_s=float(os.environ.get("PCAP_SETTLE_S", "0.005")))
dut = BoardDUT(bridge, timeout_s=5.0)
try:
    dut.load(image)
except Exception as e:                           # noqa: BLE001
    print("STEP 1 FAILED:", e)
    print("raw mailbox status = 0x%08x   (expected 0x80000000 = halted at n=0)" % dut.io.read(STATUS_REG))
    bridge.close()
    raise
print("step 1 OK: halted at n=0, status = 0x%08x" % dut.io.read(STATUS_REG))

bad, t0, record = 0, time.time(), {}
for n in sorted(expected):
    s = dut.state_at(n)
    pc, regs = norm(s["pc"]), {r: norm(v) for r, v in s["regs"].items()}
    exp = expected[n]
    record[n] = {"pc": s["pc"], "regs": [s["regs"][r] for r in range(32)]}
    epc, eregs = norm(exp["pc"]), {r: norm(v) for r, v in enumerate(exp["regs"])}
    diff = ([] if pc == epc else ["pc: board 0x%x vs sim 0x%x" % (s["pc"], exp["pc"])]) + \
           ["x%d: board 0x%08x vs sim 0x%08x" % (r, s["regs"][r], exp["regs"][r])
            for r in range(32) if regs[r] != eregs[r]]
    status = dut.io.read(STATUS_REG)
    if status != (1 << 31 | n):
        diff.append("status after capture = 0x%08x" % status)
    print("n=%-5d %s" % (n, "OK" if not diff else "MISMATCH"))
    for d in diff[:12]:
        print("        ", d)
    bad += bool(diff)
print("\n%d of %d stops matched the RTL simulation; %.1f s total" % (len(expected) - bad, len(expected), time.time() - t0))
json.dump(record, open("board_states.json", "w"))      # raw board captures, in case they are needed for debugging
print("RESULT:", "PASS" if bad == 0 else "FAIL -- copy everything above and send it to Claude")
bridge.close()
