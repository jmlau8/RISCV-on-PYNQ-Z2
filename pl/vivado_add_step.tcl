# vivado_add_step.tcl -- adds the FERIVer strobe counter / pause control to design_1 (Vivado 2022.2).
# Run the phases IN ORDER in the Vivado Tcl console (or `source` this file after phase 0).
# Phase 0 (manual): copy pico_step.v, ps_picorv32.v, step_ctrl.v into the folder that holds capture_snapshot.v.

# ---------------- PHASE 1: add sources ----------------
set hdl_dir [file dirname [get_files capture_snapshot.v]]
puts "HDL dir: $hdl_dir"
foreach f {pico_step.v ps_picorv32.v step_ctrl.v} {
    if {![file exists $hdl_dir/$f]} { error "MISSING $hdl_dir/$f -- copy it there first" }
}
add_files -norecurse [list $hdl_dir/pico_step.v $hdl_dir/ps_picorv32.v $hdl_dir/step_ctrl.v]
update_compile_order -fileset sources_1
open_bd_design [get_files design_1.bd]

# ---------------- PHASE 2: swap the PicoRV32 IP for pico_step + clock gate ----------------
set H pico_processor_0
create_bd_cell -type module -reference pico_step $H/step
create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf:2.2 $H/clkgate
set_property -dict [list CONFIG.C_BUF_TYPE {BUFGCE}] [get_bd_cells $H/clkgate]
puts "clkgate pins: [get_bd_pins $H/clkgate/*]"
puts "step pins:    [get_bd_pins $H/step/*]"
puts "step intf:    [get_bd_intf_pins $H/step/*]"

# remove the old IP (its connections go with it) and the old core clock net
delete_bd_objs [get_bd_cells $H/picorv32]
delete_bd_objs [get_bd_nets -of_objects [get_bd_pins $H/riscvBramController/s_axi_aclk]]

# clocks: free clock -> reset block, step_ctrl, clock gate input; gated clock -> core + BRAM controller
connect_bd_net [get_bd_pins $H/riscv_clk] [get_bd_pins $H/riscvReset/slowest_sync_clk] [get_bd_pins $H/step/clk] [get_bd_pins $H/clkgate/BUFGCE_I]
connect_bd_net [get_bd_pins $H/step/core_ce] [get_bd_pins $H/clkgate/BUFGCE_CE]
connect_bd_net [get_bd_pins $H/clkgate/BUFGCE_O] [get_bd_pins $H/step/gclk] [get_bd_pins $H/riscvBramController/s_axi_aclk]
# reset, trap, AXI
connect_bd_net [get_bd_pins $H/riscvReset/peripheral_aresetn] [get_bd_pins $H/step/resetn]
connect_bd_net [get_bd_pins $H/step/trap] [get_bd_pins $H/irq]
connect_bd_intf_net [get_bd_intf_pins $H/step/mem_axi] [get_bd_intf_pins $H/riscvBramController/S_AXI]
# mailbox pins on the hierarchy
create_bd_pin -dir I -from 31 -to 0 $H/step_req
create_bd_pin -dir O -from 31 -to 0 $H/step_status
connect_bd_net [get_bd_pins $H/step_req] [get_bd_pins $H/step/req]
connect_bd_net [get_bd_pins $H/step/status] [get_bd_pins $H/step_status]

# ---------------- PHASE 3: mailbox GPIO at 0x41210000 ----------------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_1
set_property -dict [list CONFIG.C_IS_DUAL {1} CONFIG.C_GPIO_WIDTH {32} CONFIG.C_ALL_OUTPUTS {1} \
                         CONFIG.C_GPIO2_WIDTH {32} CONFIG.C_ALL_INPUTS_2 {1}] [get_bd_cells axi_gpio_1]
set_property CONFIG.NUM_MI {5} [get_bd_cells psAxiInterconnect]
connect_bd_intf_net [get_bd_intf_pins psAxiInterconnect/M04_AXI] [get_bd_intf_pins axi_gpio_1/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins psAxiInterconnect/M04_ACLK] [get_bd_pins axi_gpio_1/s_axi_aclk]
connect_bd_net [get_bd_pins porReset/peripheral_aresetn] [get_bd_pins psAxiInterconnect/M04_ARESETN] [get_bd_pins axi_gpio_1/s_axi_aresetn]
connect_bd_net [get_bd_pins axi_gpio_1/gpio_io_o] [get_bd_pins $H/step_req]
connect_bd_net [get_bd_pins $H/step_status] [get_bd_pins axi_gpio_1/gpio2_io_i]
assign_bd_address -offset 0x41210000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_1/S_AXI/Reg] -force
assign_bd_address -offset 0xC0000000 -range 0x00010000 -target_address_space [get_bd_addr_spaces $H/step/mem_axi] [get_bd_addr_segs $H/riscvBramController/S_AXI/Mem0] -force
validate_bd_design
save_bd_design
