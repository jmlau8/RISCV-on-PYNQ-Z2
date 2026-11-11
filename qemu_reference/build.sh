#!/bin/bash
# Build one workload for both QEMU and the board (identical instruction stream).
# Usage (from qemu_reference/):  ./build.sh ssort     ->  ssort/ssort_qemu.elf + ssort/ssort_unified.bin
set -e
N=$1; R=$2          # optional R: repeat the work R times -> outputs ${N}_r${R}_qemu.elf / ${N}_r${R}_unified.bin
[ -f "$N/$N.c" ] || { echo "no $N/$N.c"; exit 1; }
T=$N; EXTRA=""
if [ -n "$R" ]; then T="${N}_r${R}"; EXTRA="-DREPS=$R"; fi
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O0 -ffreestanding -nostdlib \
    -DRAM_BASE=0x80000000 $EXTRA -T "$N/linker_qemu.ld" "$N/crt0.S" "$N/$N.c" -o "$N/${T}_qemu.elf"
riscv64-unknown-elf-objcopy -O binary "$N/${T}_qemu.elf" "$N/${T}_unified.bin"
riscv64-unknown-elf-size "$N/${T}_qemu.elf" | tail -1
