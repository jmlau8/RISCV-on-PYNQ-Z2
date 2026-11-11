#!/usr/bin/env python3
"""
Add the FERIVer "qferiver.run:<N>" command to QEMU's gdb server: run exactly N guest instructions at full
speed (QEMU started with -icount shift=0) and stop with the normal stop reply. Without it, getting QEMU to
instruction N takes N single-step round trips through the debug port.

    python3 apply_feriver_patch.py /home/xilinx/qemu_build/qemu-7.2.0/gdbstub.c        # QEMU 7.x
    python3 apply_feriver_patch.py <qemu-8.x>/gdbstub/gdbstub.c                          # QEMU 8.x

Checks every place it needs to change BEFORE writing anything, and refuses if the file was already patched.
Then rebuild QEMU (make -j2) and run with  FERIVER_FAST_QEMU=1  (see reconstructor/qemu_state.py).
Tested: QEMU 8.2.2 (0 mismatches against single-stepping on 3 programs x 4 strobe values, ~25,000 stops).
"""
import sys

INCLUDE_ANCHOR = '#include "sysemu/runstate.h"\n'
INCLUDE_NEW = INCLUDE_ANCHOR + '#include "sysemu/cpu-timers.h"\n#include "qemu/timer.h"\n'

HANDLER_ANCHOR = "static void handle_query_curr_tid(GArray *params, void *user_ctx)"
HANDLER = '''#ifndef CONFIG_USER_ONLY
/*
 * FERIVer extension: "qferiver.run:<N hex>" runs exactly N guest instructions at full speed
 * (needs -icount shift=0, where the virtual clock advances 1 ns per instruction) and then stops
 * with the normal stop reply. Replaces N single-step round trips with one packet.
 */
static QEMUTimer *feriver_run_timer;

static void feriver_run_expired(void *opaque)
{
    vm_stop(RUN_STATE_PAUSED);
}

static void handle_feriver_run(GArray *params, void *user_ctx)
{
    uint64_t n;

    if (!params->len || !icount_enabled() || gdbserver_state.c_cpu == NULL) {
@NOSTOP@        @PUT@("E22");
        return;
    }
    n = get_param(params, 0)->val_ull;
    if (n == 0 || n > (1ULL << 40)) {
@NOSTOP@        @PUT@("E22");
        return;
    }
    if (!feriver_run_timer) {
        feriver_run_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, feriver_run_expired, NULL);
    }
    timer_mod(feriver_run_timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + icount_to_ns(n));
    cpu_single_step(gdbserver_state.c_cpu, 0);
    gdb_continue();
}
#endif

'''

TABLE_ANCHOR = '''    {
        .handler = handle_set_qemu_sstep,
        .cmd = "qemu.sstep=",
        .cmd_startswith = 1,
        .schema = "l0"
    },
};'''
TABLE_NEW = TABLE_ANCHOR[:-2] + '''#ifndef CONFIG_USER_ONLY
    {
        .handler = handle_feriver_run,
        .cmd = "feriver.run:",
        .cmd_startswith = 1,
        .schema = "L0",@STOPFLAG@
    },
#endif
};'''


def main(path):
    s = open(path).read()
    if "feriver" in s:
        sys.exit("%s already contains the FERIVer patch; nothing changed" % path)
    for what, anchor in (("include", INCLUDE_ANCHOR), ("handler position", HANDLER_ANCHOR),
                         ("command table end", TABLE_ANCHOR)):
        n = s.count(anchor)
        if n != 1:
            sys.exit("cannot patch: expected exactly 1 %s anchor, found %d. Nothing was changed.\n"
                     "Send the output of:  grep -n 'qemu.sstep\\|runstate.h\\|handle_query_curr_tid' %s"
                     % (what, n, path))
    # QEMU 7.x: put_packet(), no allow_stop_reply flag.  QEMU 8.x: gdb_put_packet(), allow_stop_reply.
    new_api = "allow_stop_reply" in s
    put = "gdb_put_packet" if "gdb_put_packet(" in s else "put_packet"
    nostop = "        gdbserver_state.allow_stop_reply = false;\n" if new_api else ""
    stopflag = "\n        .allow_stop_reply = true" if new_api else ""
    handler = HANDLER.replace("@NOSTOP@", nostop).replace("@PUT@", put)
    table = TABLE_NEW.replace("@STOPFLAG@", stopflag)
    s = s.replace(INCLUDE_ANCHOR, INCLUDE_NEW, 1)
    s = s.replace(HANDLER_ANCHOR, handler + HANDLER_ANCHOR, 1)
    s = s.replace(TABLE_ANCHOR, table, 1)
    open(path, "w").write(s)
    print("patched %s (3 changes, %s). Now rebuild QEMU." % (path, "QEMU 8.x style" if new_api else "QEMU 7.x style"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
