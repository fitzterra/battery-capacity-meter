"""
Main application entry point.
"""

import uasyncio as asyncio
from config import i2c
from lib.charge_controller import ChargeControl
from screens import uiSetup

# Set up the charge controller and screens
ChCtl = ChargeControl(i2c)
uiSetup(ChCtl.ctlNames())

# get the asyncio loop and run forever
loop = asyncio.get_event_loop()
loop.run_forever()
