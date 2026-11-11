"""FileISS: serves QEMU states that were recorded earlier (arbiter/make_iss_states.py), so the arbiter
can run on the PYNQ. Same interface as qemu_state.QemuState: state_at(n) -> (pc, regs), forward only."""
import json


class FileISS:
    def __init__(self, path):
        self.states = {int(k): v for k, v in json.load(open(path)).items()}
        self.current = 0

    def state_at(self, n):
        if n < self.current:
            raise ValueError("ISS cannot move backward")
        if n not in self.states:
            raise ValueError("no recorded ISS state for n=%d (max %d)" % (n, max(self.states)))
        self.current = n
        s = self.states[n]
        return s["pc"], {i: v for i, v in enumerate(s["regs"])}
