"""
Small RV32I helpers for the re-constructor: a disassembler (so checkpoints
carry an instruction mnemonic) and a minimal instruction-set simulator used
as an independent reference when validating the RTL replay.

Covers the RV32I base integer set (no CSR, ecall/ebreak only disassembled).
Memory is a 64 KB little-endian space and upper address bits are ignored,
matching the board's BRAM (core address space 0xC0000000 / 64 KB).
"""

MASK32 = 0xFFFFFFFF


def _sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def imm_i(i): return _sext(i >> 20, 12)
def imm_s(i): return _sext(((i >> 25) << 5) | ((i >> 7) & 0x1F), 12)
def imm_u(i): return i & 0xFFFFF000
def imm_b(i):
    return _sext((((i >> 31) & 1) << 12) | (((i >> 7) & 1) << 11) |
                 (((i >> 25) & 0x3F) << 5) | (((i >> 8) & 0xF) << 1), 13)
def imm_j(i):
    return _sext((((i >> 31) & 1) << 20) | (((i >> 12) & 0xFF) << 12) |
                 (((i >> 20) & 1) << 11) | (((i >> 21) & 0x3FF) << 1), 21)


_BRANCH = {0: "beq", 1: "bne", 4: "blt", 5: "bge", 6: "bltu", 7: "bgeu"}
_LOAD = {0: "lb", 1: "lh", 2: "lw", 4: "lbu", 5: "lhu"}
_STORE = {0: "sb", 1: "sh", 2: "sw"}
_OPIMM = {0: "addi", 2: "slti", 3: "sltiu", 4: "xori", 6: "ori", 7: "andi"}
_OP = {(0, 0): "add", (0x20, 0): "sub", (0, 1): "sll", (0, 2): "slt", (0, 3): "sltu",
       (0, 4): "xor", (0, 5): "srl", (0x20, 5): "sra", (0, 6): "or", (0, 7): "and"}


def disasm(insn):
    """Mnemonic string for a 32-bit RV32I instruction word."""
    insn &= MASK32
    op = insn & 0x7F
    rd, f3, rs1, rs2, f7 = (insn >> 7) & 31, (insn >> 12) & 7, (insn >> 15) & 31, (insn >> 20) & 31, insn >> 25
    if op == 0x37: return "lui x%d, 0x%x" % (rd, imm_u(insn) >> 12)
    if op == 0x17: return "auipc x%d, 0x%x" % (rd, imm_u(insn) >> 12)
    if op == 0x6F: return "jal x%d, %d" % (rd, imm_j(insn))
    if op == 0x67 and f3 == 0: return "jalr x%d, %d(x%d)" % (rd, imm_i(insn), rs1)
    if op == 0x63 and f3 in _BRANCH: return "%s x%d, x%d, %d" % (_BRANCH[f3], rs1, rs2, imm_b(insn))
    if op == 0x03 and f3 in _LOAD: return "%s x%d, %d(x%d)" % (_LOAD[f3], rd, imm_i(insn), rs1)
    if op == 0x23 and f3 in _STORE: return "%s x%d, %d(x%d)" % (_STORE[f3], rs2, imm_s(insn), rs1)
    if op == 0x13:
        if f3 == 1 and f7 == 0: return "slli x%d, x%d, %d" % (rd, rs1, rs2)
        if f3 == 5 and f7 == 0: return "srli x%d, x%d, %d" % (rd, rs1, rs2)
        if f3 == 5 and f7 == 0x20: return "srai x%d, x%d, %d" % (rd, rs1, rs2)
        if f3 in _OPIMM: return "%s x%d, x%d, %d" % (_OPIMM[f3], rd, rs1, imm_i(insn))
    if op == 0x33 and (f7, f3) in _OP: return "%s x%d, x%d, x%d" % (_OP[(f7, f3)], rd, rs1, rs2)
    if op == 0x0F: return "fence"
    if insn == 0x00000073: return "ecall"
    if insn == 0x00100073: return "ebreak"
    return ".word 0x%08x" % insn


class ISS:
    """Minimal RV32I interpreter: step() executes one instruction."""

    def __init__(self, image=b"", mem_bytes=65536):
        self.mem = bytearray(mem_bytes)
        self.mem[:len(image)] = image
        self.regs = [0] * 32
        self.pc = 0
        self.count = 0

    def _a(self, addr): return addr & (len(self.mem) - 1)

    def load(self, addr, n, signed):
        a = self._a(addr)
        v = int.from_bytes(self.mem[a:a + n], "little")
        return _sext(v, 8 * n) & MASK32 if signed else v

    def store(self, addr, n, v):
        a = self._a(addr)
        self.mem[a:a + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def fetch(self):
        return self.load(self.pc, 4, False)

    def step(self):
        """Executes the instruction at self.pc. Returns (pc, insn)."""
        pc, insn = self.pc, self.fetch()
        op = insn & 0x7F
        rd, f3, rs1, rs2, f7 = (insn >> 7) & 31, (insn >> 12) & 7, (insn >> 15) & 31, (insn >> 20) & 31, insn >> 25
        a, b = self.regs[rs1], self.regs[rs2]
        sa, sb = _sext(a, 32), _sext(b, 32)
        nxt, val = (pc + 4) & MASK32, None
        if op == 0x37: val = imm_u(insn)
        elif op == 0x17: val = (pc + imm_u(insn)) & MASK32
        elif op == 0x6F: val, nxt = nxt, (pc + imm_j(insn)) & MASK32
        elif op == 0x67: val, nxt = nxt, (a + imm_i(insn)) & MASK32 & ~1
        elif op == 0x63:
            taken = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}[f3]
            if taken: nxt = (pc + imm_b(insn)) & MASK32
        elif op == 0x03:
            n = {0: 1, 1: 2, 2: 4, 4: 1, 5: 2}[f3]
            val = self.load(a + imm_i(insn), n, f3 in (0, 1, 2))
        elif op == 0x23:
            self.store(a + imm_s(insn), {0: 1, 1: 2, 2: 4}[f3], b)
        elif op in (0x13, 0x33):
            if op == 0x13:
                y = imm_i(insn) & MASK32
                sy, sh = _sext(y, 32), rs2
                key = (f7 if f3 in (1, 5) else 0, f3)
            else:
                y, sy, sh, key = b, sb, b & 31, (f7, f3)
            sh &= 31
            val = {
                (0, 0): a + y, (0x20, 0): a - y, (0, 1): a << sh,
                (0, 2): int(sa < sy), (0, 3): int(a < y), (0, 4): a ^ y,
                (0, 5): a >> sh, (0x20, 5): sa >> sh, (0, 6): a | y, (0, 7): a & y,
            }[key] & MASK32
        else:
            raise NotImplementedError("unsupported instruction 0x%08x at pc 0x%x" % (insn, pc))
        if val is not None and rd != 0:
            self.regs[rd] = val & MASK32
        self.pc = nxt
        self.count += 1
        return pc, insn
