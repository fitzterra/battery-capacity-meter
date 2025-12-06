"""
Telemetry Manager.

This module allows telemetry data to be sent, and remote commands to be
received and executed, via MQTT.

This module depends on the `net_conn` module to establish and maintain the
network connection, the `aiomqttc` (`Async MQTT`_ by **Carlos Tangerino**)
module for MQTT_ communications, and the `net_conf` module for configuration.

Note:
    As of December 2025, the main `Async MQTT`_ branch seems to have been
    broken from the last documentation merges done to that branch.

    While this is still the case, I have forked the repo and created my own
    minor changes from the last good commit on the upstream repo. This fork is
    currently in use here via a Git submodule.

See `CONFIG` for the required configuration.

The standard usage is:
    * Ensure a connection is established and maintained (`connectAndMonitor`)
    * Start the `mqManager` as a new asyncio task which will:
        * Set callback handlers for when the connection is established
          (`_onConnect`), and for when messages are received for topics we
          subscribe to (`_msgRX`). Subscription to topics are done in the
          `_onConnect()` callback.
        * Connect to the MQTT host (`_clientConnect`) and monitor and
          maintain this connection.
        * Once connected, will:
            * call `_onConnect` to subscribe to any topics
            * start a loop while `SHUTDOWN` is not set monitor the connection
            * regularly call `_publishQueue` to publish any awaiting telemetry
              messages (see `queueMsq`)
    * While the `mqManager` task is running, the app can publish any telemetry
      messages by calling `queueMsq`
    * Any messages we receive for topics subscribed to will be handled by
      `_msgRX`....

Attributes:
    CONFIG: MQTT Config dict built using the below config values from
        `net_conf` if defined (system or site local conf).

        * ``MQTT_HOST`` - required
        * ``MQTT_PORT`` - defaults to 1833 if not defined
        * ``MQTT_USER`` - defaults to ``None`` (no user auth) if not defined
        * ``MQTT_PASS`` - defaults to ``None`` (no password) if not defined
        * ``MQTT_KEEPALIVE`` - defaults to 60 seconds
        * ``MQTT_WILL_TOPIC`` - No topic is not defined
        * ``MQTT_WILL_MESSAGE`` - No message if not defined
        * ``MQTT_WILL_QOS`` - defaults to 0 if not defined
        * ``MQTT_WILL_RETAIN`` - defaults to ``False`` if not defined.

    PUB_TOPICS: A list of topics for the messages in the `PUB_Q`. See
        `queueMsq` for more details.

    PUB_Q: Queue for any outgoing messages. Use `queueMsq` to add to this queue.

    Q_MAX_LEN: Maximum number of messages that are allowed to queue before we
        start discarding the oldest. This is done by `queueMsq`

    CB_MAP: A dictionary that maps a received message string (key) to a
        callback coro.

        When a message is received on any of the topics subscribed to
        (`net_conf.MQTT_CTL_TOPIC`), this message is looked up in this map. If
        found, the value is expected to be a pointer to an asyncio callback
        function (coro) that will be awaited on.

        The coro signature is as follows:

        .. python::

            async function callback(topic: str, message: str)

    SHUTDOWN: Flag that can be set to True to close the MQTT connection and
        shut down the `mqManager`

    logger: Local module logger.

.. _MQTT: https://en.wikipedia.org/wiki/MQTT
.. _`Async MQTT`: https://github.com/Tangerino/aiomqttc
"""

import random
import json
import uasyncio as asyncio
import utime as time
from lib.aiomqttc import MQTTClient
from lib.ulogging import getLogger, telemetry_logs
from lib.bat_controller import BatteryController, telemetry_trigger
from config import TELEMETRY_EMIT_FREQ

# This is to get net_conn.IS_CONNECTED - Do not try to only import IS_CONNECTED
# since this will give us a copy of what IS_CONNECTED was at the time of
# import, and not track it as it changes.
import net_conn
import net_conf


CONFIG: dict = {
    "server": net_conf.MQTT_HOST,
    "port": getattr(net_conf, "MQTT_PORT", 1883),
    "user": getattr(net_conf, "MQTT_USER", None),
    "password": getattr(net_conf, "MQTT_PASS", None),
    "keepalive": getattr(net_conf, "MQTT_KEEPALIVE", 60),
    "will_topic": getattr(net_conf, "MQTT_WILL_TOPIC", None),
    "will_message": getattr(net_conf, "MQTT_WILL_MESSAGE", None),
    "will_qos": getattr(net_conf, "MQTT_WILL_QOS", 0),
    "will_retain": getattr(net_conf, "MQTT_WILL_RETAIN", False),
    "clean_session": True,
    "verbose": 0,
}

PUB_TOPICS: list = []
PUB_Q: list = []
Q_MAX_LEN = 10

SHUTDOWN = False


logger = getLogger(__name__)


# Callback functions for control messages. These should probably be defined in
# a submodule to make this module more generic, but for now we do it here.


async def returnResetLog(tpc, msg):
    """
    Called to publish the current reset cause log (see `boot.recordResetReason`
    for more details) via MQTT.

    The reset cause log is updated with the cause for the last reset every time
    the controller boots. This can help us understand why the last reset
    happened, especially if that was due to a code freeze and the reset was by
    the `watchdog` timer.

    This function will be called from the `_msgRX` callback when a
    ``get_reset_log`` message was received on the `MQTT_CTL_TOPIC` topic.

    We will read the log, which will only contain the last few entries, and
    then publish the full log file data on the `MQTT_LOG_TOPIC` ``/reset_log``
    topic
    """
    # We do not always use the args generic args that gets passed into the
    # callback, so @pylint: disable=unused-argument

    log_f = "reset_cause.log"

    with open(log_f, "r", encoding="utf-8") as f:
        topic = f"{net_conf.MQTT_LOG_TOPIC}/reset_log"
        queueMsq(topic, f.read())

    logger.info("returnResetLog: Reset log has been queued for delivery.")


# Map of callback functions for any received messages.
CB_MAP = {
    "get_reset_log": returnResetLog,
}


def queueMsq(topic: str | int, msg: str | None) -> int:
    """
    Interface to add a message to the publish queue (`PUB_Q`).

    Each message must have a topic to be published on.

    The `PUB_Q` is a FIFO queue consisting of a (possibly empty) list of 2-tuples:

        (topic_id, message)

    The ``topic_id`` is an index into `PUB_TOPICS` where the actual topics are
    kept as strings. The separate `PUB_TOPICS` list is so that we do not have
    to hardcode topics all over the app.

    The idea is that if a message is to be added to the queue, it's topic may
    be either a string or the actual ``topic_id`` (see further how to get the
    ``topic_id``).

    If a string, and topic does not already exist in `PUB_TOPICS`, it will be
    added as a new topic and the index recorded as the new ``topic_id``, which
    will then be returned after adding the message. The caller can from then on
    use the ``topic_id`` if set up to do so.

    In order to make it easier for setup code for various parts of the app to
    *register* their topics, this function can be called with no or an empty
    ``msg``. In this case, the topic will be added to `PUB_TOPICS` and the
    ``topic_id`` returned for further reference by the app or sub-system. No
    message is added to the `PUB_Q`.

    If ``topic`` is an integer that does not have and index in `PUB_TOPICS`,
    and error will be logged and the message discarded.

    Args:
        topic: The topic to publish the message on. This can either be a string
            or an integer to indicate the topic ID. See above.
        msg: If not None or empty, will be appended to the `PUB_Q` FIFO message
            queue.

    Returns:
        The topic ID (index into `PUB_TOPICS`) used for the topic on success,
        None on error with an error logged.
    """
    # Handle a string topic
    if isinstance(topic, str):
        topic_id = PUB_TOPICS.index(topic) if topic in PUB_TOPICS else None
        if topic_id is None:
            PUB_TOPICS.append(topic)
            topic_id = len(PUB_TOPICS) - 1
            logger.debug("Added new publish topic at ID %d : %s", topic_id, topic)
    else:
        # We assume it's an integer - caller will feel it if not...
        if not 0 <= topic < len(PUB_TOPICS):
            logger.error("Invalid topic ID [%s] for queueing message: %s", topic, msg)
            return None
        topic_id = topic

    # Do we have a message
    if msg in (None, ""):
        logger.debug("Not adding empty message to publish queue.")
        return topic_id

    # Are we at the max queue len?
    if len(PUB_Q) == Q_MAX_LEN:
        # Remove the oldest
        res = PUB_Q.pop(0)
        logger.info("Max PUB_Q len reached. Removed oldest: %s", res)

    # Add to queue
    PUB_Q.append((topic_id, msg))

    return topic_id


async def _onConnect(client, rc):
    """
    Called as soon as the MQTT connection is established.

    For now, all we do it subscribe to the `net_conf.MQTT_CTL_TOPIC`.

    If we will every make this module more dynamic, and not closely linked to
    this project as it is now, we will have to define topics and their
    callbacks more dynamically.

    If any subscribed messages are received, they will be handled by the
    `_msgRX` coro.
    """
    logger.info("_onConnect: connected with rc [%s]. Subscribing to topics...", rc)

    # Subscribe to the control topic
    await client.subscribe(f"{net_conf.MQTT_CTL_TOPIC}/#", 0)


async def _msgRX(client: MQTTClient, topic: str, message: bytes, retain: bool):
    """
    Called when new messages for the topics we have subscribed to, are received.

    This coro will check if the `CB_MAP` has a callback coro mapped for this
    message, and if so, await that callback coro passing in the topic and
    message.

    Args:
        topic: The topic the message was published on
        message: The message
    """
    # We do not always use the args generic args that gets passed into the
    # callback, so @pylint: disable=unused-argument

    logger.info("_msgRX: Received MQTT message on %s: %s", topic, message)

    # Convert to strings
    msg = message.decode()

    # Do we have a callback?
    cb = CB_MAP.get(msg, None)
    # Await on it if set
    if cb:
        await cb(topic, msg)


async def _clientConnect() -> MQTTClient:
    """
    Asynchronously establish a connection to an MQTT broker with retry logic.

    This function creates a new `MQTTClient` instance with settings from
    `CONFIG`, sets callback handlers, and attempts to connect to the
    MQTT broker with exponential backoff retry logic.

    The following config options are available. If the setting key is not in
    the dict, then the default as specified will be used:

    * ``server`` (str): MQTT broker hostname or IP. Required.
    * ``port`` (int): MQTT broker port. Defaults to 1883.
    * ``user`` (str): Username for authentication. Defaults to None - no auth.
    * ``password`` (str): Password for authentication. Defaults to None.
    * ``keepalive`` (int): MQTT keepalive time. Defaults to 60 secs.
    * ``verbose`` (int): Verbosity level. Defaults 0.
    * ``will_topic`` (str): Optional topic for a last will message. Defaults to None.
    * ``will_message`` (str): Optional last will message. Defaults to None.
    * ``will_qos`` (int): Optional QOS for the last will message. Defaults to 0.
    * ``will_retain`` (bool): Optionally set retaining for last will message. Defaults to False.

    Returns:
        MQTTClient: A connected MQTT client instance ready for publish/subscribe operations.

    Retry Logic:
        - Starts with a delay of 1 second.
        - Exponential backoff is applied up to a maximum delay of 60 seconds.
        - A small random jitter is added to the delay to avoid thundering herd issues.

    Example:
        >>> client = await client_connect(config)
        >>> await client.publish("topic/test", b"hello")
    """
    # Set up the client from the config
    client = MQTTClient(**CONFIG)

    # Register callbacks
    client.on_message = _msgRX
    client.on_connect = _onConnect
    # These are available, but currently we do not need them.
    # client.on_disconnect = on_disconnect
    # client.on_ping = on_ping

    mqtt_retry_min_delay = 1  # in seconds
    mqtt_retry_max_delay = 60

    delay = mqtt_retry_min_delay
    while True:
        logger.info("Connecting to MQTT broker...")
        if await client.connect():
            logger.info("Connected to MQTT broker.")
            break
        logger.error("Failed to connect to broker, retrying in %s seconds...", delay)
        await asyncio.sleep(delay + random.uniform(0, 0.5 * delay))
        delay = min(delay * 2, mqtt_retry_max_delay)

    return client


async def _publishQueue(client: MQTTClient):
    """
    Tries to publish any messages in the telemetry queue (`PUB_Q`)

    We expect the connection be up when called.

    If there are any messages in `PUB_Q`, they will asynchronously be published
    until the queue is empty or an error occurs.

    Message are added (`queueMsq`) published in a FIFO manner, and if the
    message was published without error, if is removed from the queue.

    Returns:
        True if there were no errors, False or None otherwise.
    """
    # Try to asynchronously empty the queue
    while PUB_Q:
        # Get the topic id and message for the first message in the queue, and
        # publish it
        topic_id, msg = PUB_Q[0]
        res = await client.publish(PUB_TOPICS[topic_id], msg)
        if not res:
            logger.error(
                "Error publishing message: topic=[%s], msg=[%s], Err: %s",
                PUB_TOPICS[topic_id],
                msg,
                client.get_last_error(),
            )
            # No point in continuing, so we return
            return res
        # Remove it from the queue
        PUB_Q.pop(0)

    return True


async def mqManager():
    """
    Main loop for managing the MQTT connection and sending and receiving
    messages.

    Will wait for the network connection to come up (`net_conn.IS_CONNECTED`)
    and then will enter the main loop. The main loop will run while `SHUTDOWN`
    is False, establish (`_clientConnect`) and monitor the MQTT connection, and
    also publish any new messages via calls to `_publishQueue`.

    If the MQTT connection drops, the client connection is disconnected, and
    then retried (`_clientConnect`) until it comes up again.
    """
    while not net_conn.IS_CONNECTED:
        logger.info("mqManager waiting for connection...")
        await asyncio.sleep(2)

    while not SHUTDOWN:
        try:
            client = await _clientConnect()
            while client.connected and not SHUTDOWN:
                # Empty the publish queue
                res = await _publishQueue(client)

                # If anything failed here, we probably disconnected, we break
                # out to retry the connection
                if not res:
                    break
                await asyncio.sleep(1)

            logger.error("Disconnected from MQTT broker")
            await client.disconnect()
            if not SHUTDOWN:
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Error in mqManager: {e}")
            await asyncio.sleep(5)


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
    and by extension the WiFi connection. The `MQTTClient` will do a best
    effort attempt to re-establish network connections if it gets lost.

    Besides monitoring the ``BC`` statuses, it also monitors
    `telemetry_trigger` and `telemetry_logs` for messages to publish.

    Normal BC telemetry is published on this topic::

        topic = f"{net_conf.MQTT_PUB_TOPIC}/{bc.name}"

    and the message is JSON which is built up by `buildMsg`

    Logs are published on this topic::

        topic = f"{net_conf.MQTT_LOG_TOPIC}/{log_level_str}"

    with the message just a raw string, which may contain exception details.

    """

    # We need access to some protected members of the BatteryController class,
    # so @pylint: disable=protected-access

    # Start the event tasks.
    for task in (net_conn.connectAndMonitor, mqManager):
        asyncio.create_task(task())

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
            queueMsq(topic, json.dumps(msg))

        # And also emit any logs
        while telemetry_logs:
            # Remove the earliest log entry
            lvl, msg = telemetry_logs.pop(0)

            topic = f"{net_conf.MQTT_LOG_TOPIC}/{lvl}"
            queueMsq(topic, msg)
