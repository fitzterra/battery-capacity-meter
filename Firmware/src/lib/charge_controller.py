"""
Module to control, monitor and keep track of the charge/discharging cycles for
a Li-Ion battery.

The charge and discharge currents, and battery voltage is monitored via one or
more ADS1115_ ADC modules.

The charging and discharging is managed by a TP4056_ BMS, for which the input
and output is switched from digital IO pins on the MCU (`Wemos S2 Mini`_ in this
case), via some MOSFETs.

Required external libs:
    * ads1x15_ - Library forked from Robert Hammelrath's ads1x15 lib for
      MicroPython

.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _TP4056: https://components101.com/modules/tp4056a-li-ion-battery-chargingdischarging-module
.. _Wemos S2 Mini: https://www.wemos.cc/en/latest/s2/s2_mini.html
.. _ads1x15: http://gitlab.gaul.za/tomc/micropython-ads1x15
"""

from collections import OrderedDict
from lib import ulogging as logger
from config import BatteryControllerCFG, B0, B1, B2, B3

ADC_ADDRS = [
    0x48,  # ADDR connected to Ground - default via 10k pulldown
    0x49,  # ADDR connected to VDD
    0x4A,  # ADDR connected to SDA
    0x4B,  # ADDR connected to SCL
]
"""Possible I²C addresses for ADS1115 modules"""


class ChargeControl:
    """
    Discharge/Charge controller.

    This module currently specifically requires one or more ADS1115_ Analog to
    Digital Converter modules. These modules consist of 4 ADC channels
    accessible over an I²C interface.

    Each module can have one of four I²C addresses as defined in the
    `ADC_ADDRS` constant. The address is set by connecting the ``ADDR`` pin
    to various other inputs as specified in the datasheet_.

    An instance of this class can be configured to asynchronously read one or
    more ADC channel values from one or more ADS1115_ modules at a given read
    interval.

    Channels are identified by their address and channel number and written as
    ``"addr:chan"``, for example ``"0x48:2"`` is the ``A2`` ADC input on the
    module with I²C address ``0x48``. The address can also be given in decimal:
    ``"72:2"`` is the same as ``"0x48:2"``

    This class allows each channel to be configured in any of these modes:

    * Voltage monitor
    * Current monitor
    * Charge monitor

    The configuration is specified as part of the channel identifier as
    described below.

    Voltage Monitor
    ^^^^^^^^^^^^^^^

    This is the default config for a channel when only the address and channel
    is used to specify the channel.

    **Example**: ``"73:0"`` or ``"0x49:3"``

    The voltage value will be read and tracked as is. This value is stored and
    tracked as **millivolt** (``mV``)

    Current Monitor
    ^^^^^^^^^^^^^^^

    To monitor a channel for current flow, it  is assumed that the *voltage*
    now being monitored is across a known and accurate shunt resistor.

    Knowing the resistor value, Ohm's law can then be used to convert the
    voltage value to a current value.

    For this type of channel configuration, the resistor value must also be
    supplied as a 3rd value to the channel identifier.

    **Example**: ``"0x48:0:5"`` defines channel ``A0`` on the ADC with address
    ``0x48`` to be a current monitor across a 5Ω resistor.

    Each reading will use Ohm's Law to convert the voltage to current for the
    given resistor value. The value is stored and tracked as **milliamp**
    (``mA``)

    Charge Monitor
    ^^^^^^^^^^^^^^

    This can be used to monitor the amount of charge flowing past a point in
    the circuit. This is useful to monitor battery charging, discharging,
    power usage, etc.

    The electrical setup is exactly as for a **Current Monitor** described
    above where the voltage the ADC monitors is across a known and accurate
    resistor.

    Charge is measured in Coulomb_, and 1C is the electric charge delivered by
    1 ampere of current flowing in 1 second past a point in the circuit.

    If we take a *current* measurement ever second, and then make an assumption
    that this current value was flowing for the full past second, we
    effectively measure **charge**. By accumulating these charge measurements,
    we can then convert the total charge to Amp-hours or Watt-hours, for example.

    In an asyncio application one can not guarantee an accuracy of making
    measurements ever second, on the second. This, along with the fact that
    assuming a current value read has been stable for the last second, does not
    make for a very accurate design, we will improve things as follows:

    * Take more than one current measurement per second, thus increasing the
      accuracy of current flow per period. **NOTE**: This is currently set by
      the default `sample_period` for all measurements for all channels and
      can not be set per channel (yet?).
    * Keep track of the time between measurements, thus not having to rely on
      a dead-accurate-per-period measurement time.
    * Calculate the charge for that period as a portion of a second,
    * Accumulate these charge portions to get the total charge amount for as
      long as we measure it.

    To configure a channel as a **Charge** monitor, we use the same channel
    definition as for a **Current** monitor above, but add an additional ``c``
    to indicate we want to monitor charge on this channel.

    **Example**: ``"73:1:5:c"`` defines channel ``A1`` at ADC address ``73`` to
    be a charge monitor using a 5Ω resistor for calculating the charge current.

    Note that for the other two channel types the value stored for the
    channel will be the last instantaneous value read, while for this channel
    type the value stored is a continuously growing accumulated charge value.
    The value is stored and tracked as **millicoulomb** (``mC``)

    In addition to the charge value stored, the total measurement period in
    seconds are also stored. This allows the charge value to be converted to
    **milliAmpHours** (``mAh``) by the appropriate method call.

    The `reset` method should be used to reset the value to start a new
    charge monitor session.

    .. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
    .. _datasheet: https://www.ti.com/lit/gpn/ads1115
    .. _Coulomb: https://en.wikipedia.org/wiki/Coulomb
    """

    def __init__(self, i2c: object):
        """
        Class initialisation.

        Args:
            i2c: An instance of an I2C object to communicate with the ADC
                modules.
        """
        self._i2c = i2c
        self._adcs = []
        """List of addresses for for all found ADC modules on the I²C bus"""

        self._bat_ctrl = OrderedDict()
        """Dictionary of available battery controllers."""

        self._findADCs()

        # Add the know controller configs by default
        for bat in [B0, B1, B2, B3]:
            self.addCtlConfig(bat)

    def _findADCs(self) -> None:
        """
        Searches the I²C bus for all available ADC modules.

        The list of available ADC module addresses are in the `ADC_ADDRS`
        constant.

        Side Effect:
            Adds any found addresses to the `_adcs` instance variable.

        Returns:
            None
        """
        # Scan the bus looking for ADS1115's
        logger.info("%s scanning I²C bus for ADC modules...", self.__class__.__name__)

        for addy in self._i2c.scan():
            if addy in ADC_ADDRS:
                logger.info("   Found ADC at address: %s, ", addy)
                self._adcs.append(addy)

    def addCtlConfig(self, cfg: BatteryControllerCFG):
        """
        Adds a battery controller config to the controller.

        If the I²C addresses for any of the `cfg.ch_mon` definitions have not been
        detected on the I²C bus, and error will be logged, and this config will
        not be added.

        If controller name already exists in `_bat_ctrl`, an error will be
        logged and the config will not be added.

        Args:
            cfg: An instance created from a `BatteryControllerCFG`
        """
        _me = f"{self.__class__.__name__}.addCtlConfig"

        # Check if the ADC address is available
        for mon in ["ch_mon", "dch_mon", "v_mon"]:
            addr = getattr(cfg, mon).adc.addr
            if not addr in self._adcs:
                logger.error(
                    "%s: Unable to add controller %s. "
                    "ADC address '%s' for '%s' monitor not available on I²C bus.",
                    _me,
                    cfg.name,
                    addr,
                    mon,
                )
                return

        if cfg.name in self._bat_ctrl:
            logger.error(
                "%s: Battery controller config with id `%s` already exists.",
                _me,
                cfg.name,
            )
            return

        self._bat_ctrl[cfg.name] = cfg

        logger.info("%s: Battery config for %s added", _me, cfg.name)

    def ctlNames(self) -> list:
        """
        Returns a list of available controllers as was added via
        `addCtlConfig`.

        The list will contain the `name` attributes from the
        `BatteryControllerCFG` structures that we can control.

        Returns:
            List of controller names.
        """
        return self._bat_ctrl.keys()


def _setupI2C():
    # pylint: disable=import-outside-toplevel
    from machine import Pin, SoftI2C as I2C
    from config import PIN_SDA, PIN_SCL, I2C_INT_PULLUP, I2C_FREQ

    scl_pin = Pin(PIN_SCL, pull=Pin.PULL_UP if I2C_INT_PULLUP else None)
    sda_pin = Pin(PIN_SDA, pull=Pin.PULL_UP if I2C_INT_PULLUP else None)
    i2c = I2C(scl=scl_pin, sda=sda_pin, freq=I2C_FREQ)

    return i2c
