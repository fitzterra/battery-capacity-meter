"""
Main application entry point.
"""

from machine import Pin, SoftI2C as I2C
import uasyncio as asyncio
from config import PIN_SDA, PIN_SCL, I2C_INT_PULLUP, I2C_FREQ

import demo_led  # pylint: disable=unused-import
from demo_ssd1306 import demoOLED
from demo_adc_tracker import demoBatMon

scl_pin = Pin(PIN_SCL, pull=Pin.PULL_UP if I2C_INT_PULLUP else None)
sda_pin = Pin(PIN_SDA, pull=Pin.PULL_UP if I2C_INT_PULLUP else None)
i2c = I2C(scl=scl_pin, sda=sda_pin, freq=I2C_FREQ)

# Just running demos for now
loop = asyncio.get_event_loop()
loop.create_task(demoOLED(i2c))
demoBatMon(i2c)
loop.run_forever()
