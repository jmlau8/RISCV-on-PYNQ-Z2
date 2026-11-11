// step_axi_top.v -- simulation of the board arrangement: pico_step + BUFGCE model + an AXI4-Lite
// memory slave on the gated clock (like the riscvBramController on gclk). Same signal names as
// step_top.v so test_step_cocotb.py runs unchanged.
`timescale 1ns / 1ps
module step_axi_top (
    input  wire        clk,
    input  wire        resetn,
    input  wire [31:0] req,
    output wire [31:0] status
);
    wire gclk, core_ce, trap;
    wire        awvalid, wvalid, bready, arvalid, rready;
    reg         awready, wready, bvalid, arready, rvalid;
    wire [31:0] awaddr, wdata, araddr;
    wire [ 3:0] wstrb;
    reg  [31:0] rdata;

    reg [31:0] mem [0:16383];
    integer k;
    initial for (k = 0; k < 16384; k = k + 1) mem[k] = 32'h0;

    step_gate gate (.clk(clk), .ce(core_ce), .gclk(gclk));
    pico_step #(.REGS_INIT_ZERO(1)) dut (
        .clk(clk), .gclk(gclk), .resetn(resetn), .core_ce(core_ce), .trap(trap),
        .req(req), .status(status),
        .mem_axi_awvalid(awvalid), .mem_axi_awready(awready), .mem_axi_awaddr(awaddr), .mem_axi_awprot(),
        .mem_axi_wvalid(wvalid), .mem_axi_wready(wready), .mem_axi_wdata(wdata), .mem_axi_wstrb(wstrb),
        .mem_axi_bvalid(bvalid), .mem_axi_bready(bready),
        .mem_axi_arvalid(arvalid), .mem_axi_arready(arready), .mem_axi_araddr(araddr), .mem_axi_arprot(),
        .mem_axi_rvalid(rvalid), .mem_axi_rready(rready), .mem_axi_rdata(rdata)
    );

    // simple AXI4-Lite slave: holds bvalid/rvalid until the master takes it
    wire [13:0] widx = awaddr[15:2];
    wire [13:0] ridx = araddr[15:2];
    always @(posedge gclk) begin
        awready <= 1'b0; wready <= 1'b0; arready <= 1'b0;
        if (!resetn) begin
            bvalid <= 1'b0; rvalid <= 1'b0;
        end else begin
            if (bvalid && bready) bvalid <= 1'b0;
            if (rvalid && rready) rvalid <= 1'b0;
            if (awvalid && wvalid && !awready && !bvalid) begin
                awready <= 1'b1; wready <= 1'b1; bvalid <= 1'b1;
                if (wstrb[0]) mem[widx][ 7: 0] <= wdata[ 7: 0];
                if (wstrb[1]) mem[widx][15: 8] <= wdata[15: 8];
                if (wstrb[2]) mem[widx][23:16] <= wdata[23:16];
                if (wstrb[3]) mem[widx][31:24] <= wdata[31:24];
            end
            if (arvalid && !arready && !rvalid) begin
                arready <= 1'b1; rvalid <= 1'b1; rdata <= mem[ridx];
            end
        end
    end

    wire [31:0] pc = dut.core.reg_pc;
    wire [31:0] x0 = 32'h0;
    wire [31:0] x1 = dut.core.cpuregs[1];
    wire [31:0] x2 = dut.core.cpuregs[2];
    wire [31:0] x3 = dut.core.cpuregs[3];
    wire [31:0] x4 = dut.core.cpuregs[4];
    wire [31:0] x5 = dut.core.cpuregs[5];
    wire [31:0] x6 = dut.core.cpuregs[6];
    wire [31:0] x7 = dut.core.cpuregs[7];
    wire [31:0] x8 = dut.core.cpuregs[8];
    wire [31:0] x9 = dut.core.cpuregs[9];
    wire [31:0] x10 = dut.core.cpuregs[10];
    wire [31:0] x11 = dut.core.cpuregs[11];
    wire [31:0] x12 = dut.core.cpuregs[12];
    wire [31:0] x13 = dut.core.cpuregs[13];
    wire [31:0] x14 = dut.core.cpuregs[14];
    wire [31:0] x15 = dut.core.cpuregs[15];
    wire [31:0] x16 = dut.core.cpuregs[16];
    wire [31:0] x17 = dut.core.cpuregs[17];
    wire [31:0] x18 = dut.core.cpuregs[18];
    wire [31:0] x19 = dut.core.cpuregs[19];
    wire [31:0] x20 = dut.core.cpuregs[20];
    wire [31:0] x21 = dut.core.cpuregs[21];
    wire [31:0] x22 = dut.core.cpuregs[22];
    wire [31:0] x23 = dut.core.cpuregs[23];
    wire [31:0] x24 = dut.core.cpuregs[24];
    wire [31:0] x25 = dut.core.cpuregs[25];
    wire [31:0] x26 = dut.core.cpuregs[26];
    wire [31:0] x27 = dut.core.cpuregs[27];
    wire [31:0] x28 = dut.core.cpuregs[28];
    wire [31:0] x29 = dut.core.cpuregs[29];
    wire [31:0] x30 = dut.core.cpuregs[30];
    wire [31:0] x31 = dut.core.cpuregs[31];
endmodule
