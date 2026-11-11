"""
Speed sweep on the PYNQ: run each long workload at several strobe values (compare every N instructions)
with QEMU running on the board, and record how long it takes.

Run from the step_test folder in a Jupyter cell:      %run step_speed_sweep.py
Every run is a FRESH python process (the register file is not cleared by a reset, so each run needs a fresh
start). Needs in the same folder: everything step_arbiter_run.py needs, the *_unified.bin files below, and
step_arbiter_run.py itself.

Settings (environment variables, defaults in brackets):
    WORKLOADS  [quicksort_r83,ssort_r37,md5_r24]   comma separated; each needs <name>_unified.bin
    MAXNS      [98941,98961,101083]                last instruction of each workload (same order)
    STROBES    [10000,1000,100,10]                 compare every N instructions
    ISS_MODE   [local]   local = live QEMU on the board (measures the QEMU side; ~8 min per 100k instructions)
                         file  = recorded QEMU states <name>_states.json (measures the FPGA side only; fast)
    SWEEP_OUT  [sweep_<time>]                      results folder (must not exist)
    TIMEOUT_S  [3600]                              per-run limit

Output: <SWEEP_OUT>/speed.csv and a printed table. Every number is measured; nothing is estimated.
Columns: seconds_total is the whole run; seconds_dut / seconds_iss are the time spent obtaining the FPGA
state / the QEMU state (the two run in parallel, so the total is close to the larger of the two).
"""
import csv
import json
import os
import subprocess
import sys
import time

WORKLOADS = os.environ.get("WORKLOADS", "quicksort_r83,ssort_r37,md5_r24").split(",")
MAXNS = [int(x) for x in os.environ.get("MAXNS", "98941,98961,101083").split(",")]
STROBES = [int(x) for x in os.environ.get("STROBES", "10000,1000,100,10").split(",")]
OUTDIR = os.environ.get("SWEEP_OUT", "sweep_" + time.strftime("%H%M%S"))
ISS_MODE = os.environ.get("ISS_MODE", "local")
if ISS_MODE not in ("local", "file"):
    raise SystemExit("ISS_MODE must be local or file")
TIMEOUT_S = int(os.environ.get("TIMEOUT_S", "3600"))
if len(WORKLOADS) != len(MAXNS):
    raise SystemExit("WORKLOADS and MAXNS must have the same number of entries")
os.makedirs(OUTDIR, exist_ok=False)


def mips(instructions, seconds):
    return instructions / seconds / 1e6 if seconds > 0 else float("nan")


rows = []
print("ISS mode: %s" % ISS_MODE)
for name, maxn in zip(WORKLOADS, MAXNS):
    image = name + "_unified.bin"
    if not os.path.exists(image):
        print("MISSING", image, "- skipping")
        continue
    for strobe in STROBES:
        out = os.path.join(OUTDIR, "%s_s%d" % (name, strobe))
        if ISS_MODE == "file" and not os.path.exists(name + "_states.json"):
            print("MISSING", name + "_states.json", "- skipping")
            break
        env = dict(os.environ, IMAGE=image, GOLDEN=image, MAXN=str(maxn),
                   STROBE=str(strobe), OUT=out, MODE="fail-fast")
        env.pop("ISS_HOST", None)
        env.pop("ISS_LOCAL", None)
        if ISS_MODE == "local":
            env["ISS_LOCAL"] = "1"
        else:
            env["ISS_FILE"] = name + "_states.json"
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, "step_arbiter_run.py"], env=env, timeout=TIMEOUT_S,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            log, rc = p.stdout, p.returncode
        except subprocess.TimeoutExpired:
            log, rc = "timeout", -1
        wall = time.time() - t0
        try:
            s = json.load(open(os.path.join(out, "summary.json")))
        except (OSError, ValueError):
            print("FAILED %s strobe %d (exit %s):\n%s" % (name, strobe, rc, log[-800:]))
            rows.append({"workload": name, "strobe": strobe, "result": "FAILED"})
            continue
        ok = s["mismatches"] == 0 and s["last_instr_count"] == maxn
        row = {"workload": name, "iss": ISS_MODE, "strobe": strobe, "instructions": s["last_instr_count"],
               "comparisons": s["comparisons"], "mismatches": s["mismatches"],
               "seconds_total": s["seconds_total"], "seconds_dut": s["seconds_in_dut_state_at"],
               "seconds_iss": s["seconds_in_iss_state_at"],
               "mips_total": round(mips(s["last_instr_count"], s["seconds_total"]), 5),
               "result": "PASS" if ok else "CHECK"}
        rows.append(row)
        print("%-14s strobe %-6d %5d cmp  total %7.1fs  dut %7.1fs  iss %7.1fs  %.5f MIPS  %s"
              % (name, strobe, row["comparisons"], row["seconds_total"], row["seconds_dut"],
                 row["seconds_iss"], row["mips_total"], row["result"]), flush=True)

fields = ["workload", "iss", "strobe", "instructions", "comparisons", "mismatches", "seconds_total",
          "seconds_dut", "seconds_iss", "mips_total", "result"]
with open(os.path.join(OUTDIR, "speed.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)
print("\nwrote %s/speed.csv" % OUTDIR)
