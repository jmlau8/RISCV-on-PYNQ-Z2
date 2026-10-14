#!/usr/bin/env python3
"""
FERIVer ISS side: get the PC and all 32 registers from QEMU after exactly N
instructions of the workload. This is the `gpr_iss` half of a checkpoint.

    python3 qemu_state.py --image quicksort_qemu.elf --n 300
    python3 qemu_state.py --image quicksort_qemu.elf --n 100 200 300 --out iss.json

How it works: starts qemu-system-riscv32 (virt machine) halted with its GDB
stub open, speaks the GDB remote protocol directly (no gdb needed), runs the
boot ROM up to the program's entry point, and then single-steps. Instruction
count n means: n instructions of the PROGRAM have completed (n = 0 is the state
at the program's first instruction). That is the same convention as the board's
instr_count and the re-constructor.

Matching the board:
  * The hardware starts with every register 0 and the program linked at 0; the
    QEMU build is linked at 0x80000000 and the virt boot ROM leaves a few
    registers non-zero (hart id, device-tree pointer...). So at the entry point
    x1..x31 are zeroed, and (default, --no-rebase to turn off) PC and any
    register value inside the program's RAM window [ram_base, ram_base+64K) have
    ram_base subtracted. With identical code at both bases, every pointer differs
    by exactly ram_base, so this gives the values the board would hold.
    validate_qemu.py checks this against the RV32I reference at every instruction.

Python use (e.g. from the arbiter):
    from qemu_state import QemuState
    with QemuState("quicksort_qemu.elf") as q:
        pc, regs = q.state_at(300)       # regs = {0..31: int}; call with increasing n
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time

MASK32 = 0xFFFFFFFF
RAM_BASE = 0x80000000
RAM_SIZE = 0x10000          # 64 KB, same as the board's BRAM


class GdbRsp:
    """Just enough of the GDB remote serial protocol."""

    def __init__(self, host, port, timeout=10.0):
        deadline = time.time() + timeout
        while True:
            try:
                self.s = socket.create_connection((host, port), timeout=2.0)
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("could not connect to QEMU's gdb stub on port %d" % port)
                time.sleep(0.05)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # tiny packets: avoid ~40 ms Nagle/delayed-ACK stalls
        self.s.settimeout(30.0)
        self.buf = b""

    def _read_packet(self):
        while True:
            start = self.buf.find(b"$")
            if start >= 0:
                end = self.buf.find(b"#", start)
                if end >= 0 and len(self.buf) >= end + 3:
                    data = self.buf[start + 1:end]
                    self.buf = self.buf[end + 3:]
                    self.s.sendall(b"+")
                    return data.decode()
            chunk = self.s.recv(65536)
            if not chunk:
                raise RuntimeError("QEMU closed the gdb connection")
            self.buf += chunk

    def command(self, data):
        cs = sum(data.encode()) & 0xFF
        self.s.sendall(b"$" + data.encode() + b"#" + ("%02x" % cs).encode())
        return self._read_packet()

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def normalize(v, ram_base=RAM_BASE):
    """Map an address in the program's RAM window [ram_base, ram_base+64K] to its
    0-based offset; any other value is returned unchanged. Apply the SAME function
    to the board's registers/PC and to QEMU's before comparing: the board's BRAM
    ignores the upper address bits, so the board holds a mix of 0x8000xxxx
    (absolute addresses, e.g. lui/addi) and 0x0000xxxx (PC-relative, e.g. auipc,
    return addresses) values for what are the same locations."""
    v &= MASK32
    return v - ram_base if ram_base <= v <= ram_base + RAM_SIZE else v


def _le_hex(v):
    return (v & MASK32).to_bytes(4, "little").hex()


class QemuState:
    def __init__(self, image, ram_base=RAM_BASE, rebase=True, qemu="qemu-system-riscv32",
                 port=None, entry=None):
        self.image = os.path.abspath(image)
        self.ram_base = ram_base
        self.rebase = rebase
        self.entry = ram_base if entry is None else entry
        self.qemu = qemu
        self.port = port
        self.proc = None
        self.gdb = None
        self.n = 0                      # program instructions completed so far
        self._boot = {}                 # fallback only, see _zero_boot_regs

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self):
        if shutil.which(self.qemu) is None:
            raise RuntimeError("%s not found (sudo apt install qemu-system-misc)" % self.qemu)
        if self.port is None:
            with socket.socket() as t:
                t.bind(("127.0.0.1", 0))
                self.port = t.getsockname()[1]
        args = [self.qemu, "-M", "virt", "-bios", "none", "-nographic", "-monitor", "none",
                "-serial", "none", "-S", "-gdb", "tcp:127.0.0.1:%d" % self.port]
        if self.image.lower().endswith((".elf", ".out")) or self._is_elf(self.image):
            args += ["-kernel", self.image]
        else:       # flat binary linked at ram_base
            args += ["-device", "loader,file=%s,addr=0x%x,cpu-num=0" % (self.image, self.ram_base)]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.gdb = GdbRsp("127.0.0.1", self.port)
        self.gdb.command("?")
        self._run_to_entry()
        return self

    def __exit__(self, *exc):
        if self.gdb:
            self.gdb.close()
        if self.proc:
            self.proc.kill()
            self.proc.wait()

    @staticmethod
    def _is_elf(path):
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"

    # -- raw access --------------------------------------------------------
    def _raw_state(self):
        g = self.gdb.command("g")
        words = [int.from_bytes(bytes.fromhex(g[i:i + 8]), "little") for i in range(0, 33 * 8, 8)]
        return words[32], {i: words[i] for i in range(32)}

    def _step(self):
        r = self.gdb.command("s")
        if not r or r[0] not in "ST":
            raise RuntimeError("unexpected reply to step: %r" % r)

    def _run_to_entry(self):
        """Step the boot ROM until the program's first instruction, then zero x1..x31."""
        for _ in range(1000):
            pc, _regs = self._raw_state()
            if pc == self.entry:
                break
            self._step()
        else:
            raise RuntimeError("never reached the entry point 0x%x (wrong image or --ram-base?)" % self.entry)
        self._zero_boot_regs()
        self.n = 0

    def _zero_boot_regs(self):
        """The virt boot ROM leaves hart id / device-tree pointers in a0-a2 (x10-x12) and t0.
        The board starts with all registers 0, so clear x1..x31. Different QEMU versions
        accept different write packets, so verify by reading back and fall back."""
        force = os.environ.get("QEMU_STATE_FORCE", "")      # testing hook: "G" or "shadow"

        def nonzero():
            return [i for i, v in self._raw_state()[1].items() if i and v]

        if force not in ("G", "shadow"):
            for i in range(1, 32):
                self.gdb.command("P%x=%s" % (i, _le_hex(0)))
            if not nonzero():
                return
        if force != "shadow":
            self.gdb.command("G" + "".join(_le_hex(0) for _ in range(32)) + _le_hex(self.entry))
            if not nonzero() and self._raw_state()[0] == self.entry:
                return
        # last resort: this QEMU will not let us write registers. Remember the boot values
        # and report a register as 0 while it still holds exactly its boot value.
        self._boot = {i: v for i, v in self._raw_state()[1].items() if i and v}
        print("warning: could not clear QEMU's boot registers (%s); treating registers that "
              "still hold their boot value as 0" % ", ".join("x%d" % i for i in sorted(self._boot)),
              file=sys.stderr)

    def _to_board(self, v):
        return normalize(v, self.ram_base) if self.rebase else v

    # -- API ---------------------------------------------------------------
    def state(self):
        """(pc, regs) after self.n instructions, in board terms."""
        pc, regs = self._raw_state()
        regs = {i: (0 if self._boot.get(i) == v else v) for i, v in regs.items()}
        return self._to_board(pc), {i: self._to_board(v) for i, v in regs.items()}

    def state_at(self, n):
        if n < self.n:
            raise ValueError("can only move forward: at %d, asked for %d" % (self.n, n))
        while self.n < n:
            self._step()
            self.n += 1
        return self.state()


def _fmt(n, pc, regs):
    return {"n": n, "pc": "0x%08x" % pc, "regs": {"x%d" % i: "0x%08x" % regs[i] for i in range(32)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="workload built for QEMU (ELF, or flat .bin linked at --ram-base)")
    ap.add_argument("--n", type=int, nargs="+", required=True, help="instruction count(s) to capture")
    ap.add_argument("--out", help="write the captured states to this JSON file")
    ap.add_argument("--ram-base", type=lambda s: int(s, 0), default=RAM_BASE)
    ap.add_argument("--no-rebase", action="store_true", help="keep raw QEMU addresses (0x80000000 based)")
    ap.add_argument("--qemu", default="qemu-system-riscv32")
    args = ap.parse_args()

    results = []
    with QemuState(args.image, ram_base=args.ram_base, rebase=not args.no_rebase, qemu=args.qemu) as q:
        for n in sorted(set(args.n)):
            pc, regs = q.state_at(n)
            results.append(_fmt(n, pc, regs))
    for r in results:
        nz = {k: v for k, v in r["regs"].items() if int(v, 16)}
        print("n=%d  pc=%s  nonzero: %s" % (r["n"], r["pc"], nz))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results if len(results) > 1 else results[0], f, indent=2)
            f.write("\n")
        print("wrote", args.out)


if __name__ == "__main__":
    main()
