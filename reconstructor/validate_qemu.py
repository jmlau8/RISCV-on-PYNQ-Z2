#!/usr/bin/env python3
"""
Check that QEMU (qemu_state.py) and the PicoRV32 RTL replay agree at EVERY
instruction boundary, using the same program image on both.

    python3 validate_qemu.py --elf quicksort_qemu.elf --image quicksort_unified.bin [--n 1250]

--elf    the workload linked at 0x80000000 (what QEMU runs)
--image  the SAME program as a flat binary (objcopy -O binary), what the RTL/board runs
         from address 0. Build both from one ELF so the instruction streams are identical.
Needs the re-constructor files (reconstruct.py, recon_cocotb.py, ...) in the same folder.
"""
import argparse, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from qemu_state import QemuState, normalize          # noqa: E402
import reconstruct                                     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--n", type=int, default=1250, help="last instruction boundary to compare")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="qvalidate_")
    out = os.path.join(tmp, "trace.json")
    reconstruct.run_sim(a.image, out, os.path.join(tmp, "sim"), "trace", maxn=a.n)
    samples = {s["n"]: s for s in json.load(open(out))["samples"]}
    bad = 0
    with QemuState(a.elf) as q:
        for n in sorted(samples):
            pc, regs = q.state_at(n)
            s = samples[n]
            rpc, rregs = normalize(s["pc"]), [normalize(v) for v in s["regs"]]
            diff = [i for i in range(32) if regs[i] != rregs[i]]
            if pc != rpc or diff:
                bad += 1
                if bad <= 5:
                    print("MISMATCH n=%d qemu pc=%x rtl pc=%x regs %s" % (
                        n, pc, rpc, [(i, hex(regs[i]), hex(rregs[i])) for i in diff]))
    print("compared %d instruction boundaries (n=%d..%d): %d mismatches" % (
        len(samples), min(samples), max(samples), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
