"""
Battery status and progress broadcasting module.

This module provides support for monitoring one or more `BatteryController`
instances and publishing regular progress messages via MQTT_ from the
`broadcast` async task. See the `buildMsg` function for details on the
telemetry message content.

It is also responsible for connecting to the network, and MQTT_ server, and for
monitoring this connection. If the connection to the WiFi or MQTT_ server drops,
the `MQTTClient` will automatically try to reconnect.

It also has the basic framework in place for receiving commands via MQTT_ should
this be needed in future.

It uses **Peter Hinch's** `Asynchronous MQTT`_ module which also handles the
WiFi connection as mentioned above.

The MQTT server and connection details are contained in the `net_conf`, and it's
site local config, module.

.. _MQTT: https://en.wikipedia.org/wiki/MQTT
.. _`Asynchronous MQTT`: https://github.com/peterhinch/micropython-mqtt
"""

import json
import ntptime
import utime as time
import uasyncio as asyncio
from lib import ulogging as logging
from lib.mqtt_as import MQTTClient, config
from lib.bat_controller import BatteryController, telemetry_trigger
import net_conf
from config import TELEMETRY_EMIT_FREQ


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

        logging.info("Network: Connection is up.")

        # Subscribe to any topics defined
        await client.subscribe(net_conf.MQTT_CTL_TOPIC, 0)

        # Sync network time
        try:
            # We use the default `pool.ntp.org` time servers for the time.
            ntptime.settime()
            logging.info("Network: Time synced to pool.ntp.org.")
        except Exception as exc:
            logging.error("Network: Error syncing time: %s", exc)


async def clientDown(client):
    """
    Task to monitor for when the client connection goes down.

    This only logs a message. The client will auto try to reconnect.
    """
    while True:
        # Pause until outage
        await client.down.wait()
        # We need to clear the event to signal that we noticed it.
        client.down.clear()

        logging.error(
            "Network: WiFi or broker is down. Auto reconnect will be attempted."
        )


async def messages(client):
    """
    Manage control messages received via MQTT.
    """
    async for topic, msg, retained in client.queue:
        logging.info("MQTT CTL: %s, %s, %s", topic.decode(), msg.decode(), retained)


def buildMsg(bc: BatteryController) -> dict:
    """
    Builds the MQTT message based on the status of the supplied BC.

    The telemetry message will be a dictionary as follows:

    .. python::

        {
            "state": the BC state name as a string (from state_name` property),

            # The rest only if not in S_DISABLED state
            "bat_id": battery ID if available,

            # The rest only if we have a battery id or busy charging or discharging
            "bat_v": the battery voltage,

            # The rest only if we are busy charging or discharging
            # The following are the values for the charge or discharge monitor
            # depending if we are charging or discharging.
            "adc_v": dis/charge monitor voltage in mV,
            "current": dis/charge monitor current in mA,
            "charge": dis/charge monitor accumulated charge in mC,
            "mAh": dis/charge monitor accumulated mAh,
            "tm": total time so far for this operation,
            "shunt": dis/charge monitor shunt/load resistor value,

            # The rest only if currently busy with a SoC measurement
            "soc_measure": {
                "uid": A unique ID for this SoC measurement
                "state": SoC measure state name (from state_name property),
                "cycle": current cycle number in SoC measurement,
                "cycles": total cycles to run for this SoC measurement,
                "cycle_tm": total time in seconds for the current state and cycle,
            }
        }

    Args:
        bc: A Battery controller instance.

    Returns:
        The dictionary as described above.
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

    # We are charging or discharging or in SoC measurement cycle. Add the
    # correct charge monitor details.  @pylint: disable=protected-access
    mon = bc._ch_mon if bc.state in (bc.S_CHARGE, bc.S_CHARGED) else bc._dch_mon

    msg["adc_v"] = mon.voltage
    msg["current"] = mon.current
    msg["charge"] = mon.charge
    msg["mAh"] = mon.mAh
    msg["tm"] = round(mon.charge_time / 1000)
    msg["shunt"] = mon._shunt

    if bc.soc_m.in_progress:
        msg["soc_measure"] = {
            "uid": bc.soc_m.uid,
            "state": bc.soc_m.state_name,
            "cycle": bc.soc_m.cycle,
            "cycles": bc.soc_m.cycles,
            "cycle_tm": bc.soc_m.cycle_tm,
        }

    return msg


async def broadcast(bcs: list[BatteryController,]):
    """
    Monitors each `BatteryController` in the ``bcs`` list and broadcasts MQTT
    messages on status changes and charge/discharge progress.

    In addition to monitoring the BCs, this task also sets up the `MQTTClient`
    and by extension the WiFi connection, and also connects to the network.

    Warning:
        Docs needs to be completed...
    """

    # We need access to some protected members of the BatteryController class,
    # so @pylint: disable=protected-access

    # Network configuration using mqtt_as config structure
    config["ssid"] = net_conf.SSID
    config["wifi_pw"] = net_conf.PASS
    config["server"] = net_conf.MQTT_HOST
    config["queue_len"] = 1  # Use event interface with default queue size
    MQTTClient.DEBUG = net_conf.MQTT_DEBUG  # Optional: print diagnostic messages

    # Create an MQTTClient instance and wait for it to connect.
    client = MQTTClient(config)
    await client.connect()

    # Start the event tasks.
    for task in (clientUp, clientDown, messages):
        asyncio.create_task(task(client))

    # Keeps some state for each of the BCs
    state = {
        bc.name: {
            "state": None,
            "bat_v": None,
            "next_emit": time.ticks_add(time.ticks_ms(), TELEMETRY_EMIT_FREQ),
        }
        for bc in bcs
    }

    while True:
        # We sleep a short time here to be fairly responsive to changes to be
        # emitted
        await asyncio.sleep_ms(100)

        # Check if we have any BCs that needs telemetry emitted
        for bc in bcs:
            # If this bc was already added as a trigger from an external
            # process, we skip any further checks - it will get an emit run
            if bc in telemetry_trigger:
                continue

            # There are a number of conditions that can cause telemetry data to
            # be emitted. This is n if statement with all these conditions. If
            # any one of them are true for this BC, we mark the BC for
            # telemetry emission.
            if (
                # Anytime a status changes - compared with our saved state
                (state[bc.name]["state"] != bc.state)
                # When in S_BAT_ID state (after dis/charge) the battery voltage
                # takes time to stabilize. We keep record of the voltage in the
                # BC state structure and then check for changes.
                or (bc.state == bc.S_BAT_ID and bc.bat_v != state[bc.name]["bat_v"])
                # When in one of the continues emit states (dis/charging), and emit time is reached
                or (
                    bc.state in [bc.S_CHARGE, bc.S_DISCHARGE]
                    and time.ticks_diff(time.ticks_ms(), state[bc.name]["next_emit"])
                    > 0
                )
            ):
                telemetry_trigger.append(bc)

        # Now emit any telemetry for any BC that are ready
        for _ in range(len(telemetry_trigger)):
            # Remove it from the trigger list
            bc = telemetry_trigger.pop(0)

            # State updates:
            # Set it's next emit time
            state[bc.name]["next_emit"] = time.ticks_add(
                time.ticks_ms(), TELEMETRY_EMIT_FREQ
            )
            # Update the state
            state[bc.name]["state"] = bc.state
            # And the battery voltage
            state[bc.name]["bat_v"] = bc.bat_v

            msg = buildMsg(bc)
            topic = f"{net_conf.MQTT_PUB_TOPIC}/{bc.name}"
            await client.publish(topic, json.dumps(msg), qos=0)
