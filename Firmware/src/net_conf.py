"""
Network and related configs module.

This module contains the required configs for the WiFi and MQTT access
credentials.

It is used by various other modules that needs access to this config.

Many of these values are simply default values for config and documentation
purposes, and things like passwords or sensitive details are not stored in the
code base.

Any sensitive or site local values will be stored in a local site config file
and be managed as described in the `sitelocal_conf` module.

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
"""

from sitelocal_conf import overrideLocal

SSID: str = ""
PASS: str = ""
HOSTNAME: str | None = "bcm"
MQTT_HOST: str = ""
MQTT_PORT: int = 1883

# Override any site local values
overrideLocal(__name__, locals())
