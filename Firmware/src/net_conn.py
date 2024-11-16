"""
Handles network connection.

The network connection details are defined in a file called ``connection.py``
which should look like this (and be a valid importable Python module)

.. python::

    CONNECT = True        # Will refuse to connect if False
    SSID = "ap_ssid"
    PASS = "ap_password"

This connection file will be imported and the values defined therein will be
used by `connect()` to establish the WiFi connection.
If the file is not found, or importing it results in an error, the defaults for
its expected values will be set as described below.

This file is not versioned in the project repo and is expected to be installed
per device, or the application should be able to create and update this file
via some UI.

This module also provides the `syncTime()` function to set the local date/time
via NTP_

Attributes:
    CONNECT: Connection control. If ``False``, a `connect()` will not try to
        connect to the network. Will be imported from ``connection.py``, and
        default to ``False`` if this import fails.
    SSID: The SSID for the AP to connect to. Defaults to the empty string if
        not importable from ``connection.py``.
    PASS: The password for connecting to the AP. Defaults to the empty string
        if not importable from ``connection.py``.
    MAX_TRIES: Maximum number of tries to connect to the AP before giving up.
    IS_CONNECTED: Will be set to True once the network is connected
    TIME_SYNCED: Will be ``False`` initially, and is updated by calling
        `syncTime()`. Will be ``True`` if the time was synced via NTP_.

.. _NTP: https://en.wikipedia.org/wiki/Network_Time_Protocol
"""

import ntptime
import uasyncio as asyncio
import network
from lib import ulogging as logger

try:
    from connection import *  # Wildcard is OK here @pylint: disable=wildcard-import
except Exception as exc:
    logger.error("Error importing connection details: %s", exc)
    # Preset to false which we would have brought in from connection.py
    CONNECT: bool = False
    SSID: str = ""
    PASS: str = ""

MAX_TRIES: int = 5
IS_CONNECTED: bool = False
TIME_SYNCED: bool = False


async def connect():
    """
    Non-blocking network connector.

    This is an asyncio coro that will attempt to connect the network set by
    `SSID` and `PASS` if `CONNECT` is ``True``. If `CONNECT` is ``False``, no
    connection will be attempted.

    If a connection is established, it will set `IS_CONNECTED` to ``True``
    """
    # The CONNECT, SSID and PASS constants will be available, and we're OK with
    # global, so @pylint: disable=used-before-assignment,global-statement

    global IS_CONNECTED

    IS_CONNECTED = False

    if not CONNECT:
        logger.info("Not connecting to network because CONNECT is False.")
        return

    # Create a station interface and activate it
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        logger.info("Already connected: %s", wlan.ifconfig())
        IS_CONNECTED = True
        return

    logger.info("Connecting to network...")
    wlan.connect(SSID, PASS)
    for n in range(MAX_TRIES):
        if wlan.isconnected():
            logger.info("Network connected: %s", wlan.ifconfig())
            IS_CONNECTED = True
            return
        await asyncio.sleep_ms(1000)
        logger.info("  Waiting to connect: %s", n)

    logger.error("Unable to connect to SSID: %s", SSID)


def disconnect():
    """
    Disconnects from the network if is is connected.
    """
    # Create a station interface and activate it
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    logger.info("Disconnecting from network...")

    if not wlan.isconnected():
        logger.info("  Not currently connected.")
        return

    wlan.disconnect()
    logger.info("   Disconnected.")


def syncTime():
    """
    Updates the internal date/time to the world time if a network connection is
    present.

    This function will use NTP_ to set the local clock to the real date and
    time.

    Note:
        The date/time is set to GMT_ and the local time zone is not currently
        taken into account.

    Note:
        This is a blocking call, so should probably not be done while running a
        asyncio application.

    Any errors setting the date will be logged. If a successful update occurred,
    the `TIME_SYNCED` global will be set ``True``, else it will be ``False``

    .. _NTP: https://en.wikipedia.org/wiki/Network_Time_Protocol
    .. _GMT: https://en.wikipedia.org/wiki/Greenwich_Mean_Time
    """
    # pylint: disable=global-statement

    logger.info("Setting date/time via NTP...")

    global TIME_SYNCED

    TIME_SYNCED = False

    if not IS_CONNECTED:
        logger.info("  No internet connection. Cannot set date/time.")

    try:
        # We use the default `pool.ntp.org` time servers for the time.
        ntptime.settime()
        TIME_SYNCED = True
    except Exception as exc:
        logger.error("  Error setting time: %s", exc)


def _test():
    """
    Function for testing `connect()`.

    Just import it and execute it. It will start an asyncio task to monitor
    `IS_CONNECTED` and also start a task to run `connect()`. Output and
    progress is logged.
    """

    async def waitForConn():
        """
        Waits for the connection to become live
        """

        logger.info("Gonna wait for connection....")
        for _ in range(20):
            logger.info("Connection is up: %s", IS_CONNECTED)
            if IS_CONNECTED:
                return
            logger.info("Sleeping a bit while waiting")
            await asyncio.sleep_ms(700)

        logger.info("No connection was established.")

    async def runEm():
        """
        Nike
        """
        await asyncio.gather(waitForConn(), connect())

    logger.info("Starting tasks...")
    asyncio.run(runEm())
