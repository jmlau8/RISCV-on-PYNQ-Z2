# ----------------------------------------------------------------------
# Copyright (c) 2018, The Regents of the University of California All
# rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#
#     * Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#
#     * Neither the name of The Regents of the University of California
#       nor the names of its contributors may be used to endorse or
#       promote products derived from this software without specific
#       prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL REGENTS OF THE
# UNIVERSITY OF CALIFORNIA BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
# TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.
# ----------------------------------------------------------------------
from riscvonpynq.Overlay import Overlay
from riscvonpynq.Processor import BramProcessor
import os, inspect

class Overlay(Overlay):
    """Overlay driver for the PicoRV32 bram Overlay

    Note
    ----
    This class definition must be co-located with the .tcl and .bit
    file for the overlay for the search path modifications in
    riscvonpynq.Overlay to work. __init__ in riscvonpynq.Overlay uses
    the path of this file to search for the .bit file using the
    inspect package.

    """
    pass

class Processor(BramProcessor):
    """Hierarchy driver for the PicoRV32 BRAM Processor

    Note
    ----
    In order to be recognized as a RISC-V Processor hierarchy, three
    conditions must be met: First, there must be a PS-Memory-Mapped
    Block RAM Controller where the name matches the variable
    _bram. Second, the hierarchy name (fullpath) must equal the
    variable _name. Finally, there must be a GPIO port with the name
    _reset_name.

    _name is 'pico_processor_0' here (not upstream's 'picoBramProcessor')
    because this design's pico_processor hierarchy is instantiated under
    that name in scripts/pico_bit.tcl -- see
    `create_bd_cell -type hier $nameHier` in
    create_hier_cell_pico_processor_0 (called with nameHier=pico_processor_0).

    Subclasses of this module are responsible for setting _name (The
    name of the Hierarchy), _bits (Processor bit-width), _proc
    (Processor Type Name)

    This class must be placed in a known location relative to the
    build files for this processor. The relative path can be modified
    in __get_path.

    """
    _name = 'pico_processor_0'
    _proc = 'picorv32'
    _bits = 32

    # riscv_resetn/irq are hierarchy boundary pins that dissolve during
    # Vivado's BD-to-netlist flattening (see scripts/pico_bit.tcl's
    # create_hier_cell_pico_processor_0 -- they're pure pass-throughs, no
    # logic). In the exported .hwh they show up wired directly to leaf IP
    # (riscvReset.aux_reset_in and picorv32.trap), and since neither
    # riscvReset nor picorv32 is independently PS-addressable, PYNQ's
    # hwh_parser never attributes them to this hierarchy's
    # description['gpio']/['interrupts'] (see Processor.checkhierarchy's
    # docstring). They ARE real signals, just visible only at the top level
    # -- as PL.gpio_dict['resetSlice'] and
    # PL.interrupt_pins['pico_processor_0/picorv32/trap']. These two names
    # let Processor fall back to that top-level lookup instead.
    _reset_gpio_name = 'resetSlice'
    _irq_pin_fullpath = 'pico_processor_0/picorv32/trap'

    @classmethod
    def checkhierarchy(cls, description):
        return super().checkhierarchy(description)

    def __get_path(self):
        """Get the directory path of this file, or the directory path of the
        class that inherits from this class.

        """
        # Get file path of the current class (i.e. /opt/python3.6/<...>/stream.py)
        file_path = os.path.abspath(inspect.getfile(inspect.getmodule(self)))
        # Get directory path of the current class (i.e. /opt/python3.6/<...>/stream/)
        return os.path.dirname(file_path)

    def __init__(self, description, *args):
        """Return a new Processor object.

        Parameters
        ----------
        description : dict
            Dictionary describing this processor.

        """
        build_path = os.path.join(self.__get_path(), "build")
        reset_value = 0
        super().__init__(build_path, reset_value, description, *args)
