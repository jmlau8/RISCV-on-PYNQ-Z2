#!/usr/bin/env python3
"""
Build a real checkpoint.json: board state (from PCAPBridge.capture()) + QEMU state.

  1. On the board (Jupyter), at the pause point after N instructions:
         import json
         s = bridge.capture()
         json.dump({"pc": s["pc"], "regs": {str(k): v for k, v in s["regs"].items()}}, open("board_n300.json", "w"))
  2. On the PC (WSL), same N:
         python3 make_checkpoint.py --elf quicksort_qemu.elf --board board_n300.json --n 300 --id 1 --out cp.json
  3. python3 reconstruct.py --checkpoint cp.json --image quicksort_unified.bin --out out/

Both the board's and QEMU's PC/registers are passed through normalize() (addresses in the
program's RAM window -> 0-based) so lui-built 0x8000xxxx and auipc-built 0x0000xxxx
pointers compare equal. The instruction mnemonic is disassembled from --image at the PC.
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from qemu_state import QemuState, normalize      # noqa: E402
from checkpoint import write_checkpoint          # noqa: E402
from rv32i import disasm                         # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elf", required=True, help="workload linked at 0x80000000 (QEMU)")
    ap.add_argument("--image", help="same program as flat .bin (for the mnemonic); default: derive from QEMU memory-free disasm skipped")
    ap.add_argument("--board", required=True, help="JSON {pc, regs} from PCAPBridge.capture()")
    ap.add_argument("--n", type=int, required=True, help="instructions completed at the pause point")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    b = json.load(open(a.board))
    hw_pc = normalize(int(b["pc"]))
    hw_regs = {int(k): normalize(int(v)) for k, v in b["regs"].items()}
    with QemuState(a.elf) as q:
        iss_pc, iss_regs = q.state_at(a.n)
    insn = "?"
    if a.image:
        img = open(a.image, "rb").read()
        if hw_pc + 4 <= len(img):
            insn = disasm(int.from_bytes(img[hw_pc:hw_pc + 4], "little"))
    write_checkpoint(a.out, a.id, hw_pc, insn, hw_regs, iss_regs, instr_count=a.n)
    diff = [i for i in range(32) if hw_regs[i] != iss_regs[i]]
    print("checkpoint %d at n=%d  pc board=0x%x qemu=0x%x%s" % (
        a.id, a.n, hw_pc, iss_pc, "" if hw_pc == iss_pc else "  <-- PC DIFFERS"))
    print("registers differing board vs QEMU:", ["x%d" % i for i in diff] or "none")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
