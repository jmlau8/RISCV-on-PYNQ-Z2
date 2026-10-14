#!/bin/bash
# Build ONE program for both QEMU and the board, so both execute the identical instruction stream.
# Usage: ./build_workload.sh quicksort.c crt0.S linker_qemu.ld   (outputs quicksort_qemu.elf + quicksort_unified.bin)
# Needs: sudo apt install gcc-riscv64-unknown-elf qemu-system-misc   (or your notebook's toolchain)
set -e
SRC=${1:-quicksort.c}; CRT=${2:-crt0.S}; LD=${3:-linker_qemu.ld}
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O0 -ffreestanding -nostdlib \
    -DRAM_BASE=0x80000000 -T "$LD" "$CRT" "$SRC" -o quicksort_qemu.elf
riscv64-unknown-elf-objcopy -O binary quicksort_qemu.elf quicksort_unified.bin
echo "built quicksort_qemu.elf (for QEMU) and quicksort_unified.bin (for the board / re-constructor)"
