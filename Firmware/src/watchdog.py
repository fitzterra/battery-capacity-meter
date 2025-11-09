"""
Module to set up a watchdog to check for code freezes and restart the MCU if it
happens.

In addition to running the `watchdog`, this async function will also
periodically log memory stats that may help in determining freezes of other
problems.

The memory stats can also be pushed via MQTT if setting up logging for this
module in `config.LOGGING_CFG`

Attributes:
    WDT_TIMEOUT: How long we allow before the timer times out and resets
        without feeding the dog. This is in milliseconds.
    ML_PERIOD: How often we log memory stats - in seconds
    WDT_BYPASS: The name of a file, which if found on the file system, will be
        taken as an indicator to not start the watchdog timer on this boot.

        With the WDT running, it is sometimes difficult to upload new firmware
        since if the add is stopped and not feeding the dog, the WDT is still
        running in the background.

        This means when the new firmware is being uploaded the WDT will kick in
        and reset, thus failing the upload.

        To bypass this, create a file with this name on the FS, reset and when
        back online, do the firmware upload.

        With the file present, you will get one startup with the WDT disabled,
        but the file will be removed if found to ensure we do not forget it for
        production.
"""

import os
import gc
import uasyncio as asyncio
import utime as time
from machine import WDT
from lib.ulogging import getLogger
from config import WD_LOG_MEM

logger = getLogger(__name__)

# How long we allow before the timer times out and resets without feeding
# the dog. This is in milliseconds
WDT_TIMEOUT = 3000
# How often we log memory stats - in seconds
ML_PERIOD = 60
# A file flag to bypass the WDT for this boot.
WDT_BYPASS = "wdt_bypass"


async def watchdog():
    """
    A watchdog process that sets up a hardware watchdog and then keeps feeding
    it to avoid it resetting the system.

    This is in case the code freezes leaving us in a charging or discharging
    state.

    To get an idea if a system reset was caused by the WDT, you can request the
    reset log - see `telemetry.returnResetLog`

    We also log memory usage here every now and then
    """
    # The watchdog interferes with uploading new firmware because it stops the
    # app which feeds the dog, but internally to the watchdog still runs. If we
    # do not then get the firmware uploaded in time, it resets the connection
    # and the upload fails.
    # To overcome this, we allow a one shot override flag to be set that will
    # not start the watchdog on the next startup. BUT... the flag will be auto
    # removed once it was seen to ensure we do not accidentally forget to set
    # it for prod. The flag is just a file that exists on the FS - note it will
    # be removed if found, so do not put any important info in the file.
    if WDT_BYPASS in os.listdir():
        # Remove it
        os.unlink(WDT_BYPASS)
        logger.info("Bypass setting up a watchdog timer for this boot.")
        return

    # How long we allow before the timer times out and resets without feeding
    # the dig. This is in milliseconds
    wdt_timeout = 3000

    # Create the watchdog timer
    wdt = WDT(timeout=wdt_timeout)

    # The next time we need to log mem stats - we need to convert ML_PERIOD to
    # millis here.
    next_mem_log = time.ticks_add(time.ticks_ms(), ML_PERIOD * 1000)

    # Now we run forever
    while True:
        # We sleep for 500 millis less that the timer timeout value...
        await asyncio.sleep_ms(wdt_timeout - 500)
        # ... and then we feed the dog
        wdt.feed()

        # Log mem stats?
        if WD_LOG_MEM and time.ticks_diff(next_mem_log, time.ticks_ms()) <= 0:
            logger.info("Memory (alloc/free): %s / %s", gc.mem_alloc(), gc.mem_free())
            # The next time we need to log mem stats - we need to convert ML_PERIOD to
            # millis here.
            next_mem_log = time.ticks_add(time.ticks_ms(), ML_PERIOD * 1000)
