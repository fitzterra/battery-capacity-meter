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
`ChargeControl` module, we can effectively say the "current sensing" resistor
is 1Ω.

For the discharge monitor, we define the ``LOAD`` resistor (`LOAD_R`) in this
config file.  This will make it more difficult to change this at runtime, but
for now this should be OK.  We can revisit how to set this resistor value
dynamically later.

ADC config definitions
~~~~~~~~~~~~~~~~~~~~~~

Since there may be ADC inputs spread across multiple ADS1115_ modules, and we
want to define an ADC input to be either a normal voltage monitor, a current
monitor (see above) or a charge monitor (see above), we need a compact way to
designate these inputs.

We will do this using a string value as follows::

    "addr:chan[:R[:c]]"

where:

* ``addr`` is the ADS1115_ module's I²C address either in hex (``0x48``)
   or decimal (``73``) format. See `lib.charge_controller.ADC_ADDRS` for valid
   addresses.
* ``chan`` is the channel number to set up on this module. Only values
   from 0 - 3 are allowed and corresponds to the ``A0`` to ``A3`` ADC
   input channels on the module
* ``R`` is a resistor value in ohm if this is a current monitor
  channel. See the class documentation of the different channel types.
* ``c`` is appended to make this a charge monitor channel. See the
  class documentation of the different channel types.

.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
"""

from micropython import const
from machine import Pin, SoftI2C as I2C
from structures import (
    ADCChannel,
    ChannelMonitor,
    BatteryControllerCFG,
    VoltageMonitor,
    ChargeMonitor,
)

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
I2C_FREQ = const(4000000)
"""Default I²C Frequency to run at."""
# We also just create an I²C instance right here since it is needed all over
# the place
i2c = I2C(
    scl=Pin(PIN_SCL, pull=Pin.PULL_UP if I2C_INT_PULLUP else None),
    sda=Pin(PIN_SDA, pull=Pin.PULL_UP if I2C_INT_PULLUP else None),
    freq=I2C_FREQ,
)
"""
An I²C instance available for all, created from `PIN_SDA`, `PIN_SCL`,
`I2C_INT_PULLUP` and `I2C_FREQ` configs.
"""

# OLED
OLED_ADDR = 0x3C
"""I²C address for SSD1306 OLED"""
OLED_W = const(128)
"""OLED width in pixels"""
OLED_H = const(64)
"""OLED height in pixels"""

# Encoder pins
ENC_CLK = const(4)
ENC_DT = const(2)
ENC_SW = const(1)

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


B0 = BatteryControllerCFG(
    "BC0",
    Pin(16, Pin.OUT, value=0),  # Charge control pin
    Pin(18, Pin.OUT, value=0),  # Discharge control pin
    ChannelMonitor(
        # Charge monitor dict: adc and charge monitor
        ADCChannel(addr=0x48, chan=2),
        ChargeMonitor(res=1),
    ),
    ChannelMonitor(
        # Discharge monitor dict: adc and charge monitor
        ADCChannel(addr=0x48, chan=0),
        ChargeMonitor(res=LOAD_R),
    ),
    ChannelMonitor(
        # Battery voltage monitor dict: adc and voltage monitor
        ADCChannel(addr=0x48, chan=1),
        VoltageMonitor(),
    ),
)
"""
    Battery 0 config.

    ========= ======= ==== ==== ========
    Function  GPIO    ADC  ADC  Resistor
              Control Addr Chan
    ========= ======= ==== ==== ========
    Charge      16    0x48  2   1
    Discharge   18    0x48  0   `LOAD_R`
    Bat V       n/a   0x48  1   n/a
    ========= ======= ==== ==== ========
"""

B1 = BatteryControllerCFG(
    "BC1",
    Pin(33, Pin.OUT, value=0),  # Charge control pin
    Pin(35, Pin.OUT, value=0),  # Discharge control pin
    ChannelMonitor(
        # Charge monitor dict: adc and charge monitor
        ADCChannel(addr=0x49, chan=2),
        ChargeMonitor(res=1),
    ),
    ChannelMonitor(
        # Discharge monitor dict: adc and charge monitor
        ADCChannel(addr=0x48, chan=3),
        ChargeMonitor(res=LOAD_R),
    ),
    ChannelMonitor(
        # Battery voltage monitor dict: adc and voltage monitor
        ADCChannel(addr=0x49, chan=3),
        VoltageMonitor(),
    ),
)
"""
    Battery 1 config.

    ========= ======= ==== ==== ========
    Function  GPIO    ADC  ADC  Resistor
              Control Addr Chan
    ========= ======= ==== ==== ========
    Charge      33    0x49  2   1
    Discharge   35    0x48  3   `LOAD_R`
    Bat V       n/a   0x49  3   n/a
    ========= ======= ==== ==== ========
"""

B2 = BatteryControllerCFG(
    "BC2",
    Pin(37, Pin.OUT, value=0),  # Charge control pin
    Pin(39, Pin.OUT, value=0),  # Discharge control pin
    ChannelMonitor(
        # Charge monitor dict: adc and charge monitor
        ADCChannel(addr=0x4A, chan=0),
        ChargeMonitor(res=1),
    ),
    ChannelMonitor(
        # Discharge monitor dict: adc and charge monitor
        ADCChannel(addr=0x49, chan=1),
        ChargeMonitor(res=LOAD_R),
    ),
    ChannelMonitor(
        # Battery voltage monitor dict: adc and voltage monitor
        ADCChannel(addr=0x49, chan=0),
        VoltageMonitor(),
    ),
)
"""
    Battery 2 config.

    ========= ======= ==== ==== ========
    Function  GPIO    ADC  ADC  Resistor
              Control Addr Chan
    ========= ======= ==== ==== ========
    Charge      37    0x4A  0   1
    Discharge   39    0x49  1   `LOAD_R`
    Bat V       n/a   0x49  0   n/a
    ========= ======= ==== ==== ========
"""

B3 = BatteryControllerCFG(
    "BC3",
    Pin(40, Pin.OUT, value=0),  # Charge control pin
    Pin(38, Pin.OUT, value=0),  # Discharge control pin
    ChannelMonitor(
        # Charge monitor dict: adc and charge monitor
        ADCChannel(addr=0x4A, chan=3),
        ChargeMonitor(res=1),
    ),
    ChannelMonitor(
        # Discharge monitor dict: adc and charge monitor
        ADCChannel(addr=0x4A, chan=1),
        ChargeMonitor(res=LOAD_R),
    ),
    ChannelMonitor(
        # Battery voltage monitor dict: adc and voltage monitor
        ADCChannel(addr=0x4A, chan=2),
        VoltageMonitor(),
    ),
)
"""
    Battery 3 config.

    ========= ======= ==== ==== ========
    Function  GPIO    ADC  ADC  Resistor
              Control Addr Chan
    ========= ======= ==== ==== ========
    Charge      40    0x4A  3   1
    Discharge   38    0x4A  2   `LOAD_R`
    Bat V       n/a   0x4A  1   n/a
    ========= ======= ==== ==== ========
"""
