"""
Network and related configs module.

This module contains the required configs for the WiFi and MQTT access
credentials as used by the `state_broadcast` and `net_conn` modules.

It is used by various other modules that needs access to this config.

Many of these values are simply default values for config and documentation
purposes, and things like passwords or sensitive details are not stored in the
codebase.

Any sensitive or site local values will be stored in a local site config file
and will be managed as described in the `sitelocal_conf` module.

Attributes:
    SSID: The SSID for the AP to connect to. Expects to be overridden from a
        site local config.
    PASS: The password for connecting to the AP. Expects to be overridden from a
        site local config.
    HOSTNAME: The hostname to use on the network. If None, no hostname will be
        set specifically. May be overridden from a site local config.
    MQTT_HOST: The name for the MQTT server to use for MQTT messages. Expects
        to be overridden from a site local config.
    MQTT_PORT: The port on `MQTT_HOST` to connect to. May be overridden from a
        site local config.
    MQTT_PUB_TOPIC: This is the base topic used to publish state messages on.
        `BatteryController.name` will be appended to the topic to make unique
        topics per battery controller name.
    MQTT_CTL_TOPIC: This is the topic to subscribe to for MQTT control messages.
    MQTT_DEBUG: If True, the `mqtt_as` module will print verbose output that
        can be used for debugging.
"""

from sitelocal_conf import overrideLocal

SSID: str = ""
PASS: str = ""
HOSTNAME: str | None = "bcm"
MQTT_HOST: str = ""
MQTT_PORT: int = 1883
MQTT_PUB_TOPIC: str = "BCM/state"
MQTT_CTL_TOPIC: str = "BCM/ctl/#"
MQTT_DEBUG: bool = False

# Override any site local values
overrideLocal(__name__, locals())
