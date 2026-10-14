#!/usr/bin/env python3
"""
FERIVer re-constructor: replay a mismatch checkpoint on the PicoRV32 RTL.

    python3 reconstruct.py --checkpoint cp.json --image quicksort_hw.bin --out out/

What it does (paper section 3.1.3, Cocotb + Icarus Verilog + GTKWave):
  1. reads the checkpoint (ID, PC, instruction, bitstream GPRs, ISS GPRs)
  2. simulates the same PicoRV32 configuration in Icarus Verilog from reset
     until the checkpoint instruction boundary, recording a VCD waveform
  3. compares the RTL replay's registers and PC against BOTH recorded sets
  4. writes out/report.json, out/trace.csv (every instruction up to the
     checkpoint) and out/recon.vcd (open it in GTKWave)

Where the checkpoint is: the number of instructions completed before it
("instr_count" in the checkpoint file). If the file has none, the first time
the core fetches the checkpoint's PC is used, which is only exact for
checkpoints whose PC occurs once (loops make the PC repeat).
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# recon_top.v and picorv32.v may sit in an rtl/ subfolder or right next to this script
RTL_DIR = os.path.join(HERE, "rtl") if os.path.isdir(os.path.join(HERE, "rtl")) else HERE

from checkpoint import load_checkpoint, normalize  # noqa: E402
from rv32i import disasm                        # noqa: E402


def _allow_vcd_output():
    """cocotb's Icarus runner always passes vvp the flag `-none`, which silences
    $dumpfile/$dumpvars unless its own FST option is used. The paper uses VCD, so
    swap that one flag for `-vcd` (tested with cocotb 2.1.0; a no-op if the runner
    no longer passes -none)."""
    from cocotb_tools import runner as _runner
    icarus = _runner.Icarus
    if getattr(icarus, "_recon_vcd_patched", False):
        return
    original = icarus._test_command

    def patched(self):
        return [["-vcd" if arg == "-none" else arg for arg in cmd] for cmd in original(self)]

    icarus._test_command = patched
    icarus._recon_vcd_patched = True


def run_sim(image, out_json, build_dir, mode, vcd=None, target=None, target_pc=None,
            maxn=None, context=20):
    from cocotb_tools.runner import get_runner
    if vcd:
        _allow_vcd_output()
    runner = get_runner("icarus")
    runner.build(
        sources=[os.path.join(RTL_DIR, "recon_top.v"), os.path.join(RTL_DIR, "picorv32.v")],
        hdl_toplevel="recon_top",
        build_dir=build_dir,
        build_args=["-g2012"],
        always=True,
    )
    env = {"RECON_IMAGE": os.path.abspath(image), "RECON_OUT": os.path.abspath(out_json),
           "RECON_MODE": mode, "RECON_CONTEXT": str(context)}
    if target is not None:
        env["RECON_TARGET"] = str(target)
    if target_pc is not None:
        env["RECON_TARGET_PC"] = hex(target_pc)
    if maxn is not None:
        env["RECON_MAXN"] = str(maxn)
    plusargs = ["+vcd=" + os.path.abspath(vcd)] if vcd else []
    runner.test(
        hdl_toplevel="recon_top",
        test_module="recon_cocotb",
        test_dir=HERE,
        build_dir=build_dir,
        extra_env=env,
        plusargs=plusargs,
    )


def diff_regs(a, b):
    return [i for i in range(32) if a[i] != b[i]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--image", required=True, help="workload binary loaded at address 0")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--context", type=int, default=20, help="extra cycles to simulate after the checkpoint")
    ap.add_argument("--no-vcd", action="store_true")
    args = ap.parse_args()

    cp = load_checkpoint(args.checkpoint)
    if cp["instr_count"] is None:
        print("note: checkpoint has no instr_count; replaying to the FIRST fetch of pc 0x%x "
              "(exact only if that PC is executed once before the checkpoint)" % cp["pc"])
    os.makedirs(args.out, exist_ok=True)
    out_json = os.path.join(args.out, "replay_raw.json")
    vcd = None if args.no_vcd else os.path.join(args.out, "recon.vcd")

    run_sim(args.image, out_json, os.path.join(args.out, "sim_build"), "replay", vcd=vcd,
            target=cp["instr_count"], target_pc=None if cp["instr_count"] is not None else cp["pc"],
            context=args.context)
    raw = json.load(open(out_json))
    hit = raw["checkpoint"]
    rtl = [normalize(v) for v in hit["regs"]]      # compare in normalized address terms (see checkpoint.normalize)
    hit["pc"] = normalize(hit["pc"])

    with open(os.path.join(args.out, "trace.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "pc", "insn", "mnemonic"])
        for n, pc, insn in raw["fetch_log"]:
            w.writerow([n, "0x%08x" % pc, "0x%08x" % insn, disasm(insn)])

    mism_hw_vs_iss = cp["mismatch"]
    d_rtl_hw = diff_regs(rtl, cp["gpr_bitstream"])
    d_rtl_iss = diff_regs(rtl, cp["gpr_iss"])
    pc_ok = {"bitstream_pc": cp["pc"] == hit["pc"]}

    if not mism_hw_vs_iss and not d_rtl_hw:
        verdict = "no mismatch: hardware, ISS and RTL replay all agree"
    elif mism_hw_vs_iss and not d_rtl_iss:
        verdict = ("hardware deviates: the RTL replay agrees with the ISS, so the board's "
                   "bitstream state is the odd one out (registers %s)" % ["x%d" % r for r in d_rtl_hw])
    elif mism_hw_vs_iss and not d_rtl_hw:
        verdict = ("ISS deviates: the RTL replay reproduces the hardware values, so the "
                   "ISS (or its configuration) disagrees with the RTL (registers %s)"
                   % ["x%d" % r for r in mism_hw_vs_iss])
    else:
        verdict = ("all three disagree: the RTL replay matches neither the hardware nor the "
                   "ISS (check the workload image, reset state, or whether the checkpoint "
                   "instruction count is right)")

    if not pc_ok["bitstream_pc"]:
        verdict = ("PC differs: the checkpoint says 0x%08x but the RTL replay is at 0x%08x after %d "
                   "instructions (wrong workload image, wrong instr_count, or the PC itself is the "
                   "fault). Register comparison: %s"
                   % (cp["pc"], hit["pc"], hit["n"], verdict))

    report = {
        "checkpoint_id": cp["checkpoint_id"],
        "instructions_completed": hit["n"],
        "pc_rtl": "0x%08x" % hit["pc"],
        "pc_checkpoint": "0x%08x" % cp["pc"],
        "pc_matches": pc_ok["bitstream_pc"],
        "instruction_rtl": disasm(hit["insn"]),
        "instruction_checkpoint": cp["instruction"],
        "registers_differing_hw_vs_iss": ["x%d" % r for r in mism_hw_vs_iss],
        "registers_differing_rtl_vs_hw": ["x%d" % r for r in d_rtl_hw],
        "registers_differing_rtl_vs_iss": ["x%d" % r for r in d_rtl_iss],
        "detail": {"x%d" % r: {"rtl": "0x%08x" % rtl[r],
                               "bitstream": "0x%08x" % cp["gpr_bitstream"][r],
                               "iss": "0x%08x" % cp["gpr_iss"][r]}
                   for r in sorted(set(mism_hw_vs_iss) | set(d_rtl_hw) | set(d_rtl_iss))},
        "verdict": verdict,
        "waveform": os.path.abspath(vcd) if vcd else None,
    }
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("\n=== FERIVer re-constructor: checkpoint %d ===" % cp["checkpoint_id"])
    print("replayed %d instructions; next instruction %s at pc %s"
          % (hit["n"], report["instruction_rtl"], report["pc_rtl"]))
    print("PC matches checkpoint:", report["pc_matches"])
    for r, d in report["detail"].items():
        print("  %-4s rtl=%s  bitstream=%s  iss=%s" % (r, d["rtl"], d["bitstream"], d["iss"]))
    print("verdict:", verdict)
    if vcd:
        print("waveform:", os.path.abspath(vcd))


if __name__ == "__main__":
    main()
