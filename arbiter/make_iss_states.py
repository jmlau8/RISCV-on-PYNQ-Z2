#!/usr/bin/env python3
"""Record QEMU's state (PC + x0..x31) after every instruction boundary 0..N into a JSON file, so the arbiter
can run on the PYNQ, where QEMU is not available.

    python3 arbiter/make_iss_states.py --elf qemu_reference/quicksort/quicksort_qemu.elf --max 1250 --out iss_states_quicksort.json [--every 10]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "reconstructor"))
from qemu_state import QemuState   # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--elf", required=True)
ap.add_argument("--max", type=int, required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--every", type=int, default=1,
                help="record only instruction counts that are multiples of this (and --max); default 1 = all")
a = ap.parse_args()
out = {}
with QemuState(a.elf) as q:
    counts = sorted(set(range(0, a.max + 1, a.every)) | {a.max})
    for n in counts:
        pc, regs = q.state_at(n)
        out[str(n)] = {"pc": pc, "regs": [regs[i] for i in range(32)]}
json.dump(out, open(a.out, "w"), separators=(",", ":"))
print("wrote %d QEMU states to %s" % (len(out), a.out))
