"""
Module that contains only I²C config details.

Multiple modules may need access to I²C things, and to prevent cross imports,
we split this out into it's own module.

Attributes:
    PIN_SDA: I²C SDA pin used on S2 Mini for Host

    PIN_SCL: I²C SCL pin used on S2 Mini for Host

    I2C_INT_PULLUP: Whether to use internal pullups for I²C or not. Default is
        enable pullups

    I2C_FREQ: Default I²C Frequency to run at.

    i2c: An I²C instance available for all, created from `PIN_SDA`, `PIN_SCL`,
        `I2C_INT_PULLUP` and `I2C_FREQ` configs.

    ADC_ADDRS: These are all possible I²C addresses for all available ADS1115
        modules in this circuit.

    AVAILABLE_ADCS: This will be a list of ADS1115 modules available on the I²C
        bus.

        This list is obtained by scanning the I²C bus and matching any
        addresses found to the list of available addresses in `ADC_ADDRS`.

        This can be used to disable any battery controller for which the actaul
        ADS1115 module may not be available currently.
"""

from micropython import const
from machine import Pin, SoftI2C as I2C

# I²C pins used on the host board. See docstring Attributes for more.
PIN_SDA = const(36)
PIN_SCL = const(34)
I2C_INT_PULLUP = True
I2C_FREQ = const(4000000)
# We also just create an I²C instance right here since it is needed all over
# the place
i2c = I2C(
    scl=Pin(PIN_SCL, pull=Pin.PULL_UP if I2C_INT_PULLUP else None),
    sda=Pin(PIN_SDA, pull=Pin.PULL_UP if I2C_INT_PULLUP else None),
    freq=I2C_FREQ,
)

# See docstring Attributes for more.
ADC_ADDRS: list = [
    0x48,  # ADDR connected to Ground - default via 10k pulldown
    0x49,  # ADDR connected to VDD
    0x4A,  # ADDR connected to SDA
    0x4B,  # ADDR connected to SCL
]

# We want to see get a list of the actually available ADS1115 modules that are
# on the I²C buss currently
AVAILABLE_ADCS = [addr for addr in i2c.scan() if addr in ADC_ADDRS]
