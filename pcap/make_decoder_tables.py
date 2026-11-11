#!/usr/bin/env python3
"""
Regenerate the PCAP decoder tables from a Vivado build.

    python3 make_decoder_tables.py --ll design_1_wrapper.ll --placement placement.csv --out newtables/

Inputs
  --ll         the .ll (logic location) file written with write_bitstream -logic_location_file.
               It lists, for every flip-flop AND every LUT-RAM bit, the frame address (FAR) and the
               bit offset inside the frame (word*32 + bit).
  --placement  CSV from the Tcl dump: name,ref,loc,bel for the cells matching *reg_pc_reg* / *cpuregs*.
Outputs
  full_decoder_table.json   {reg_number: [{bit, FAR, word, bit_in_word}, ...]}  x1..x31, 32 bits each
  pc_decoder_table.json     [{bit, FAR, word, bit_in_word, offset, block, latch}, ...]  PC bits 1..31

How registers are located: the register file is 32-entry LUT-RAM, built as RAM32M cells (6 bits each:
A5/A6, B5/B6, C5/C6 LUTs = bits lo..lo+5) plus two RAM32X1D cells for bits 30 and 31. Register number r is
entry r of a LUT: INIT index r in the 5-LUT half, 32+r in the 6-LUT half. The .ll gives the frame bit of
each (LUT, INIT index) as "Ram=<A-D>:<index>". Only read port 1 (cpuregs_reg_r1_*) is used; the r2 cells hold
a copy of the same data.

Mapping learned from the first board run (it decoded x1 as x30, x2 as x29 ..., and swapped bit pairs):
  * the register number is MIRRORED inside each LUT half: register R is at .ll index 32*half + (31 - R)
  * the two outputs of a pair are swapped: in a RAM32M, the 5-LUT (RAMx) holds the ODD bit (lo+1, lo+3, lo+5)
    and the 6-LUT (RAMx_D1) holds the EVEN bit; of the two RAM32X1D cells, "..._30_31" holds bit 31 and
    "..._30_31__0" holds bit 30.
The board test (pl/step_board_test.py) checks this against the RTL simulation.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict


def parse_ll(path, slices):
    """Return {(slice, 'Ram', lut, idx): (far, offset)} and {(slice, latch): (far, offset, net)}."""
    ram, ff = {}, {}
    pat_blk = re.compile(r"Block=(SLICE_X\d+Y\d+)")
    with open(path) as f:
        for line in f:
            if not line.startswith("Bit "):
                continue
            m = pat_blk.search(line)
            if not m or m.group(1) not in slices:
                continue
            parts = line.split()
            far, off = int(parts[2], 16), int(parts[3])
            blk = m.group(1)
            r = re.search(r"Ram=([A-D]):(\d+)", line)
            if r:
                ram[(blk, r.group(1), int(r.group(2)))] = (far, off)
            l = re.search(r"Latch=(\S+)", line)
            if l:
                n = re.search(r"Net=(\S+)", line)
                ff[(blk, l.group(1))] = (far, off, n.group(1) if n else "")
    return ram, ff


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ll", required=True)
    ap.add_argument("--placement", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--swap-3031", action="store_true", help="swap which RAM32X1D holds bit 30 / bit 31 (default: first cell = bit 31)")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.placement)))
    slices = {r["loc"] for r in rows}
    ram, ff = parse_ll(a.ll, slices)

    # ---------------- registers ----------------
    table = defaultdict(list)
    cellbits = {}      # bit -> (slice, lut letter, half)  for read port 1
    for r in rows:
        m = re.search(r"cpuregs_reg_r1_0_31_(\d+)_(\d+)/RAM([ABC])(_D1)?$", r["name"])
        if m and r["ref"] == "RAMD32":
            lo, letter, d1 = int(m.group(1)), m.group(3), bool(m.group(4))
            k = "ABC".index(letter) * 2 + (0 if d1 else 1)       # pair swapped: 5-LUT = odd bit, 6-LUT = even bit
            cellbits[lo + k] = (r["loc"], letter, 1 if d1 else 0, r["bel"])
    for r in rows:     # RAM32X1D bits 30/31: the data LUT of the read port is the DP half
        m = re.search(r"cpuregs_reg_r1_0_31_30_31(__0)?/DP$", r["name"])
        if m:
            second = bool(m.group(1))
            bit = (31 if second else 30) if a.swap_3031 else (30 if second else 31)
            letter = r["bel"].split(".")[1][0]
            half = 1 if r["bel"].endswith("6LUT") else 0
            cellbits[bit] = (r["loc"], letter, half, r["bel"])
    missing = [b for b in range(32) if b not in cellbits]
    if missing:
        sys.exit("no RAM cell found for register bits %s" % missing)
    for bit in range(32):
        blk, letter, half, bel = cellbits[bit]
        # sanity: the placement BEL letter must agree with the LUT letter we use
        assert bel.split(".")[1][0] == letter, (bit, bel, letter)
        for reg in range(1, 32):
            far, off = ram[(blk, letter, half * 32 + (31 - reg))]
            table[reg].append({"bit": bit, "FAR": far, "word": off // 32, "bit_in_word": off % 32})

    # ---------------- PC ----------------
    pc = []
    for r in rows:
        m = re.search(r"reg_pc_reg\[(\d+)\]$", r["name"])
        if not m:
            continue
        bit, blk, bel = int(m.group(1)), r["loc"], r["bel"].split(".")[1]
        latch = bel + ".Q" if "5FF" in bel else bel.replace("FF", "Q")   # AFF -> AQ, A5FF -> A5FF.Q
        far, off, net = ff[(blk, latch)]
        nm = re.search(r"\[(\d+)\]$", net)
        assert nm and int(nm.group(1)) == bit, ("net/bit mismatch", bit, net)
        pc.append({"bit": bit, "FAR": far, "word": off // 32, "bit_in_word": off % 32,
                   "offset": off, "block": blk, "latch": latch})
    pc.sort(key=lambda e: e["bit"])
    assert [e["bit"] for e in pc] == list(range(1, 32)), "PC bits 1..31 expected"

    os.makedirs(a.out, exist_ok=True)
    json.dump({str(k): v for k, v in sorted(table.items())}, open(os.path.join(a.out, "full_decoder_table.json"), "w"))
    json.dump(pc, open(os.path.join(a.out, "pc_decoder_table.json"), "w"))
    reg_fars = sorted({e["FAR"] for v in table.values() for e in v})
    pc_fars = sorted({e["FAR"] for e in pc})
    print("registers: %d entries, %d FARs: %s" % (sum(len(v) for v in table.values()), len(reg_fars), reg_fars))
    print("PC: %d bits, %d FARs: %s" % (len(pc), len(pc_fars), pc_fars))
    print("frames per capture: %d" % len(set(reg_fars) | set(pc_fars)))
    # no two state bits may share one frame bit
    seen = {}
    for reg, v in table.items():
        for e in v:
            k = (e["FAR"], e["word"], e["bit_in_word"])
            assert k not in seen, ("collision", reg, e, seen[k])
            seen[k] = ("x%d" % reg, e["bit"])
    for e in pc:
        k = (e["FAR"], e["word"], e["bit_in_word"])
        assert k not in seen, ("collision", e, seen[k])
        seen[k] = ("pc", e["bit"])
    print("no bit collisions")


if __name__ == "__main__":
    main()
