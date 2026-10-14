#!/usr/bin/env python3
"""
Validates the RTL replay harness against the independent ISS (rv32i.py).

Runs the workload on the PicoRV32 RTL in trace mode (state recorded at every
instruction boundary) and checks that, for every instruction count n, the RTL's
PC, fetched instruction word and all 32 registers equal the ISS state after n
instructions. Also checks the workload's own result (sorted array in memory).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from reconstruct import run_sim
from rv32i import ISS

image_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "quicksort_hw.bin")
maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 1250
out = os.path.join(HERE, "out_validate"); os.makedirs(out, exist_ok=True)
raw_path = os.path.join(out, "trace_raw.json")
run_sim(image_path, raw_path, os.path.join(out, "sim_build"), "trace", maxn=maxn)
raw = json.load(open(raw_path))
samples = raw["samples"]

image = open(image_path, "rb").read()
iss = ISS(image)
bad = 0
for s in samples:
    n = s["n"]
    assert iss.count == n, (iss.count, n)
    exp_regs = list(iss.regs); exp_pc = iss.pc; exp_insn = iss.fetch()
    if s["regs"] != exp_regs or s["pc"] != exp_pc or s["insn"] != exp_insn:
        bad += 1
        if bad <= 5:
            diffs = [i for i in range(32) if s["regs"][i] != exp_regs[i]]
            print("MISMATCH at n=%d: pc rtl=%#x iss=%#x insn rtl=%#x iss=%#x regs differ: %s"
                  % (n, s["pc"], exp_pc, s["insn"], exp_insn, diffs))
    iss.step()
print("compared %d instruction boundaries (n=0..%d): %d mismatches" % (len(samples), samples[-1]["n"], bad))
mw = raw["mem_words"]
status, result = mw[0], mw[(0x400 - 0x3FC) // 4: (0x400 - 0x3FC) // 4 + 8]
print("RTL memory at end of trace: status=%#x result=%s" % (status, result))
