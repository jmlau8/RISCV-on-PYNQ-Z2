// capture_snapshot.v
// Wraps CAPTUREE2 with input synchronization + edge detection so a
// multi-cycle PS-driven GPIO pulse produces exactly one CAP pulse.
// Also exposes a toggle-flop debug output (cap_toggle_dbg) so the
// capture event is visible on an LED -- a single-cycle pulse would
// blink too fast to see.
`timescale 1ns / 1ps

module capture_snapshot (
    input  wire clk,
    input  wire cap_trigger,
    output reg  cap_toggle_dbg = 1'b0   // toggles each capture event; tap to an LED
);

    reg cap_trigger_sync0 = 1'b0;
    reg cap_trigger_sync1 = 1'b0;
    reg cap_trigger_prev  = 1'b0;

    always @(posedge clk) begin
        cap_trigger_sync0 <= cap_trigger;
        cap_trigger_sync1 <= cap_trigger_sync0;
        cap_trigger_prev  <= cap_trigger_sync1;
    end

    wire cap_pulse = cap_trigger_sync1 & ~cap_trigger_prev;

    // Visible debug: flip a bit every time a capture fires.
    always @(posedge clk) begin
        if (cap_pulse)
            cap_toggle_dbg <= ~cap_toggle_dbg;
    end

    CAPTUREE2 #(
        .ONESHOT("FALSE")
    ) captureee2_inst (
        .CAP (cap_pulse),
        .CLK (clk)
    );

endmodule