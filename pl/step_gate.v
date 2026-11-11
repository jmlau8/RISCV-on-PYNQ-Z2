// step_gate.v -- gated core clock. On the board this is a BUFGCE (CE low suppresses the next
// edge). The behavioral model below is the standard glitch-free latch + AND and is only used
// in simulation.
module step_gate (input wire clk, input wire ce, output wire gclk);
`ifdef SYNTHESIS
    BUFGCE u_bufgce (.I(clk), .CE(ce), .O(gclk));
`else
    reg ce_l = 1'b1;
    always @(clk or ce) if (!clk) ce_l = ce;
    assign gclk = clk & ce_l;
`endif
endmodule
