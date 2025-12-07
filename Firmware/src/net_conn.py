"""
Module to connect and handle and monitor a network connection.

Using this module entails:

* Making sure the network parameters are set in `net_conf` (see `connect`
  for more details)
* Starting the `connectAndMonitor()` coro in an asyncio loop which will
  establish the network connection via `connect()`, sync the time via
  `syncTime()` and will also manage the `IS_CONNECTED` global.

This module also provides the `syncTime()` function to set the local date/time
via NTP_

Attributes:
    logger: Local module logger instance.

    CONNECT: Connection control. If ``False``, a `connect()` will not try to
        establish a connection.

        This is set from `net_conf.CONNECT` if `CONNECT` is defined in
        `net_conf`, else it defaults to False.

    LED_PIN: A pin connected to an `LED` to toggle to indicate the network status.

        If the `LED` is reverse connected (anode to VCC and pin to `LED` cathode,
        meaning 0 on the pin switched the `LED` on), indicate this by making the
        pin a negative value. Otherwise, to switch the LED on, the pin will be
        taken high (expecting the `LED` cathode to be connected to GND).

    IS_CONNECTED: Will be set to True/False depending on the current connection
        status if the `connectAndMonitor()` task is started.

    TIME_SYNCED: Will be ``False`` initially, and is updated by calling
        `syncTime()`. Will be ``True`` if the time was synced via NTP_.

.. _NTP: https://en.wikipedia.org/wiki/Network_Time_Protocol
"""

import ntptime
import uasyncio as asyncio
import network
from lib.ulogging import getLogger
from lib.led import LED
import net_conf

logger = getLogger(__name__)

# Global connection switch from net_conf
CONNECT: bool = getattr(net_conf, "CONNECT", False)

# This is the default LED pin for an S2 Mini.
LED_PIN: int | None = getattr(net_conf, "CONN_LED_PIN", None)

IS_CONNECTED: bool = False
TIME_SYNCED: bool = False


async def connect():
    """
    Sets up the network connection and then tries to connect.

    Note:
        This is an *async* function so must be awaited to allow for the
        connection to be established without blocking.

    The network config is defined in `net_conf`, and the following settings
    from there are relevant here:

    * `net_conf.SSID` : The WiFi SSID to connect to.
    * `net_conf.PASS` : Password for the connection.
    * `net_conf.HOSTNAME` : If set, it will be set as the client hostname.
    * `net_conf.CONNECT` : Connection control. The local `CONNECT` is set from
      this value if it is present in `net_conf`, defaulting ``FALSE`` if not.
      If `CONNECT` resolves to ``False``, no connection will be attempted.

    After setting up the connection this function will wait for specific period
    of time for the connection to be established. If the connection does not
    come up in this time, or if any connection error occurs, ``False`` is
    returned.

    Returns:
        True if the connection is successful, False otherwise.
    """
    log_name = "NetConn"

    if not CONNECT:
        logger.info("%s: Not connecting to network because CONNECT is False.", log_name)
        return False

    # Create a station interface and activate it
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        logger.info("%s: Already connected: %s", log_name, wlan.ifconfig())
        return True

    # Set the hostname if available
    if net_conf.HOSTNAME:
        logger.info("%s: Setting hostname to: %s", log_name, net_conf.HOSTNAME)
        wlan.config(hostname=net_conf.HOSTNAME)

    tout_cnt = 16
    logger.info("%s: Connecting to network...", log_name)
    try:
        wlan.connect(net_conf.SSID, net_conf.PASS)
        while tout_cnt:
            if wlan.isconnected():
                return True
            tout_cnt -= 1
            logger.warning("Waiting for connection to come up (%s)...", tout_cnt)
            await asyncio.sleep(1)
        logger.error("Timed out waiting for network to come up.")
        return False
    except OSError as exc:
        logger.error("%s: Error setting up connection: %s", log_name, exc)
    except Exception as exc:
        logger.error("%s: Unhandled error setting up connection: %s", log_name, exc)

    return False


def disconnect():
    """
    Disconnects from the network if is is connected.

    Side effect:
        Sets `IS_CONNECTED` to False
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
        wlan.active(False)
        return

    wlan.disconnect()
    wlan.active(False)
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


async def connectAndMonitor():
    """
    This is an async task that will `connect` to the network, and then monitor
    the connection.

    Warning:
        It seems that when the connection is lost (tested by switching off the
        WiFi router), the internal network stack will automatically and
        continuously try to re-establish the connection.

        So, if a connection loss is detected all we do is go into a loop and
        wait for the IP address to appear on the interface again. This is done
        instead of disconnecting and then trying a fresh connection again,
        which might be required on other platform where the connection is not
        retried by the lower levels.

        This functionality seems to be built into Micropython or at the lower
        ESP32 level, so may not work the same on other platforms. For these
        cases some tweaking of this flow may be needed.

    This task will keep `IS_CONNECTED` set to indicate the network connection
    status, and will never return.
    """
    # pylint: disable=global-statement

    global IS_CONNECTED

    if not CONNECT:
        logger.info("NetMon: Not starting connection monitor because CONNECT is False")
        return

    mon_led = LED(LED_PIN)
    mon_led.flash()

    while not await connect():
        logger.info("NetMon: Trying a disconnect, sleep a bit and then reconnecting...")
        try:
            disconnect()
        except Exception as exc:
            logger.error("NetMon: Disconnect error: %s", exc)

        await asyncio.sleep(3)

    IS_CONNECTED = True
    mon_led.on()
    syncTime()

    # Create a local dict of the various STAT_ constants from network in order
    # to report the status names.
    stat_names = {getattr(network, n): n for n in dir(network) if n.startswith("STAT_")}

    wlan = network.WLAN(network.STA_IF)

    while True:
        status = wlan.status()
        if status != network.STAT_GOT_IP:
            logger.info(
                "NetMon: Not connected. Status: %s. IS_CONNECTED=%s",
                stat_names.get(status, status),
                IS_CONNECTED,
            )
            if IS_CONNECTED:
                IS_CONNECTED = False
                mon_led.flash()
        else:
            if not IS_CONNECTED:
                IS_CONNECTED = True
                logger.info("NetMon: Connection is up: %s", wlan.ifconfig())
                syncTime()
                mon_led.on()

        await asyncio.sleep_ms(1000)
