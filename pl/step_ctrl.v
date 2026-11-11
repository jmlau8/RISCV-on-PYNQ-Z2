// step_ctrl.v -- FERIVer strobe counter / pause control (paper 3.1.1), PL side.
//
// Runs the PicoRV32 for a requested number of instructions and then freezes it, so the PCAP
// bridge can read its state at exactly that instruction boundary.
//
// Instruction count convention (same as the re-constructor): "n instructions completed" is the
// state in the cycle after the core's count_instr goes n -> n+1, i.e. as instruction n is decoded
// (instructions 0..n-1 retired, PC = address of instruction n). So the core is frozen when
//     count_instr == n + 1.
//
// Registers (AXI GPIO second instance, base 0x41210000):
//   req    (ch1, PS->PL)  bit31 request toggle, bits[29:0] k = instructions to run
//   status (ch2, PL->PS)  bit31 HALTED, bit30 TRAPPED, bits[29:0] n completed since reset
//
// After reset the core runs to n = 0 and halts. A request is taken only while HALTED, when
// req[31] differs from the toggle last seen; while the core is in reset the current req[31] is
// taken as the baseline, so a stale toggle never starts a run. k = 0 is ignored.
//
// core_ce is meant to drive the CE pin of a BUFGCE on the core clock (see step_gate.v): it goes
// low in the cycle after the target is reached, so the next core clock edge is suppressed.
module step_ctrl (
    input  wire        clk,         // free-running clock (also feeds the BUFGCE input)
    input  wire        resetn,
    input  wire [31:0] req,
    input  wire [63:0] count_instr, // from the core
    input  wire        trap,        // from the core
    output wire [31:0] status,
    output wire        core_ce
);
    reg        base;                // request toggle last seen
    reg [29:0] tgt;                 // freeze when count_instr[29:0] == tgt

    wire [29:0] cnt     = count_instr[29:0];
    wire        at_tgt  = (cnt == tgt) && resetn;
    wire        halted  = at_tgt || trap;
    wire        new_req = halted && !trap && (req[31] != base) && (req[29:0] != 30'd0);
    wire        eat_req = halted && (req[31] != base);   // a k=0 request is consumed and ignored

    always @(posedge clk) begin
        if (!resetn) begin
            base <= req[31];
            tgt  <= 30'd1;                                // run to n = 0
        end else if (eat_req) begin
            base <= req[31];
            if (new_req) tgt <= cnt + req[29:0];
        end
    end

    assign core_ce = !halted;
    // n = count_instr - 1 once the first instruction has been decoded, else 0
    wire [29:0] n = (cnt == 30'd0) ? 30'd0 : cnt - 30'd1;
    assign status = {halted, trap, n};
endmodule
