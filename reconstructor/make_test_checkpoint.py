#!/usr/bin/env python3
"""
Builds a test checkpoint from the reference ISS: runs the workload for N
instructions, records the ISS state as `gpr_iss`, and writes `gpr_bitstream`
as a copy with optional injected faults. Stand-in for the arbiter, which will
write real checkpoints (hardware state from PCAP, ISS state from QEMU).

    make_test_checkpoint.py quicksort_hw.bin 300 cp.json --flip x15:0x00000100 --id 7
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from checkpoint import write_checkpoint
from rv32i import ISS, disasm

ap = argparse.ArgumentParser()
ap.add_argument("image"); ap.add_argument("n", type=int); ap.add_argument("out")
ap.add_argument("--flip", action="append", default=[], metavar="xN:MASK",
                help="XOR MASK into the bitstream copy of register N (repeatable)")
ap.add_argument("--iss-flip", action="append", default=[], metavar="xN:MASK",
                help="XOR MASK into the ISS copy instead (to simulate an ISS-side fault)")
ap.add_argument("--id", type=int, default=1)
ap.add_argument("--no-count", action="store_true", help="omit instr_count from the file")
a = ap.parse_args()

iss = ISS(open(a.image, "rb").read())
for _ in range(a.n):
    iss.step()
iss_regs = {i: iss.regs[i] for i in range(32)}
hw_regs = dict(iss_regs)
def apply(regs, items):
    for item in items:
        r, m = item.split(":"); regs[int(r.lstrip("x"))] ^= int(m, 0)
apply(hw_regs, a.flip); apply(iss_regs, a.iss_flip)
write_checkpoint(a.out, a.id, iss.pc, disasm(iss.fetch()), hw_regs, iss_regs,
                 instr_count=None if a.no_count else a.n)
print("wrote %s: after %d instructions, next pc %#x (%s)" % (a.out, a.n, iss.pc, disasm(iss.fetch())))
