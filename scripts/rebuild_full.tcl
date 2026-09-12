# Full from-scratch rebuild: creates a fresh Vivado project, sources the
# fixed scripts/pico_bit.tcl to build design_1's block design, then runs
# synth_1 -> impl_1 -> write_bitstream and copies out the .bit/.hwh.
#
# This is the correct way to (re)build this project now. It exists because
# pico_bit.tcl was changed to instantiate pico_processor_0 as a plain
# hierarchy (`create_bd_cell -type hier`) instead of a Block Design
# Container reference to a separate pico_processor.bd -- the container
# form produced a .hwh MODULE entry with no VLNV and no flattened internal
# IP, which PYNQ's hwh_parser couldn't resolve into a RISC-V processor
# hierarchy. Any Vivado project built against the old container-based
# script (or partially migrated from one) carries leftover artifacts --
# a stray pico_processor.bd source and an orphaned "pico_processor_inst_0"
# BlockSrcs fileset with no TopModule property -- that reliably crash
# Vivado with "Application Exception: SrcMgr::createSS : name not set"
# partway through generate_target/synthesis. Reusing such a project is not
# safe; always build fresh (this script does, via create_project) rather
# than opening an existing myproj/.
#
# Also works around two environment quirks hit on this machine:
#   - generate_target already writes hdl/design_1_wrapper.v as a side
#     effect, so make_wrapper is only called if that file doesn't exist yet
#     (calling it when the file is already present crashes Vivado the same
#     way as the stale-fileset issue above).
#   - the PYNQ-Z2 board_part files aren't installed for this Vivado, so
#     setting BOARD_PART is wrapped in a catch and treated as non-fatal --
#     the design configures processing_system7 with explicit PCW_*
#     properties rather than relying on a board preset.

set root "C:/Users/jalen/RISCV-on-PYNQ-Z2-fresh"

create_project project_1 "$root/myproj" -part xc7z020clg400-1
# Board files for PYNQ-Z2 aren't installed in this Vivado setup; not
# fatal -- the design configures processing_system7 with explicit PCW_*
# properties rather than relying on a board preset.
if { [catch { set_property BOARD_PART tul.com.tw:pynq-z2:part0:1.0 [current_project] } errMsg] } {
    puts "WARNING: could not set BOARD_PART ($errMsg); continuing with part-only project."
}
set_property ip_repo_paths "$root/ip" [current_project]
update_ip_catalog

source "$root/scripts/pico_bit.tcl"

set bd_file [get_files -all "*design_1.bd"]
puts "Using BD file: $bd_file"

validate_bd_design
generate_target all $bd_file

set wrapper_path [file join [file dirname $bd_file] hdl design_1_wrapper.v]
if { ![file exists $wrapper_path] } {
    make_wrapper -files $bd_file -top
}
if { [get_files -quiet $wrapper_path] eq "" } {
    add_files -norecurse $wrapper_path
}
update_compile_order -fileset sources_1
set_property top design_1_wrapper [current_fileset]
update_compile_order -fileset sources_1

set constr_path "$root/constrs/PYNQ-Z2.xdc"
set existing_constr [get_files -quiet -of_objects [get_filesets constrs_1] "*PYNQ-Z2.xdc"]
if { $existing_constr eq "" } {
    add_files -fileset constrs_1 -norecurse $constr_path
}
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs 4
wait_on_run synth_1

set synth_status [get_property STATUS [get_runs synth_1]]
set synth_progress [get_property PROGRESS [get_runs synth_1]]
puts "SYNTH_STATUS=$synth_status SYNTH_PROGRESS=$synth_progress"
if { $synth_progress ne "100%" } {
    puts "REBUILD_RESULT=SYNTH_FAILED"
    exit 1
}

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
set impl_progress [get_property PROGRESS [get_runs impl_1]]
puts "IMPL_STATUS=$impl_status IMPL_PROGRESS=$impl_progress"
if { $impl_progress ne "100%" } {
    puts "REBUILD_RESULT=IMPL_FAILED"
    exit 1
}

set bit_src "$root/myproj/project_1.runs/impl_1/design_1_wrapper.bit"
set bit_dst "$root/build_output/design_1_wrapper.bit"
file mkdir "$root/build_output"
file copy -force $bit_src $bit_dst
puts "BITSTREAM_COPIED_TO=$bit_dst"

set hwh_path "$root/myproj/project_1.gen/sources_1/bd/design_1/hw_handoff/design_1.hwh"
puts "HWH_PATH=$hwh_path"
puts "HWH_EXISTS=[file exists $hwh_path]"

puts "REBUILD_RESULT=SUCCESS"
