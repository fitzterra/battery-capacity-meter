"""
Project configuration file.

ADC inputs per battery controller.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These constants sets the ADCTracker tracer input config for the various
monitors.

In order to monitor the charge current on the TP4056 module, we monitor the
voltage on the PROG pin as per the datasheet. The charge current at this
point can then be calculated using the formula::

          Vprog
    Ich = ----- x 1200
          Rprog

where ``Rprog`` is value of the current programming resistor on the board. For
a 1000mA charge current a 1200Ω resistor should be used for ``Rprog``. Since
these boards normally have a 1200Ω resistor installed, they are set to charge
at 1000mA.  
From the formula above, the 1200 multiplier cancels the 1200Ω resistor
divisor, leaving the charge current (``Ich``) equal to the voltage measured on
the pin (``Vprog``).

To use the ``PROG`` pin of the TP4056 as charge monitor input for the
`ADCTracker` module, we can effectively say the "current sensing" resistor is
1Ω.

For the discharge monitor, we define the ``LOAD`` resistor (`LOAD_R`) in this
config file.  This will make it more difficult to change this at runtime, but
for now this should be OK.  We can revisit how to set this resistor value
dynamically later.  """

from micropython import const

# Pins used on the S2 Mini
PIN_LED = 15
"""Onboard LED pin. Default for S2 Mini"""

# I²C pins used on the host board
PIN_SDA = const(36)
"""I²C SDA pin used on S2 Mini for Host"""
PIN_SCL = const(34)
"""I²C SCL pin used on S2 Mini for Host"""
I2C_INT_PULLUP = True
"""Whether to use internal pullups for I²C or not. Default is enable pullups"""
I2C_FREQ = 4000000
"""Default I²C Frequency to run at."""

# Battery 0 control pins
B0_CH_CTL = const(16)
"""Battery 0 charge control pin"""
B0_DCH_CTL = const(18)
"""Battery 0 discharge control pin"""

# Battery 1 control pins
B1_CH_CTL = const(33)
"""Battery 1 charge control pin"""
B1_DCH_CTL = const(35)
"""Battery 1 discharge control pin"""

# Battery 2 control pins
B2_CH_CTL = const(37)
"""Battery 2 charge control pin"""
B2_DCH_CTL = const(39)
"""Battery 2 discharge control pin"""

# Battery 3 control pins
B3_CH_CTL = const(40)
"""Battery 3 charge control pin"""
B3_DCH_CTL = const(38)
"""Battery 3 discharge control pin"""

### ADC inputs per battery controller.
# These constants sets the ADCTracker tracer input config for the various
# monitors.
#
# In order to monitor the charge current on the TP4056 module, we monitor the
# voltage on the PROG pin as per the datasheet. The charge current at this
# point can then be calculated using the formula:
#
#        Vprog
#  Ich = ----- x 1200
#        Rprog
#
# where Rprog is value of the current programming resistor on the board. For a
# 1000mA charge current a 1200Ω resister should be used for Rprog. Since these
# boards normally have a 1200Ω resistor installed, they are set to charge at
# 1000mA.
# From the formula above, the 1200 multiplier cancels the 1200Ω resistor
# divisor, leaving the charge current (Ich) equal to the voltage measured on
# the pin (Vprog).
#
# To use the PROG pin of the TP4056 as charge monitor input for the ADCTracker
# module, we can effectively say the "current sensing" resistor is 1Ω.
#
# For the discharge monitor, we define the LOAD resistor here. This will make
# it more difficult to change this at runtime, but for now this should be OK.
# We can revisit how to set this resistor value dynamically later.
LOAD_R = 5  # 5Ω load resistor
"""Load resistance value in Ohm. Default is 5Ω"""
# Battery 0
B0_CH_C = "0x48:2:1:c"  # TP4056 charge current monitor - see above
B0_DCH_C = f"0x48:0:{LOAD_R}:c"  # Discharge  monitor
B0_OB_V = "0x48:1"  # Output and battery voltage monitor
# Battery 1
B1_CH_C = "0x49:2:1:c"  # TP4056 charge current monitor - see above
B1_DCH_C = f"0x48:3:{LOAD_R}:c"  # Discharge  monitor
B1_OB_V = "0x49:3"  # Output and battery voltage monitor
# Battery 2
B2_CH_C = "0x4A:0:1:c"  # TP4056 charge current monitor - see above
B2_DCH_C = f"0x49:1:{LOAD_R}:c"  # Discharge  monitor
B2_OB_V = "0x49:0"  # Output and battery voltage monitor
# Battery 3
B3_CH_C = "0x4A:3:1:c"  # TP4056 charge current monitor - see above
B3_DCH_C = f"0x4A:1:{LOAD_R}:c"  # Discharge  monitor
B3_OB_V = "0x4A:2"  # Output and battery voltage monitor

# OLED
OLED_ADDR = 0x3C
"""I²C address for SSD1306 OLED"""
OLED_W = 128
"""OLED width in pixels"""
OLED_H = 64
"""OLED height in pixels"""
