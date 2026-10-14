"""
Board side: run quicksort_unified.bin to completion on the PicoRV32, then read its
whole state through PCAP and save it as board_final.json.

Run in a Jupyter notebook on the PYNQ-Z2, in the same folder as pcap_bridge.py,
decoder.py, full_decoder_table.json, pc_decoder_table.json, the .bit/.hwh and
quicksort_unified.bin. Use a FRESH kernel (Kernel > Restart) so the register file
starts clean: resetn does not clear the LUTRAM register file, so stale values from
earlier runs would show up as false mismatches.

It checks two things on the way:
  1. the program really ran: sorted array at BRAM 0x400.., status 0xBEEF0002 at 0x3FC
     (proves a program linked at 0x80000000 runs from BRAM offset 0, i.e. the upper
      address bits are ignored by the BRAM path)
  2. the PCAP capture: writes board_final.json = {"pc": ..., "regs": {"0": ..., ... "31": ...}}
"""
import json, time
from pynq import Overlay, MMIO, GPIO
from pcap_bridge import PCAPBridge

BITSTREAM = "design_1_wrapper_verified.bit"     # change if yours has another name/path
IMAGE = "quicksort_unified.bin"
OUT = "board_final.json"
EXPECTED_SORTED = [3, 8, 17, 29, 42, 55, 71, 93]

ol = Overlay(BITSTREAM)                          # PL must be programmed before any MMIO
BRAM_BASE = 0x40010000
bram = MMIO(BRAM_BASE, 0x10000)
reset_pin = GPIO(GPIO.get_gpio_pin(0), 'out')

image = open(IMAGE, "rb").read()
image += b"\x00" * (-len(image) % 4)

# hold the core in reset, clear the result area, load the program, release reset
reset_pin.write(0); time.sleep(0.01)
for off in range(0x3FC, 0x420, 4):
    bram.write(off, 0)
for i in range(0, len(image), 4):
    bram.write(i, int.from_bytes(image[i:i + 4], "little"))
reset_pin.write(1)
time.sleep(0.5)                                  # ~1250 instructions: far less than this

status = bram.read(0x3FC)
result = [bram.read(0x400 + 4 * i) for i in range(8)]
signed = [v - (1 << 32) if v & 0x80000000 else v for v in result]
print("status word : 0x%08x  (expect 0xbeef0002)" % status)
print("sorted array:", signed, "(expect %s)" % EXPECTED_SORTED)
ran_ok = (status == 0xBEEF0002 and signed == EXPECTED_SORTED)
print("program ran correctly from the unified image:", ran_ok)
if not ran_ok:
    print("-> do NOT trust a capture yet. Tell Claude what the two lines above print.")

bridge = PCAPBridge()
s = bridge.capture()
bridge.close()
print("captured PC = 0x%08x" % s["pc"])
print("nonzero regs:", {("x%d" % r): hex(v) for r, v in s["regs"].items() if v})
json.dump({"pc": s["pc"], "regs": {str(k): v for k, v in s["regs"].items()}}, open(OUT, "w"))
print("saved", OUT, "- copy it to ~/recon in WSL")
