"""
Checkpoint file format for the FERIVer re-constructor (paper section 3.1.3).

The paper says the checkpoint .json holds: the checkpoint ID, the program
counter, the instruction mnemonic, and two sets of general-purpose register
values, one extracted from the bitstream (PCAP) and one from the ISS (QEMU).
Field names below are our choice; the paper doesn't specify them.

    {
      "checkpoint_id": 12,
      "pc": "0x00000038",
      "instruction": "addi x5, x5, 1",
      "instr_count": 12,
      "gpr_bitstream": {"x0": "0x00000000", ..., "x31": "0x..."},
      "gpr_iss":       {"x0": "0x00000000", ..., "x31": "0x..."}
    }

Register values are 8-digit hex strings so the file is readable and exact.
`pc` is the PC of the instruction about to execute at the checkpoint, and
`instr_count` (optional, an addition of ours; typically checkpoint_id *
strobe_counter) is how many instructions had completed before it. The
re-constructor needs it to replay loops exactly. `mismatch` (a list of
register names) is derived on load, never stored, so it can't go stale.

Producing one from the PCAP bridge's output:

    state = bridge.capture()              # {"pc": int, "regs": {0..31: int}}
    write_checkpoint("cp.json", 12, state["pc"], "addi x5, x5, 1",
                     state["regs"], iss_regs)
"""
import json

NUM_REGS = 32
RAM_BASE = 0x80000000
RAM_SIZE = 0x10000


def normalize(v, ram_base=RAM_BASE):
    """Addresses in the program's RAM window [ram_base, ram_base+64K] -> 0-based offset;
    everything else unchanged. The board's BRAM ignores the upper address bits, so one
    program holds both 0x8000xxxx (lui-built) and 0x0000xxxx (auipc/return-address)
    pointers for the same locations; comparing normalized values treats them as equal.
    Used for the board, QEMU and RTL sides alike."""
    v &= 0xFFFFFFFF
    return v - ram_base if ram_base <= v <= ram_base + RAM_SIZE else v



def _hex32(v):
    if not 0 <= v <= 0xFFFFFFFF:
        raise ValueError("value out of 32-bit range: %r" % (v,))
    return "0x%08x" % v


def _regs_to_json(regs):
    missing = [i for i in range(NUM_REGS) if i not in regs]
    if missing:
        raise ValueError("register set missing x%s" % missing)
    return {"x%d" % i: _hex32(regs[i]) for i in range(NUM_REGS)}


def _regs_from_json(d):
    out = {}
    for i in range(NUM_REGS):
        key = "x%d" % i
        if key not in d:
            raise ValueError("checkpoint missing register %s" % key)
        out[i] = int(d[key], 16)
    return out


def write_checkpoint(path, checkpoint_id, pc, instruction, regs_bitstream, regs_iss,
                     instr_count=None):
    """regs_*: dicts {0..31: int}. Writes the checkpoint JSON file."""
    doc = {
        "checkpoint_id": int(checkpoint_id),
        "pc": _hex32(pc),
        "instruction": str(instruction),
        "gpr_bitstream": _regs_to_json(regs_bitstream),
        "gpr_iss": _regs_to_json(regs_iss),
    }
    if instr_count is not None:
        doc["instr_count"] = int(instr_count)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")


def load_checkpoint(path):
    """Returns dict with ints: checkpoint_id, pc, instruction, instr_count (or None),
    gpr_bitstream, gpr_iss, plus mismatch (sorted list of register numbers where the two sets differ)."""
    with open(path) as f:
        doc = json.load(f)
    for key in ("checkpoint_id", "pc", "instruction", "gpr_bitstream", "gpr_iss"):
        if key not in doc:
            raise ValueError("checkpoint missing field %r" % key)
    hw = _regs_from_json(doc["gpr_bitstream"])
    iss = _regs_from_json(doc["gpr_iss"])
    return {
        "checkpoint_id": int(doc["checkpoint_id"]),
        "pc": int(doc["pc"], 16),
        "instruction": doc["instruction"],
        "instr_count": int(doc["instr_count"]) if "instr_count" in doc else None,
        "gpr_bitstream": hw,
        "gpr_iss": iss,
        "mismatch": [i for i in range(NUM_REGS) if hw[i] != iss[i]],
    }
