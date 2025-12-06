"""
Network and related configs module.

This module contains the required configs for the WiFi and MQTT access
credentials as used by the `telemetry` and `net_conn` modules.

It is used by various other modules that needs access to this config.

Many of these values are simply default values for config and documentation
purposes, and things like passwords or sensitive details are not stored in the
codebase.

Any sensitive or site local values will be stored in a local site config file
and will be managed as described in the `sitelocal_conf` module.

Attributes:
    CONNECT: Global connection control.

        If False or not defined, `net_conn.connect()` will not try to
        establish a network connection.

    SSID: The SSID for the AP to connect to. Expects to be overridden from a
        site local config.

    PASS: The password for connecting to the AP. Expects to be overridden from a
        site local config.

    HOSTNAME: The hostname to use on the network. If None, no hostname will be
        set specifically. May be overridden from a site local config.

    CONN_LED_PIN: Optional GPIO pin connected to an LED that should be used to
        indicate the network connection status.

        This can be None (default) to disable this feature. If the LED is
        active low (lights up on with a low state, and off with a high pin
        state), then make the pin value the negative of the actual GPIO.
        So, -16 says use GPIO 16, but that it has active low control.

    MQTT_HOST: The name for the MQTT server to use for MQTT messages. Expects
        to be overridden from a site local config.

    MQTT_PORT: The port on `MQTT_HOST` to connect to. May be overridden from a
        site local config.

    MQTT_PUB_TOPIC: This is the base topic used to publish state messages on.

        ``BatteryController.name`` will be appended to the topic to make unique
        topics per battery controller name.

    MQTT_CTL_TOPIC: This is the topic to subscribe to for MQTT control
        messages. We will subscribe for all sub topic of this topic (#).

    MQTT_LOG_TOPIC: This is the topic to subscribe to for all log messages
        published by `telemetry.broadcast`.
"""

from sitelocal_conf import overrideLocal

CONNECT: bool = True
SSID: str = ""
PASS: str = ""
HOSTNAME: str | None = "bcm"
CONN_LED_PIN = None
MQTT_HOST: str = ""
MQTT_PORT: int = 1883
MQTT_PUB_TOPIC: str = "BCM/state"
MQTT_LOG_TOPIC: str = "BCM/log"
MQTT_CTL_TOPIC: str = "BCM/ctl"

# Override any site local values
overrideLocal(__name__, locals())
