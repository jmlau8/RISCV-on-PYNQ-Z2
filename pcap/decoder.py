"""
Frame-to-state decoder for the PicoRV32I core: general-purpose registers
(x1-x31; x0 is hardwired to zero) and the program counter (PC).

Derived from:
  - Registers (LUTRAM): Vivado placement + net-tracing of the cpuregs cells,
    plus prjxray-db segbits for the exact frame-bit addressing. Hardware
    verified (7 distinct registers decoded bit-exact, bits 30/31 isolated).
  - PC (flip-flops): Vivado's logic location (.ll) file, cross-checked
    against the placement CSV. Hardware verified on PC bits 2-12 (17 targets).
    Captured flip-flop state reads back INVERTED in the frames, so each PC
    bit is flipped here (LUTRAM register bits are not inverted).

Needs, next to this file: full_decoder_table.json, pc_decoder_table.json

Usage:
    from decoder import ALL_FARS, PC_FARS, STATE_FARS, \
        decode_register, decode_all_registers, decode_pc, decode_state

    # capture frames via PCAP for every FAR in STATE_FARS (12 frames), then:
    frames = {far: read_frame(far) for far in STATE_FARS}
    state = decode_state(frames)   # {"pc": ..., "regs": {0: 0, 1: ..., 31: ...}}

    # registers only:  frames for ALL_FARS (8 frames) -> decode_all_registers
    # PC only:         frames for PC_FARS  (4 frames) -> decode_pc

IMPORTANT: the tables are tied to one specific implemented design. If the
design is re-synthesized/re-placed, regenerate them (same method) or the
decode will be wrong. Always load the .bit that matches the tables.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, "full_decoder_table.json")) as f:
    _RAW_TABLE = json.load(f)
# JSON keys are strings; convert register numbers back to int
DECODER_TABLE = {int(reg): entries for reg, entries in _RAW_TABLE.items()}
ALL_FARS = sorted(set(e["FAR"] for entries in DECODER_TABLE.values() for e in entries))

with open(os.path.join(_HERE, "pc_decoder_table.json")) as f:
    PC_TABLE = json.load(f)   # list of {bit, FAR, word, bit_in_word, ...}
PC_FARS = sorted(set(e["FAR"] for e in PC_TABLE))

# every frame needed for a complete architectural-state capture
STATE_FARS = sorted(set(ALL_FARS) | set(PC_FARS))


def decode_register(frames, reg_num):
    """
    frames: dict mapping FAR (int) -> sequence of 101 32-bit words
            (as returned by read_frame() for that FAR)
    reg_num: 0-31 (x0 is always 0, not looked up)
    returns: the register's 32-bit value as a Python int
    """
    if reg_num == 0:
        return 0
    if reg_num not in DECODER_TABLE:
        raise ValueError(f"reg_num must be 0-31, got {reg_num}")

    value = 0
    for entry in DECODER_TABLE[reg_num]:
        far, word, bit, reg_bit = entry["FAR"], entry["word"], entry["bit_in_word"], entry["bit"]
        word_val = int(frames[far][word])
        bit_val = (word_val >> bit) & 1
        value |= (bit_val << reg_bit)
    return value


def decode_all_registers(frames):
    """Returns {0: 0, 1: val, 2: val, ..., 31: val} for the full register file."""
    result = {0: 0}
    for reg_num in range(1, 32):
        result[reg_num] = decode_register(frames, reg_num)
    return result


def decode_pc(frames):
    """
    Returns the program counter as a Python int. Bit 0 is not stored by the
    core (always 0 without compressed instructions) and is returned as 0.
    Captured flip-flop bits are inverted in the frames, so each is flipped.
    """
    value = 0
    for e in PC_TABLE:
        raw = (int(frames[e["FAR"]][e["word"]]) >> e["bit_in_word"]) & 1
        value |= (raw ^ 1) << e["bit"]
    return value


def decode_state(frames):
    """Full architectural state: {"pc": int, "regs": {0..31: int}}."""
    return {"pc": decode_pc(frames), "regs": decode_all_registers(frames)}
