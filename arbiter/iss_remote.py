"""
RemoteISS: a live QEMU that runs on another machine (e.g. your PC in WSL) and answers the arbiter
over the network. Same interface as qemu_state.QemuState: state_at(n) -> (pc, regs), forward only.

Use it when QEMU is not installed on the PYNQ. (The paper runs QEMU on the board's ARM; this is a
stand-in for that, so say so when you report results.)

On the machine with QEMU (WSL; needs qemu-system-riscv32 and reconstructor/qemu_state.py):
    python3 arbiter/iss_remote.py serve --port 5555 [--token SECRET]

On the board (inside the arbiter script):
    from iss_remote import RemoteISS
    iss = RemoteISS("192.168.x.y", 5555, open("quicksort_unified.bin", "rb").read(), token="SECRET")
    ...
    iss.close()

Each connection gets its own fresh QEMU, started from the image the client sends, so every run
starts at instruction 0 and any workload works without restarting the server.
Protocol: one JSON object per line.   no authentication beyond the optional token -> keep it on your LAN.
"""
import argparse
import base64
import json
import os
import socket
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(os.path.dirname(HERE), "reconstructor")
if RECON not in sys.path:
    sys.path.insert(0, RECON)

MAX_IMAGE = 1 << 20          # 1 MiB; the board's program memory is 64 KiB


# ----------------------------------------------------------------------------- client
class RemoteISS:
    def __init__(self, host, port, image, token="", timeout_s=30.0):
        self.sock = socket.create_connection((host, port), timeout=timeout_s)
        self.sock.settimeout(timeout_s)
        self.f = self.sock.makefile("rwb")
        self.lock = threading.Lock()
        self.current = 0
        self._call({"op": "start", "token": token, "image": base64.b64encode(image).decode()})

    def _call(self, msg):
        with self.lock:
            self.f.write((json.dumps(msg) + "\n").encode())
            self.f.flush()
            line = self.f.readline()
        if not line:
            raise RuntimeError("ISS server closed the connection")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise RuntimeError("ISS server error: %s" % reply.get("error"))
        return reply

    def state_at(self, n):
        if n < self.current:
            raise ValueError("ISS cannot move backward")
        r = self._call({"op": "state", "n": n})
        self.current = n
        return r["pc"], {int(i): v for i, v in r["regs"].items()}

    def close(self):
        try:
            self.f.close()
            self.sock.close()
        except OSError:
            pass


# ----------------------------------------------------------------------------- server
def _serve_one(conn, token, qemu):
    from qemu_state import QemuState        # imported here so the client needs no cocotb/qemu
    f = conn.makefile("rwb")

    def send(obj):
        f.write((json.dumps(obj) + "\n").encode())
        f.flush()

    state, tmpdir = None, tempfile.mkdtemp(prefix="iss_remote_")
    try:
        for line in f:
            try:
                msg = json.loads(line)
                if msg["op"] == "start":
                    if token and msg.get("token") != token:
                        raise PermissionError("bad token")
                    if state is not None:
                        raise RuntimeError("already started")
                    image = base64.b64decode(msg["image"])
                    if not 0 < len(image) <= MAX_IMAGE:
                        raise ValueError("image size out of range")
                    path = os.path.join(tmpdir, "image.bin")
                    open(path, "wb").write(image)
                    state = QemuState(path, qemu=qemu).__enter__()
                    send({"ok": True})
                elif msg["op"] == "state":
                    if state is None:
                        raise RuntimeError("not started")
                    n = msg["n"]
                    if type(n) is not int or n < 0:
                        raise ValueError("bad n")
                    pc, regs = state.state_at(n)
                    send({"ok": True, "pc": pc, "regs": {str(i): v for i, v in regs.items()}})
                else:
                    raise ValueError("unknown op")
            except Exception as e:                       # report to the client, keep serving
                send({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
    finally:
        if state is not None:
            state.__exit__(None, None, None)
        f.close()
        conn.close()
        for p in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, p))
        os.rmdir(tmpdir)


def serve(host, port, token, qemu):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    print("ISS server on %s:%d (token %s) -- Ctrl-C to stop" % (host, port, "set" if token else "none"),
          flush=True)
    while True:
        conn, addr = srv.accept()
        print("connection from %s:%d" % addr, flush=True)
        threading.Thread(target=_serve_one, args=(conn, token, qemu), daemon=True).start()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=5555)
    s.add_argument("--token", default="")
    s.add_argument("--qemu", default="qemu-system-riscv32")
    a = ap.parse_args()
    serve(a.host, a.port, a.token, a.qemu)
