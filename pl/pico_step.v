// pico_step.v -- PicoRV32 + AXI4-Lite adapter + strobe counter / pause control, for the block design.
//
// Replaces the picorv32_axi IP cell. Same core configuration as the IP (component.xml defaults),
// but with count_instr visible to step_ctrl. Two clocks:
//   clk   free-running 50 MHz clock: step_ctrl, and the CE input of the clock gate
//   gclk  gated version of clk (util_ds_buf BUFGCE, CE = core_ce): the core, the AXI adapter,
//         and the BRAM controller it talks to must all run on gclk so that a frozen core never
//         misses an AXI handshake.
// Mailbox: req = AXI GPIO channel 1 output, status = AXI GPIO channel 2 input (see step_ctrl.v).
`timescale 1ns / 1ps
module pico_step #(
    parameter REGS_INIT_ZERO = 0   // board IP uses 0; simulation sets 1 so unwritten registers are 0, not X
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 50000000" *)
    input  wire        clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 gclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF mem_axi, ASSOCIATED_RESET resetn, FREQ_HZ 50000000" *)
    input  wire        gclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 resetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire        resetn,
    output wire        core_ce,
    output wire        trap,
    input  wire [31:0] req,
    output wire [31:0] status,

    (* X_INTERFACE_MODE = "master mem_axi" *)
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi AWVALID" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME mem_axi, PROTOCOL AXI4LITE, FREQ_HZ 50000000, ADDR_WIDTH 32, DATA_WIDTH 32" *)
    output wire        mem_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi AWREADY" *) input  wire        mem_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi AWADDR"  *) output wire [31:0] mem_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi AWPROT"  *) output wire [ 2:0] mem_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi WVALID"  *) output wire        mem_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi WREADY"  *) input  wire        mem_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi WDATA"   *) output wire [31:0] mem_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi WSTRB"   *) output wire [ 3:0] mem_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi BVALID"  *) input  wire        mem_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi BREADY"  *) output wire        mem_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi ARVALID" *) output wire        mem_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi ARREADY" *) input  wire        mem_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi ARADDR"  *) output wire [31:0] mem_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi ARPROT"  *) output wire [ 2:0] mem_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi RVALID"  *) input  wire        mem_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi RREADY"  *) output wire        mem_axi_rready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 mem_axi RDATA"   *) input  wire [31:0] mem_axi_rdata
);
    wire        mem_valid, mem_instr, mem_ready;
    wire [31:0] mem_addr, mem_wdata, mem_rdata, count_instr;
    wire [ 3:0] mem_wstrb;

    ps_picorv32 #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(1), .ENABLE_REGS_16_31(1), .ENABLE_REGS_DUALPORT(1),
        .TWO_STAGE_SHIFT(1), .BARREL_SHIFTER(0), .TWO_CYCLE_COMPARE(0), .TWO_CYCLE_ALU(0),
        .COMPRESSED_ISA(0), .CATCH_MISALIGN(1), .CATCH_ILLINSN(1), .ENABLE_PCPI(0),
        .ENABLE_MUL(0), .ENABLE_FAST_MUL(0), .ENABLE_DIV(0), .ENABLE_IRQ(0),
        .ENABLE_IRQ_QREGS(1), .ENABLE_IRQ_TIMER(1), .ENABLE_TRACE(0), .REGS_INIT_ZERO(REGS_INIT_ZERO),
        .MASKED_IRQ(32'h0), .LATCHED_IRQ(32'hFFFFFFFF), .PROGADDR_RESET(32'h0),
        .PROGADDR_IRQ(32'h10), .STACKADDR(32'hFFFFFFFF)
    ) core (
        .clk(gclk), .resetn(resetn), .trap(trap),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb), .mem_rdata(mem_rdata),
        .pcpi_wr(1'b0), .pcpi_rd(32'h0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
        .irq(32'h0), .count_instr_o(count_instr)
    );

    ps_picorv32_axi_adapter adapter (
        .clk(gclk), .resetn(resetn),
        .mem_axi_awvalid(mem_axi_awvalid), .mem_axi_awready(mem_axi_awready),
        .mem_axi_awaddr(mem_axi_awaddr), .mem_axi_awprot(mem_axi_awprot),
        .mem_axi_wvalid(mem_axi_wvalid), .mem_axi_wready(mem_axi_wready),
        .mem_axi_wdata(mem_axi_wdata), .mem_axi_wstrb(mem_axi_wstrb),
        .mem_axi_bvalid(mem_axi_bvalid), .mem_axi_bready(mem_axi_bready),
        .mem_axi_arvalid(mem_axi_arvalid), .mem_axi_arready(mem_axi_arready),
        .mem_axi_araddr(mem_axi_araddr), .mem_axi_arprot(mem_axi_arprot),
        .mem_axi_rvalid(mem_axi_rvalid), .mem_axi_rready(mem_axi_rready),
        .mem_axi_rdata(mem_axi_rdata),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb), .mem_rdata(mem_rdata)
    );

    step_ctrl ctrl (.clk(clk), .resetn(resetn), .req(req), .count_instr({32'h0, count_instr}),
                    .trap(trap), .status(status), .core_ce(core_ce));
endmodule
