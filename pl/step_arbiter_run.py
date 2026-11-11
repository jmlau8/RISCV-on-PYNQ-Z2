"""
Run the real arbiter on the PYNQ: DUT = the PicoRV32 on the FPGA (pause block + PCAP), ISS = QEMU states
recorded in WSL (iss_states_quicksort.json). Use a FRESH kernel for every run (Kernel > Restart).

Files in the same folder: step.bit, step.hwh, pcap_bridge.py, decoder.py, full_/pc_decoder_table_step.json,
dut_board.py, arbiter.py, iss_file.py, checkpoint.py, rv32i.py, iss_states_quicksort.json, and the image(s).

Settings (set as environment variables before %run, defaults in brackets):
    IMAGE   [quicksort_unified.bin]  the program loaded onto the board
    STROBE  [1]                      compare every STROBE instructions
    MAXN    [1250]                   last instruction count to compare
    GOLDEN  [quicksort_unified.bin]  the program QEMU runs (same as IMAGE unless you are testing a fault)
    MODE    [fail-fast]              or fail-through
    OUT     [run_<time>]             output folder (must not exist)
    ISS_FILE   path to recorded QEMU states (arbiter/make_iss_states.py); used when ISS_LOCAL/ISS_HOST are unset
               [iss_states_quicksort.json]
    PCAP_SETTLE_S  [0.005]  pause (seconds, used twice) around the CAPTUREE2 trigger. Smaller = faster stops, but
               only trust a value after strobe-1 runs of every workload pass (a stale capture shows as a mismatch)
    FERIVER_FAST_QEMU  set to 1 to use the patched QEMU's fast "run N instructions" command (qemu_patch/);
               otherwise QEMU is single-stepped (slow, ~200 instructions/s on the board)
    ISS_LOCAL  set to 1 to run QEMU ON THE BOARD (qemu-system-riscv32 on the PATH, qemu_state.py in the
               same folder) -- this is the paper's setup
    ISS_HOST, ISS_PORT [5555], ISS_TOKEN
            if ISS_HOST is set, use a live QEMU served by arbiter/iss_remote.py (e.g. in WSL)
            instead of the recorded states; needs iss_remote.py in the same folder
"""
import os
import time

os.environ["DECODER_SUFFIX"] = "_step"          # before pcap_bridge / decoder are imported
from pynq import Overlay                        # noqa: E402
from pcap_bridge import PCAPBridge              # noqa: E402
from dut_board import BoardDUT                  # noqa: E402
from arbiter import Arbiter                     # noqa: E402
from iss_file import FileISS                    # noqa: E402

IMAGE = os.environ.get("IMAGE", "quicksort_unified.bin")
STROBE = int(os.environ.get("STROBE", "1"))
MAXN = int(os.environ.get("MAXN", "1250"))
MODE = os.environ.get("MODE", "fail-fast")
OUT = os.environ.get("OUT", "run_" + time.strftime("%H%M%S"))
GOLDEN_IMAGE = os.environ.get("GOLDEN", "quicksort_unified.bin")   # what QEMU / the re-constructor run

ol = Overlay("step.bit")
image = open(IMAGE, "rb").read()
bridge = PCAPBridge(settle_s=float(os.environ.get("PCAP_SETTLE_S", "0.005")))
dut = BoardDUT(bridge, timeout_s=5.0)
dut.load(image)
if os.environ.get("ISS_LOCAL"):
    from qemu_state import QemuState
    iss = QemuState(GOLDEN_IMAGE).__enter__()
    print("ISS: live QEMU on the board (%s)" % ("fast run mode" if iss.fast else "single-step mode"))
elif os.environ.get("ISS_HOST"):
    from iss_remote import RemoteISS
    iss = RemoteISS(os.environ["ISS_HOST"], int(os.environ.get("ISS_PORT", "5555")),
                    open(GOLDEN_IMAGE, "rb").read(), token=os.environ.get("ISS_TOKEN", ""))
    print("ISS: live QEMU at %s" % os.environ["ISS_HOST"])
else:
    iss = FileISS(os.environ.get("ISS_FILE", "iss_states_quicksort.json"))
    print("ISS: recorded states (%s)" % os.environ.get("ISS_FILE", "iss_states_quicksort.json"))
arb = Arbiter(dut, iss, open(GOLDEN_IMAGE, "rb").read(), OUT, strobe_counter=STROBE, mode=MODE)
results = arb.run(MAXN)
bridge.close()
if hasattr(iss, "close"):
    iss.close()
elif hasattr(iss, "__exit__"):
    iss.__exit__(None, None, None)

bad = [r for r in results if r["mismatch"]]
s = arb.summary
print("PCAP settle: %g s" % float(os.environ.get("PCAP_SETTLE_S", "0.005")))
print("image on board: %s   strobe %d   mode %s" % (IMAGE, STROBE, MODE))
print("%d comparisons, %d mismatches, %.1f s (DUT side %.1f s)" %
      (s["comparisons"], s["mismatches"], s["seconds_total"], s["seconds_in_dut_state_at"]))
if bad:
    b = bad[0]
    print("FIRST MISMATCH at instruction %d: %s" % (b["instr_count"], b["mismatch"]))
    print("checkpoint:", b.get("checkpoint"))
    print("-> download that file (and summary.json), then in WSL run the re-constructor on it with the ORIGINAL image")
else:
    print("RESULT: PASS -- board and QEMU agree at every comparison")
