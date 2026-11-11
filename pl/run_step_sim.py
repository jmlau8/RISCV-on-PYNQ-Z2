#!/usr/bin/env python3
"""Simulate the PL step block (step_ctrl + gated PicoRV32) and check it against the
re-constructor's RTL trace.   python3 pl/run_step_sim.py   (from the repo root)"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECON = os.path.join(ROOT, "reconstructor")
sys.path.insert(0, RECON)
IMAGE = os.path.join(ROOT, "qemu_reference", "quicksort", "quicksort_unified.bin")


def sim(mode, image, work, ref=None, targets=None, axi=False):
    from cocotb_tools.runner import get_runner
    r = get_runner("icarus")
    build = os.path.join(work, "build_" + mode)
    top = "step_axi_top" if axi else "step_top"
    files = (("step_axi_top.v", "pico_step.v", "ps_picorv32.v", "step_ctrl.v", "step_gate.v") if axi
             else ("step_top.v", "step_ctrl.v", "step_gate.v"))
    srcs = [os.path.join(HERE, f) for f in files]
    if not axi:
        srcs.append(os.path.join(RECON, "rtl", "picorv32.v"))
    r.build(sources=srcs, hdl_toplevel=top, build_dir=build, build_args=["-g2012"], always=True)
    env = {"STEP_IMAGE": os.path.abspath(image), "STEP_MODE": mode}
    if ref:
        env["STEP_REF"] = ref
    if targets:
        env["STEP_TARGETS"] = ",".join(map(str, targets))
    res = r.test(hdl_toplevel=top, test_module="test_step_cocotb", test_dir=HERE,
                 build_dir=build, extra_env=env)
    return res


def main():
    import reconstruct
    from cocotb_tools.runner import get_results
    work = tempfile.mkdtemp(prefix="stepsim_")
    ref = os.path.join(work, "ref.json")
    reconstruct.run_sim(IMAGE, ref, os.path.join(work, "refsim"), "trace", maxn=1250)
    # a dense start, then strides, then the end of the workload
    targets = list(range(1, 60)) + list(range(60, 1251, 7)) + [1250]
    targets = sorted(set(targets))
    ok = True
    for axi in (False, True):
        for mode, kw in (("compare", dict(ref=ref, targets=targets)), ("trap", {}), ("reset", {})):
            path = sim(mode, IMAGE if mode != "trap" else make_trap_image(work), work, axi=axi, **kw)
            passed, failed = get_results(path)
            print("%s %-8s passed=%d failed=%d" % ("board-style (AXI, pico_step)" if axi else "simple memory", mode, passed, failed))
            ok &= failed == 0
    sys.exit(0 if ok else 1)


def make_trap_image(work):
    p = os.path.join(work, "trap.bin")
    words = [0x00100093, 0x00200113, 0x00300193, 0xFFFFFFFF, 0x00000013]   # addi x1..x3, illegal
    open(p, "wb").write(b"".join(w.to_bytes(4, "little") for w in words))
    return p


if __name__ == "__main__":
    main()
