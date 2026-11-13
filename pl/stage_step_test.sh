#!/bin/bash
# Gather everything the board scripts need into ONE flat folder (they expect all files side by side).
#
# On the PYNQ, from a fresh clone:
#     git clone https://github.com/jmlau8/RISCV-on-PYNQ-Z2.git
#     bash RISCV-on-PYNQ-Z2/pl/stage_step_test.sh [destination]
# destination defaults to /home/xilinx/jupyter_notebooks/step_test_fresh (it must not exist yet).
# Then open that folder in Jupyter and run step_arbiter_run.py as in the notes.
set -eu

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-/home/xilinx/jupyter_notebooks/step_test_fresh}"

if [ -e "$DEST" ]; then
    echo "ERROR: $DEST already exists. Pick another folder name (nothing was changed)." >&2
    exit 1
fi

FILES="
pl/bitstream/step.bit
pl/bitstream/step.hwh
pl/step_arbiter_run.py
pl/step_board_test.py
pl/step_speed_sweep.py
pl/pcap_settle_check.py
pl/pcap_timing.py
pl/expected_states.json
pl/expected_quicksort_all.json
pl/iss_states_quicksort.json
pl/quicksort_faulty.bin
pl/patterns/patterns.bin
pl/patterns/expected_patterns.json
pcap/pcap_bridge.py
pcap/decoder.py
pcap/full_decoder_table_step.json
pcap/pc_decoder_table_step.json
arbiter/arbiter.py
arbiter/dut_board.py
arbiter/iss_file.py
arbiter/iss_remote.py
reconstructor/qemu_state.py
reconstructor/checkpoint.py
reconstructor/rv32i.py
qemu_reference/quicksort/quicksort_unified.bin
qemu_reference/quicksort/quicksort_r83_unified.bin
qemu_reference/ssort/ssort_unified.bin
qemu_reference/ssort/ssort_r37_unified.bin
qemu_reference/md5/md5_unified.bin
qemu_reference/md5/md5_r24_unified.bin
"

missing=0
for f in $FILES; do
    if [ ! -f "$REPO/$f" ]; then
        echo "MISSING in repo: $f" >&2
        missing=1
    fi
done
if [ "$missing" -ne 0 ]; then
    echo "ERROR: the repo is incomplete (see above). Nothing was copied." >&2
    exit 1
fi

mkdir -p "$DEST"
for f in $FILES; do
    cp "$REPO/$f" "$DEST/"
done

echo "Copied $(echo $FILES | wc -w) files to $DEST"
echo "step.bit md5 (the notes say what it should be):"
md5sum "$DEST/step.bit"
