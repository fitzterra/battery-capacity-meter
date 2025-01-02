"""
Battery status and progress broadcasting module.

This module provides support for monitoring one or more BatteryController
instances and publishing regular progress messages via MQTT_.

It also has the basic framework in place for receiving commands via MQTT_ should
this be needed in future.

It uses the **Peter Hinch's** `Asynchronous MQTT`_ module which also handles
the Wifi connection.

MQTT Connection Config
----------------------

The MQTT server and connection details are contained in the `net_conf`, and it's
site local equivalent, module.

Warning:
    Need to complete docs here.

.. _MQTT: https://en.wikipedia.org/wiki/MQTT
.. _`Asynchronous MQTT`: https://github.com/peterhinch/micropython-mqtt
"""

import json
import ntptime
import uasyncio as asyncio
from lib import ulogging as logging
from lib.mqtt_as import MQTTClient, config
from lib.bat_controller import BatteryController
import net_conf

# This is the main BCM control topic. We will subscribe to this main and all
# it's sub-topics.
CTL_TOPIC = "BCM/ctl/#"
PUB_TOPIC = "BCM/state"


async def clientUp(client):
    """
    Task to monitor for when the client comes up.

    Once the client is up, we set the time from the network and also subscribe
    to any topics we need to.
    """

    while True:
        # Wait on an Event
        await client.up.wait()
        # We need to clear the event to signal that we noticed it.
        client.up.clear()

        # Subscribe to any topics defined
        await client.subscribe(CTL_TOPIC, 0)

        # Sync network time
        try:
            # We use the default `pool.ntp.org` time servers for the time.
            ntptime.settime()
            logging.info("Network: Time synced to pool.ntp.org.")
        except Exception as exc:
            logging.error("Network: Error syncing time: %s", exc)


async def messages(client):
    """
    Manage control messages received via MQTT.
    """
    async for topic, msg, retained in client.queue:
        logging.info("MQTT CTL: %s, %s, %s", topic.decode(), msg.decode(), retained)


def buildMsg(bc: BatteryController) -> dict:
    """
    Builds the MQTT message based on the status of the supplied BC.

    Args:
        bc: A Battery controller instance.
    """

    msg = {"state": bc.state_name}

    if bc.state == bc.S_DISABLED:
        # Nothing more for disabled.
        return msg

    # Add the battery ID if we have it.
    if bc.bat_id:
        msg["bat_id"] = bc.bat_id

    if bc.state not in [
        bc.S_BAT_ID,
        bc.S_CHARGE,
        bc.S_DISCHARGE,
        bc.S_CHARGED,
        bc.S_DISCHARGED,
    ]:
        # Any state other than the above we do not have anything else to add.
        return msg

    # Always add the battery voltage
    msg["bat_v"] = bc.bat_v

    # Nothing more for only battery with id
    if bc.state == bc.S_BAT_ID:
        return msg

    # We are charging or discharging. Add the correct charge monitor details.
    # @pylint: disable=protected-access
    mon = bc._ch_mon if bc.state in (bc.S_CHARGE, bc.S_CHARGED) else bc._dch_mon

    msg["adc_v"] = mon.voltage
    msg["current"] = mon.current
    msg["charge"] = mon.charge
    msg["mAh"] = mon.mAh
    msg["tm"] = round(mon.charge_time / 1000)
    msg["shunt"] = mon._shunt

    return msg


async def broadcast(bcs: list[BatteryController,]):
    """
    Function continue sly checks the BCs to monitor and broadcast current status via
    MQTT...

    Warning:
        Docs needs to be completed...
    """

    # Configuration
    config["ssid"] = net_conf.SSID
    config["wifi_pw"] = net_conf.PASS
    config["server"] = net_conf.MQTT_HOST
    config["queue_len"] = 1  # Use event interface with default queue size
    MQTTClient.DEBUG = True  # Optional: print diagnostic messages

    # Create an MQTTClient instance and wait for it to connect.
    client = MQTTClient(config)
    await client.connect()

    # While we wait, we start the event tasks.
    for task in (clientUp, messages):
        asyncio.create_task(task(client))

    stats = {bc._name: {"state": None} for bc in bcs}

    while True:
        for bc in bcs:
            await asyncio.sleep_ms(250)

            st = stats[bc._name]
            topic = msg = None

            if st["state"] != bc.state or bc.state in [
                bc.S_BAT_ID,
                bc.S_CHARGE,
                bc.S_DISCHARGE,
            ]:
                st["state"] = bc.state
                topic = f"{PUB_TOPIC}/{bc._name}"
                msg = buildMsg(bc)

            if msg:
                await client.publish(topic, json.dumps(msg), qos=0)
