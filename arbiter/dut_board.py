"""
BoardDUT: the PicoRV32 on the PYNQ-Z2 as seen by the arbiter.

Two pieces of hardware are involved:
  * the PCAP bridge (pcap/pcap_bridge.py) reads the PC and 32 registers while the core is halted;
  * the PL step mailbox (the strobe counter / pause control) runs the core for a requested
    number of instructions and halts it. NOT BUILT YET: this file is its software side and
    the register layout below is the interface the PL block must implement.

Step mailbox (an AXI GPIO with two channels, base address `gpio_base`, default 0x41210000):

  channel 1, offset 0x0, PS -> PL, "request":
      bit 31      request toggle. The PL starts a request whenever this bit differs from the
                  last value it saw. (The PL takes the current value as the baseline while
                  the core is in reset, so a stale toggle from an earlier run is never
                  mistaken for a request.)
      bits 29:0   k, how many more instructions to run
  channel 2, offset 0x8, PL -> PS, "status":
      bit 31      HALTED   the core is stopped and its state is stable (PCAP readback is safe)
      bit 30      TRAPPED  the core hit a trap (PicoRV32 `trap`) before the requested count
      bits 29:0   n, instructions completed since reset

  After reset is released the core runs until n = 0 and halts. "n instructions completed"
  has one meaning everywhere in FERIVer: n instructions have retired and the next one is
  at the PC; it is the value of PicoRV32's count_instr minus the instruction being decoded,
  exactly as the re-constructor samples it.

Status reads never change the core. A PCAP capture must not advance it or reset the count;
state_at() checks that.
"""
import time

HALTED, TRAPPED, COUNT_MASK = 1 << 31, 1 << 30, (1 << 30) - 1
REQUEST_REG, STATUS_REG = 0x0, 0x8


class BoardDUT:
    def __init__(self, bridge, gpio_base=0x41210000, timeout_s=10.0, mmio=None,
                 initial_toggle=0):
        """bridge: PCAPBridge. mmio: any object with read(off)/write(off, val); defaults to
        pynq.MMIO(gpio_base). initial_toggle: the request toggle the PL last saw (0 after
        load())."""
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if mmio is None:
            from pynq import MMIO
            mmio = MMIO(gpio_base, 0x10000)
        self.io, self.bridge, self.timeout_s = mmio, bridge, timeout_s
        self.toggle = HALTED if initial_toggle else 0

    # -- loading -----------------------------------------------------------------
    def load(self, image, bram_base=0x40010000, reset_pin=None, bram=None):
        """Put the core in reset, write the workload at BRAM offset 0, reset the mailbox
        request to 0, release reset, and wait for the core to halt at n = 0.

        The register file lives in LUTRAM and is NOT cleared by reset. For a clean start
        reload the bitstream first (pynq.Overlay(bit) re-download), otherwise registers the
        program never writes keep the previous run's values and show up as false mismatches.
        UNTESTED on hardware."""
        if reset_pin is None:
            from pynq import GPIO
            reset_pin = GPIO(GPIO.get_gpio_pin(0), "out")
        if bram is None:
            from pynq import MMIO
            bram = MMIO(bram_base, 0x10000)
        padded = bytes(image) + b"\x00" * (-len(image) % 4)
        reset_pin.write(0)
        time.sleep(0.01)
        for off in range(0, len(padded), 4):
            bram.write(off, int.from_bytes(padded[off:off + 4], "little"))
        self.io.write(REQUEST_REG, 0)
        self.toggle = 0
        reset_pin.write(1)
        self._wait(0)

    # -- stepping ----------------------------------------------------------------
    def _wait(self, target):
        deadline = time.monotonic() + self.timeout_s
        status = 0
        while time.monotonic() < deadline:
            status = self.io.read(STATUS_REG)
            if status & HALTED:
                if status & TRAPPED:
                    raise RuntimeError("DUT trapped before the requested instruction boundary "
                                       "(n=%d)" % (status & COUNT_MASK))
                if (status & COUNT_MASK) == target:
                    return
            time.sleep(0.0001)
        raise TimeoutError("DUT did not halt at n=%d; last status=0x%08x" % (target, status))

    def state_at(self, n):
        """Run the DUT forward to exactly n instructions completed, capture, return state."""
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= COUNT_MASK:
            raise ValueError("instruction count must fit 30 bits")
        status = self.io.read(STATUS_REG)
        if not status & HALTED:
            self._wait_initial()
            status = self.io.read(STATUS_REG)
        if status & TRAPPED:
            raise RuntimeError("DUT is trapped")
        current = status & COUNT_MASK
        if n < current:
            raise ValueError("DUT cannot move backward")
        if n > current:
            self.toggle ^= HALTED
            self.io.write(REQUEST_REG, self.toggle | (n - current))
            self._wait(n)
        state = self.bridge.capture()
        # Capture/readback must not advance the DUT or reset its counter.
        if self.io.read(STATUS_REG) != (HALTED | n):
            raise RuntimeError("DUT state changed during PCAP readback")
        return state

    def _wait_initial(self):
        """Only the initial run to n = 0 (after reset) may still be in progress."""
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            status = self.io.read(STATUS_REG)
            if status & HALTED:
                return
            time.sleep(0.0001)
        raise TimeoutError("DUT never halted; last status=0x%08x" % status)
