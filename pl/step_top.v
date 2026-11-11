// step_top.v -- simulation harness: PicoRV32 (board configuration) + step_ctrl + gated clock.
// Memory is clocked by the gated clock too, i.e. it freezes together with the core (on the
// board the AXI adapter lives in the same gated domain and AXI slaves hold their responses).
`timescale 1ns / 1ps
module step_top (
    input  wire        clk,
    input  wire        resetn,
    input  wire [31:0] req,
    output wire [31:0] status
);
    wire        trap, mem_valid, mem_instr;
    reg         mem_ready;
    wire [31:0] mem_addr, mem_wdata;
    wire [ 3:0] mem_wstrb;
    reg  [31:0] mem_rdata;
    wire        gclk, core_ce;

    reg [31:0] mem [0:16383];
    integer k;
    initial for (k = 0; k < 16384; k = k + 1) mem[k] = 32'h0;

    picorv32 #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(1), .ENABLE_REGS_16_31(1), .ENABLE_REGS_DUALPORT(1),
        .TWO_STAGE_SHIFT(1), .BARREL_SHIFTER(0), .TWO_CYCLE_COMPARE(0), .TWO_CYCLE_ALU(0),
        .COMPRESSED_ISA(0), .CATCH_MISALIGN(1), .CATCH_ILLINSN(1), .ENABLE_PCPI(0),
        .ENABLE_MUL(0), .ENABLE_FAST_MUL(0), .ENABLE_DIV(0), .ENABLE_IRQ(0),
        .ENABLE_IRQ_QREGS(1), .ENABLE_IRQ_TIMER(1), .ENABLE_TRACE(0), .REGS_INIT_ZERO(1),
        .MASKED_IRQ(32'h0), .LATCHED_IRQ(32'hFFFFFFFF), .PROGADDR_RESET(32'h0),
        .PROGADDR_IRQ(32'h10), .STACKADDR(32'hFFFFFFFF)
    ) core (
        .clk(gclk), .resetn(resetn), .trap(trap),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb), .mem_rdata(mem_rdata),
        .pcpi_wr(1'b0), .pcpi_rd(32'h0), .pcpi_wait(1'b0), .pcpi_ready(1'b0), .irq(32'h0)
    );

    step_ctrl ctrl (.clk(clk), .resetn(resetn), .req(req), .count_instr(core.count_instr),
                    .trap(trap), .status(status), .core_ce(core_ce));
    step_gate gate (.clk(clk), .ce(core_ce), .gclk(gclk));

    wire [13:0] widx = mem_addr[15:2];
    always @(posedge gclk) begin
        mem_ready <= 1'b0;
        if (resetn && mem_valid && !mem_ready) begin
            mem_ready <= 1'b1;
            if (mem_wstrb == 4'b0) mem_rdata <= mem[widx];
            else begin
                if (mem_wstrb[0]) mem[widx][ 7: 0] <= mem_wdata[ 7: 0];
                if (mem_wstrb[1]) mem[widx][15: 8] <= mem_wdata[15: 8];
                if (mem_wstrb[2]) mem[widx][23:16] <= mem_wdata[23:16];
                if (mem_wstrb[3]) mem[widx][31:24] <= mem_wdata[31:24];
            end
        end
    end

    wire [31:0] pc = core.reg_pc;
    wire [31:0] x0 = 32'h0;
    wire [31:0] x1 = core.cpuregs[1];
    wire [31:0] x2 = core.cpuregs[2];
    wire [31:0] x3 = core.cpuregs[3];
    wire [31:0] x4 = core.cpuregs[4];
    wire [31:0] x5 = core.cpuregs[5];
    wire [31:0] x6 = core.cpuregs[6];
    wire [31:0] x7 = core.cpuregs[7];
    wire [31:0] x8 = core.cpuregs[8];
    wire [31:0] x9 = core.cpuregs[9];
    wire [31:0] x10 = core.cpuregs[10];
    wire [31:0] x11 = core.cpuregs[11];
    wire [31:0] x12 = core.cpuregs[12];
    wire [31:0] x13 = core.cpuregs[13];
    wire [31:0] x14 = core.cpuregs[14];
    wire [31:0] x15 = core.cpuregs[15];
    wire [31:0] x16 = core.cpuregs[16];
    wire [31:0] x17 = core.cpuregs[17];
    wire [31:0] x18 = core.cpuregs[18];
    wire [31:0] x19 = core.cpuregs[19];
    wire [31:0] x20 = core.cpuregs[20];
    wire [31:0] x21 = core.cpuregs[21];
    wire [31:0] x22 = core.cpuregs[22];
    wire [31:0] x23 = core.cpuregs[23];
    wire [31:0] x24 = core.cpuregs[24];
    wire [31:0] x25 = core.cpuregs[25];
    wire [31:0] x26 = core.cpuregs[26];
    wire [31:0] x27 = core.cpuregs[27];
    wire [31:0] x28 = core.cpuregs[28];
    wire [31:0] x29 = core.cpuregs[29];
    wire [31:0] x30 = core.cpuregs[30];
    wire [31:0] x31 = core.cpuregs[31];
endmodule
