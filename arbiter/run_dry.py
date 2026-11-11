#!/usr/bin/env python3
"""Software-only FERIVer dry run: RTL simulation as the DUT, QEMU as the ISS.

  python3 arbiter/run_dry.py --out runs/dry1 --strobe 7 --max 1250
  python3 arbiter/run_dry.py --out runs/dry2 --strobe 7 --fault-reg 10 --fault-from 300

--fault-reg/--fault-from flip bit 2 of that register in the DUT from that instruction on, so you can
watch the arbiter catch it and write a checkpoint for the re-constructor."""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "reconstructor")):
    sys.path.insert(0, p)
from arbiter import Arbiter           # noqa: E402
from dut_sim import SimDUT            # noqa: E402
from qemu_state import QemuState      # noqa: E402

Q = os.path.join(ROOT, "qemu_reference", "quicksort")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--strobe", type=int, default=1)
    ap.add_argument("--max", type=int, default=1250)
    ap.add_argument("--mode", default="fail-fast", choices=["fail-fast", "fail-through"])
    ap.add_argument("--image", default=os.path.join(Q, "quicksort_unified.bin"))
    ap.add_argument("--elf", default=os.path.join(Q, "quicksort_qemu.elf"))
    ap.add_argument("--fault-reg", type=int)
    ap.add_argument("--fault-from", type=int, default=0)
    a = ap.parse_args()
    faults = [{"from_n": a.fault_from, "reg": a.fault_reg, "xor": 4}] if a.fault_reg else []
    dut = SimDUT(a.image, a.max, faults=faults)
    with QemuState(a.elf) as iss:
        arb = Arbiter(dut, iss, open(a.image, "rb").read(), a.out, a.strobe, a.mode)
        res = arb.run(a.max)
    s = arb.summary
    print("%d comparisons, %d mismatches (strobe %d); results in %s"
          % (s["comparisons"], s["mismatches"], a.strobe, a.out))
    bad = [r for r in res if r["mismatch"]]
    if bad:
        print("first mismatch at instruction %d: %s\ncheckpoint: %s\nnext: python3 reconstructor/reconstruct.py "
              "--checkpoint %s --image %s --out %s/recon"
              % (bad[0]["instr_count"], bad[0]["mismatch"], bad[0].get("checkpoint"),
                 bad[0].get("checkpoint"), a.image, a.out))


if __name__ == "__main__":
    main()
