"""
PCAP Bridge controller (PS side): one call does trigger -> PCAP readback ->
decode, and returns the PicoRV32's architectural state.

    from pcap_bridge import PCAPBridge
    bridge = PCAPBridge()
    state = bridge.capture()        # {"pc": int, "regs": {0: 0, 1: ..., 31: ...}}
    bridge.last_timing              # {"trigger": s, "read": s, "decode": s, "total": s}

This wraps the pieces already verified on hardware (CAPTUREE2 trigger pulse,
single-frame PCAP DMA readback, table-driven decode from decoder.py) and
removes the per-call overhead of the test scripts:
  * DMA command buffers are built once (one per frame address) and reused
  * one result buffer is reused for every frame
  * the decode is vectorized with numpy instead of Python loops
  * a DMA timeout raises TimeoutError instead of silently returning garbage

Scope: this is the trigger/read/decode sequencer. It does NOT pause or
single-step the CPU; the core keeps running while it is captured. Choosing
*when* to capture (the paper's strobe_counter / checkpoint cadence) belongs
to the arbiter.

Needs decoder.py, full_decoder_table.json, pc_decoder_table.json alongside.
Load the matching bitstream (Overlay) before creating a PCAPBridge.
"""

import time
import numpy as np
from decoder import DECODER_TABLE, PC_TABLE, STATE_FARS

GPIO_BASE = 0x41200000
GPIO_DATA = 0x0
TRIGGER_BIT = 1

DEVCFG_BASE = 0xF8007000
REG_CTRL, REG_INT_STS = 0x00, 0x0C
REG_DMA_SRC_ADDR, REG_DMA_DST_ADDR = 0x18, 0x1C
REG_DMA_SRC_LEN, REG_DMA_DST_LEN = 0x20, 0x24
CTRL_PCAP_PR_BIT, CTRL_PCAP_MODE_BIT = 27, 26
INT_DMA_DONE_BIT = 13
PCAP_DST = 0xFFFFFFFF
WORDS_PER_FRAME = 101
TOTAL_WORDS = WORDS_PER_FRAME * 2   # one dummy frame + the real frame


def _type2_header(word_count):
    return (0b010 << 29) | (0b01 << 27) | (word_count & 0x7FFFFFF)


def _command_words(far):
    return [
        0xFFFFFFFF, 0x000000BB, 0x11220044, 0xFFFFFFFF, 0xAA995566,
        0x20000000, 0x30008001, 0x00000004, 0x20000000,
        0x30002001, far, 0x28006000, _type2_header(TOTAL_WORDS),
    ] + [0x20000000] * 32


class StateDecoder:
    """Vectorized version of decoder.decode_state(), for a stacked frame matrix."""

    def __init__(self, fars):
        self.far_index = {far: i for i, far in enumerate(fars)}
        n = len(DECODER_TABLE)
        fi = np.zeros((31, 32), dtype=np.intp)
        wd = np.zeros((31, 32), dtype=np.intp)
        bt = np.zeros((31, 32), dtype=np.uint32)
        rb = np.zeros((31, 32), dtype=np.uint64)
        for reg in range(1, 32):
            entries = DECODER_TABLE[reg]
            assert len(entries) == 32, "register %d has %d bits" % (reg, len(entries))
            for j, e in enumerate(entries):
                fi[reg - 1, j] = self.far_index[e["FAR"]]
                wd[reg - 1, j] = e["word"]
                bt[reg - 1, j] = e["bit_in_word"]
                rb[reg - 1, j] = e["bit"]
        self._reg = (fi, wd, bt, rb)
        self._pc = (
            np.array([self.far_index[e["FAR"]] for e in PC_TABLE], dtype=np.intp),
            np.array([e["word"] for e in PC_TABLE], dtype=np.intp),
            np.array([e["bit_in_word"] for e in PC_TABLE], dtype=np.uint32),
            np.array([e["bit"] for e in PC_TABLE], dtype=np.uint64),
        )

    def decode(self, frames):
        """frames: uint32 array of shape (len(fars), 101), rows in `fars` order."""
        fi, wd, bt, rb = self._reg
        bits = ((frames[fi, wd] >> bt) & 1).astype(np.uint64)
        vals = (bits << rb).sum(axis=1)
        regs = {0: 0}
        for i in range(31):
            regs[i + 1] = int(vals[i])
        pfi, pwd, pbt, prb = self._pc
        pbits = ((frames[pfi, pwd] >> pbt) & 1).astype(np.uint64) ^ np.uint64(1)  # FF bits read back inverted
        pc = int((pbits << prb).sum())
        return {"pc": pc, "regs": regs}


class PCAPBridge:
    def __init__(self, fars=None, gpio_base=GPIO_BASE, trigger_bit=TRIGGER_BIT,
                 settle_s=0.005, dma_timeout_s=2.0):
        from pynq import MMIO, allocate          # imported here so the module loads off-board
        self.fars = list(fars) if fars is not None else list(STATE_FARS)
        self.settle_s = settle_s                 # pause around the trigger edge (known-good: 5 ms)
        self.dma_timeout_s = dma_timeout_s
        self.trigger_bit = trigger_bit
        self.gpio = MMIO(gpio_base, 0x10000)
        self.devcfg = MMIO(DEVCFG_BASE, 0x100)
        self._decoder = StateDecoder(self.fars)
        self._cmd = {}
        for far in self.fars:
            words = _command_words(far)
            buf = allocate(shape=(len(words),), dtype=np.uint32)
            for i, w in enumerate(words):
                buf[i] = w
            buf.flush()
            self._cmd[far] = buf
        self._res = allocate(shape=(TOTAL_WORDS,), dtype=np.uint32)
        self.last_timing = {}

    # -- low level ---------------------------------------------------------
    def _wait_dma_done(self, what):
        t0 = time.time()
        while True:
            if self.devcfg.read(REG_INT_STS) & (1 << INT_DMA_DONE_BIT):
                self.devcfg.write(REG_INT_STS, 1 << INT_DMA_DONE_BIT)
                return
            if time.time() - t0 > self.dma_timeout_s:
                raise TimeoutError("PCAP DMA timed out during %s" % what)

    def trigger(self):
        """Rising edge on the CAPTUREE2 trigger GPIO: snapshot live state into config memory."""
        self.gpio.write(GPIO_DATA, 0)
        if self.settle_s:
            time.sleep(self.settle_s)
        self.gpio.write(GPIO_DATA, 1 << self.trigger_bit)
        if self.settle_s:
            time.sleep(self.settle_s)
        self.gpio.write(GPIO_DATA, 0)

    def _read_frame_into(self, far, out_row):
        cmd = self._cmd[far]
        self.devcfg.write(REG_DMA_SRC_ADDR, cmd.physical_address)
        self.devcfg.write(REG_DMA_DST_ADDR, PCAP_DST)
        self.devcfg.write(REG_DMA_SRC_LEN, len(cmd))
        self.devcfg.write(REG_DMA_DST_LEN, 0)
        self._wait_dma_done("command phase, FAR %#x" % far)
        self.devcfg.write(REG_DMA_SRC_ADDR, PCAP_DST)
        self.devcfg.write(REG_DMA_DST_ADDR, self._res.physical_address)
        self.devcfg.write(REG_DMA_SRC_LEN, 0)
        self.devcfg.write(REG_DMA_DST_LEN, TOTAL_WORDS)
        self._wait_dma_done("readback phase, FAR %#x" % far)
        self._res.invalidate()
        out_row[:] = self._res[WORDS_PER_FRAME:2 * WORDS_PER_FRAME]

    # -- public ------------------------------------------------------------
    def read_frames(self):
        """Read every frame in self.fars (no trigger). Returns uint32 array (n_frames, 101)."""
        ctrl = self.devcfg.read(REG_CTRL)
        ctrl |= (1 << CTRL_PCAP_PR_BIT) | (1 << CTRL_PCAP_MODE_BIT)
        self.devcfg.write(REG_CTRL, ctrl)
        frames = np.zeros((len(self.fars), WORDS_PER_FRAME), dtype=np.uint32)
        for i, far in enumerate(self.fars):
            self._read_frame_into(far, frames[i])
        return frames

    def capture(self, return_frames=False):
        """Trigger CAPTUREE2, read all frames over PCAP, decode. Returns the state dict."""
        t0 = time.perf_counter()
        self.trigger()
        t1 = time.perf_counter()
        frames = self.read_frames()
        t2 = time.perf_counter()
        state = self._decoder.decode(frames)
        t3 = time.perf_counter()
        self.last_timing = {"trigger": t1 - t0, "read": t2 - t1,
                            "decode": t3 - t2, "total": t3 - t0}
        if return_frames:
            return state, {far: frames[i] for i, far in enumerate(self.fars)}
        return state

    def close(self):
        for buf in self._cmd.values():
            buf.freebuffer()
        self._res.freebuffer()
