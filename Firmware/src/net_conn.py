"""
Module to connect and handle network connections if not using the `Asynchronous
MQTT`_ module.

Note:
    The `state_broadcast` module uses `Asynchronous MQTT`_ for broadcasting
    battery status and will thus use the `mqtt_as` module for both handling the
    network connection as well as the MQTT connection.
    This means that this module will not be used in production, but is still
    kept in the code base if simple networking testing or such may be needed.

The network access credentials are defined in thew `net_conf` module, and it's
site local settings.

This module also provides the `syncTime()` function to set the local date/time
via NTP_

Attributes:
    CONNECT: Connection control. If ``False``, a `connect()` will not try to
    LED_PIN: A pin connected to an LED to toggle to indicate the network status.
        If the LED is reverse connected (anode to VCC and pin to LED cathode,
        meaning 0 on the pin switched the LED on), indicate this by making the
        pin a negative value. Otherwise, to switch the LED on, the pin will be
        taken high (expecting the LED cathode to be connected to GND).
    IS_CONNECTED: Will be set to True/False depending on the current connection
        status if the `monitor()` task is started.
    TIME_SYNCED: Will be ``False`` initially, and is updated by calling
        `syncTime()`. Will be ``True`` if the time was synced via NTP_.

.. _Asynchronous MQTT: https://github.com/peterhinch/micropython-mqtt
.. _NTP: https://en.wikipedia.org/wiki/Network_Time_Protocol
"""

import ntptime
import uasyncio as asyncio
import network
from micropython import const
from lib import ulogging as logger
from lib.led import LED
import net_conf

# Warning: not very Pythonic :-(
# We predefine the expected values from the connection.py settings file here
# with default values, and override them by doing a wildcard import from
# connection. Only those values defined will overwrite our local defaults.
CONNECT: bool = False
# This is the default LED pin for an S2 Mini.
LED_PIN: int = const(15)

IS_CONNECTED: bool = False
TIME_SYNCED: bool = False


def connect():
    """
    Connect to network.

    The network config is set by `net_conf.SSID` and `net_conf.PASS` if `CONNECT` is ``True``. If
    `CONNECT` is ``False``, no connection will be attempted.

    This function only connects to the network, and it would be a good
    """
    if not CONNECT:
        logger.info("NetConn: Not connecting to network because CONNECT is False.")
        return

    # Create a station interface and activate it
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        logger.info("NetConn: Already connected: %s", wlan.ifconfig())
        return

    # Set the hostname if available
    if net_conf.HOSTNAME:
        logger.info("NetConn: Setting hostname to: %s", net_conf.HOSTNAME)
        wlan.config(hostname=net_conf.HOSTNAME)

    logger.info("NetCon: Connecting to network...")
    wlan.connect(net_conf.SSID, net_conf.PASS)


def disconnect():
    """
    Disconnects from the network if is is connected.
    """
    # pylint: disable=global-statement

    global IS_CONNECTED

    IS_CONNECTED = False

    # Create a station interface and activate it
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    logger.info("NetDiscon: Disconnecting from network...")

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

    logger.info("syncTime: Setting date/time via NTP...")

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


async def monitor():
    """
    This is an async task that will monitor the network connection.

    Currently it monitors the WLAN connection and then it detects the
    connection has dropped, it will update `IS_CONNECTED` to ``False`` and
    switch off the monitor LED.

    When a connection is established, it will again update `IS_CONNECTED` to
    ``True``, call `syncTime()` and turn the monitor LED on.

    The idea was that this will try to re-establish the connection, but I ran
    into some issues getting this to work - read on...

    The way I tested was to kick the connection on the router, but I suspect
    this does a deauth, and may not be representative of a real connection
    loss.

    On the ESP32 I tested, this puts the WLAN in some state where you can not
    reconnect - or at least not with everything I tried like forcing a
    disconnect, deactivating/reactivating the interface, etc. It seems the
    ESP32 when in this state will wait around 60 seconds and then reconnect
    automatically.

    Other issues where the AP goes away, or the signal is not good may result
    in different states of the ESP32 WLAN interface, but that is too much of an
    effort to test at the moment.
    """
    # pylint: disable=global-statement

    global IS_CONNECTED

    if not CONNECT:
        logger.info("NetMon: Not starting connection monitor because CONNECT is False")
        return

    mon_led = LED(LED_PIN)
    mon_led.off()

    # Create a local dict of the various STAT_ constants from network in order
    # to report the status names.
    stat_names = {getattr(network, n): n for n in dir(network) if n.startswith("STAT_")}

    wlan = network.WLAN(network.STA_IF)

    while True:
        status = wlan.status()
        if status != network.STAT_GOT_IP:
            logger.info(
                "NetMon: Not connected. Status: %s", stat_names.get(status, status)
            )
            if IS_CONNECTED:
                IS_CONNECTED = False
                mon_led.off()
        else:
            if not IS_CONNECTED:
                IS_CONNECTED = True
                logger.info("NetMon: Connection is up: %s", wlan.ifconfig())
                syncTime()
                mon_led.on()

        await asyncio.sleep_ms(1000)


def _test():
    """
    Function for testing `connect()`.

    Just import it and execute it.

    It will try to connect and then start the monitor to log network status.
    """

    connect()

    async def runEm():
        """
        Nike
        """
        await asyncio.gather(monitor())

    logger.info("Starting tasks...")
    asyncio.run(runEm())
