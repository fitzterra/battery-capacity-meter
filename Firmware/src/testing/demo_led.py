"""
Simple demo to show/test the onboard LED by simply flashing it asynchronously.
"""

from lib.led import LED

from config import PIN_LED

# Instantiate an LED instance using the default onboard LED pin and then
# asynchronously start flashing it at the default rate.
led = LED(PIN_LED)
led.flash()
