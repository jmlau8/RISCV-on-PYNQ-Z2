"""
Where do the ~18 ms per stop go?  Times PCAPBridge.capture() on the board, split into trigger / PCAP read / decode,
for several values of the trigger settle delay (PCAPBridge settle_s, default 5 ms; trigger() sleeps twice by this).

Run from the step_test folder in a FRESH kernel:     %run pcap_timing.py
Needs step.bit, pcap_bridge.py, decoder.py and the *_step.json decoder tables (same as step_arbiter_run.py).
Nothing is changed on the board: it only reads the core's state (the core sits halted after reset). To check that
a shorter settle delay is still correct, it compares every decoded state with the one from the default delay.
"""
import os
import time

os.environ["DECODER_SUFFIX"] = "_step"
from pynq import Overlay            # noqa: E402
from pcap_bridge import PCAPBridge  # noqa: E402

ol = Overlay("step.bit")
N = int(os.environ.get("N", "100"))
reference = None
print("%-10s %9s %9s %9s %9s   %s" % ("settle", "trigger", "read", "decode", "total", "state == reference?"))
for settle in (0.005, 0.002, 0.001, 0.0005, 0.0002, 0.0):
    b = PCAPBridge(settle_s=settle)
    b.capture()                                    # warm up
    tt = {"trigger": 0.0, "read": 0.0, "decode": 0.0, "total": 0.0}
    same = True
    for _ in range(N):
        s = b.capture()
        for k in tt:
            tt[k] += b.last_timing[k]
        if reference is None:
            reference = s
        same = same and (s == reference)
    b.close()
    print("%-10s %7.2f ms %7.2f ms %7.2f ms %7.2f ms   %s" % (
        "%g s" % settle, tt["trigger"] / N * 1e3, tt["read"] / N * 1e3, tt["decode"] / N * 1e3,
        tt["total"] / N * 1e3, "yes" if same else "NO"))
