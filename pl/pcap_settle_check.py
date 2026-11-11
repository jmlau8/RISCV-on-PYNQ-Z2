"""
Is a shorter CAPTUREE2 settle delay still correct?  For each delay, run four tests that change the core's state
at (almost) every stop, so a stale or half-finished capture shows up as a mismatch:
    patterns   step_board_test.py on patterns.bin  vs expected_patterns.json      (81 stops, all registers, bits 30/31)
    quicksort  step_board_test.py on quicksort_unified.bin vs expected_quicksort_all.json   (1251 stops)
    ssort      step_arbiter_run.py strobe 1, live QEMU (fast mode)                (2686 stops)
    md5        step_arbiter_run.py strobe 1, live QEMU (fast mode)                (4289 stops)
Each run is a fresh python process (the register file is not cleared by a reset).

Run from the step_test folder:     %run pcap_settle_check.py
Settings (environment variables):  SETTLES [0.001,0.0005,0.0002,0.0001,0]   delays to try, in seconds
Needs: step.bit/.hwh, step_board_test.py, step_arbiter_run.py, pcap_bridge.py, decoder.py, the *_step.json tables,
dut_board.py, arbiter.py, iss_file.py, iss_remote.py, qemu_state.py, checkpoint.py, rv32i.py, patterns.bin,
expected_patterns.json, expected_quicksort_all.json, quicksort_unified.bin, ssort_unified.bin, md5_unified.bin.
"""
import os
import subprocess
import sys
import time

SETTLES = [float(x) for x in os.environ.get("SETTLES", "0.001,0.0005,0.0002,0.0001,0").split(",")]
TESTS = [
    ("patterns", "step_board_test.py", {"IMAGE": "patterns.bin", "EXPECTED": "expected_patterns.json"}),
    ("quicksort", "step_board_test.py", {"IMAGE": "quicksort_unified.bin", "EXPECTED": "expected_quicksort_all.json"}),
    ("ssort", "step_arbiter_run.py", {"IMAGE": "ssort_unified.bin", "GOLDEN": "ssort_unified.bin", "MAXN": "2685",
                                      "STROBE": "1", "ISS_LOCAL": "1", "FERIVER_FAST_QEMU": "1"}),
    ("md5", "step_arbiter_run.py", {"IMAGE": "md5_unified.bin", "GOLDEN": "md5_unified.bin", "MAXN": "4288",
                                    "STROBE": "1", "ISS_LOCAL": "1", "FERIVER_FAST_QEMU": "1"}),
]
needed = {"step_board_test.py", "step_arbiter_run.py"} | {v for _, _, e in TESTS for k, v in e.items()
                                                          if k in ("IMAGE", "EXPECTED")}
missing = [f for f in sorted(needed) if not os.path.exists(f)]
if missing:
    raise SystemExit("missing files: %s" % ", ".join(missing))

print("%-9s | %s | %s" % ("settle", " | ".join("%-9s" % t[0] for t in TESTS), "seconds"))
all_ok = {}
for settle in SETTLES:
    cells, t0 = [], time.time()
    for name, script, extra in TESTS:
        env = dict(os.environ, PCAP_SETTLE_S=repr(settle), OUT="chk_%s_%s_%d" % (name, repr(settle).replace(".", "p"), int(t0)), **extra)
        env.pop("ISS_HOST", None)
        try:
            p = subprocess.run([sys.executable, script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, timeout=1800)
            ok = "RESULT: PASS" in p.stdout
            if not ok:
                open("chk_fail_%s_%s.txt" % (name, repr(settle).replace(".", "p")), "w").write(p.stdout)
        except subprocess.TimeoutExpired:
            ok = False
        cells.append("PASS" if ok else "FAIL")
    all_ok[settle] = all(c == "PASS" for c in cells)
    print("%-9g | %s | %6.0f" % (settle, " | ".join("%-9s" % c for c in cells), time.time() - t0), flush=True)
print("\nFAIL output of a test is saved as chk_fail_<test>_<settle>.txt - send it to Claude.")
