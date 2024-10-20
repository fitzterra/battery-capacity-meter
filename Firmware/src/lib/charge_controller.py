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
import uasyncio as asyncio
from lib import ulogging as logger
from lib.ads1x15 import ADS1115
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

    # This is the gain to set for the builtin PGA. We will be measuring Lithium
    # cells, so we can go up to 4.2V, which means we need to use the larges Full
    # Scale Reading (FSR) which is ±6.144V or a granularity of 187.5µV per value.
    # The ads1x15 lib uses a gain mapping where the first entry (0) is the one we
    # need for the gain we require.
    ADC_GAIN = 0
    """Gain setting for small ADC values. See code for more details."""

    # Set the sampling rate. This is an index into the rates map of the ads1x15
    # module and sets the rate at which the ADS1115 will do the AD conversions. See
    # the datasheet for more, but a rate of 0 uses the slowest, but more accurate,
    # sampling rate of 8 samples per sec (over 500ms to sample all 4 channels),
    # while the max rate of 7 samples at 860 samples per sec (±19ms to sample all
    # four channels, but less accurate). The default rate of 4 does 128 samples per
    # sec and takes about 50ms for a 4 channels.
    ADC_RATE = 4
    """Default ADC conversion rate index. See code for more info."""

    def __init__(
        self, i2c: object, sample_period: int = 300, start_tracker: bool = True
    ):
        """
        Class initialisation.

        Args:
            i2c: An instance of an I2C object to communicate with the ADC
                modules.
            sample_period: The delay in milliseconds between sampling all
                defined ADC monitor channels.
            start_tracker: If True, `track()` will automatically be started as
                an asyncio task and will start to run as soon as the asyncio
                loop is started.
        """
        self._i2c = i2c
        self._adcs = []
        """List of addresses for for all found ADC modules on the I²C bus"""

        self._sample_period = sample_period
        """Set from `sample_period` in `__init__`."""

        self._bat_ctrl = OrderedDict()
        """Dictionary of available battery controllers."""

        self._findADCs()

        # Add the know controller configs by default
        for bat in [B0, B1, B2, B3]:
            self.addCtlConfig(bat)

        # Do we start the tracker?
        if start_tracker:
            logger.info(
                "%s: Will start tracker as soon as asyncIO loop starts.",
                self.__class__.__name__,
            )
            asyncio.get_event_loop().create_task(self.track())

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

        When adding a new battery controller, both charging and discharging
        controls will be turned off, and all monitor values reset.

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

        logger.info("%s: Battery config for %s added", _me, cfg.name)

        # Now reset everything
        self._bat_ctrl[cfg.name] = cfg
        self.charge(cfg.name, 0)
        self.discharge(cfg.name, 0)
        self.reset(cfg.name)

    async def track(self):
        """
        Coro to continuously track ADC inputs.

        This needs to be started as an asyncio task and it will a continuously
        loop to do the following:

        * For every available battery controller in `_bat_ctrl`:
            * If currently charging, update the charge monitor with an ADC
              reading for the given ADC module and channel
            * If currently discharging, update the discharge monitor with an
              ADC reading for the given ADC module and channel
            * Update the battery/output monitor via it's designated ADC input
        * Do an asyncio sleep for `_sample_period` milliseconds and repeat the
          loop.
        """
        # If we have no channel definitions we exit
        if not self._bat_ctrl:
            logger.error(
                "%s.track: No battery controller definitions found. Not starting tracker coro.",
                self.__class__.__name__,
            )
            return

        logger.info("%s.track: Starting tracker coro....", self.__class__.__name__)

        # Instantiate an ADS1115 instance. We will be updating the address for
        # each channel we read, so the address we use here does not matter too
        # much.
        adc = ADS1115(self._i2c, ADC_ADDRS[0], self.ADC_GAIN)

        # Just keep tracking ....
        while True:
            # Sleep a bit
            await asyncio.sleep_ms(self._sample_period)

            # Cycle through all controllers
            for ctl in self._bat_ctrl.values():

                # If we are charging, we read the charge monitor
                if ctl.pin_ch.value():
                    # First set the address based on the channel def
                    adc.address = ctl.ch_mon.adc.addr
                    # Read the channel ADC value, converted as mV value
                    ctl.ch_mon.mon.v = adc.raw_to_v(
                        await adc.read_async(
                            rate=self.ADC_RATE, channel1=ctl.ch_mon.adc.chan
                        ),
                        mV=True,
                    )
                    logger.debug(
                        "%s.track: %s - update charge monitor: %s",
                        self.__class__.__name__,
                        ctl.name,
                        ctl.ch_mon.mon,
                    )

                # If we are discharging, we read the discharge monitor
                if ctl.pin_dch.value():
                    # First set the address based on the channel def
                    adc.address = ctl.dch_mon.adc.addr
                    # Read the channel ADC value, converted as mV value
                    ctl.dch_mon.mon.v = adc.raw_to_v(
                        await adc.read_async(
                            rate=self.ADC_RATE, channel1=ctl.dch_mon.adc.chan
                        ),
                        mV=True,
                    )
                    logger.debug(
                        "%s.track: %s - update discharge monitor: %s",
                        self.__class__.__name__,
                        ctl.name,
                        ctl.dch_mon.mon,
                    )

                # Always read the battery/output voltage. First set the address
                # based on the channel def
                adc.address = ctl.v_mon.adc.addr
                # Read the channel ADC value, converted as mV value
                ctl.v_mon.mon.v = adc.raw_to_v(
                    await adc.read_async(
                        rate=self.ADC_RATE, channel1=ctl.v_mon.adc.chan
                    ),
                    mV=True,
                )
                logger.debug(
                    "%s.track: %s - update battery/output voltage monitor: %s",
                    self.__class__.__name__,
                    ctl.name,
                    ctl.v_mon.mon,
                )

    def ctlNames(self) -> list:
        """
        Returns a list of available controllers as was added via
        `addCtlConfig`.

        The list will contain the `name` attributes from the
        `BatteryControllerCFG` structures that we can control.

        Returns:
            List of controller names.
        """
        return list(self._bat_ctrl.keys())

    def charge(self, bc_name: str, state: bool | None = None) -> bool:
        """
        Controls or returns the current charge state for the given battery
        controller.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Args:
            bc_name: The Battery Controller name. This should be one of the
                names as returned in the list from calling `ctlNames`
            state: Controls either switching the controller on (True or 1), off
                (False or 0), toggle current state ('t') or if None, just
                returns the current state.

        Returns;
            1 if the controller state is currently charging, or 0 if not.
        """
        ctl = self._bat_ctrl.get(bc_name)
        if ctl is None:
            logger.error(
                "%s.charge: Controller with name '%s' does not exist.",
                self.__class__.__name__,
                bc_name,
            )
            return None

        if state == "t":
            # Toggle current state
            ctl.pin_ch.value(not ctl.pin_ch.value())
            act = "toggled to"
        elif state in (True, False):
            ctl.pin_ch.value(state)
            act = "set to"
        elif state is None:
            act = "reported as"
        else:
            logger.error(
                "%s.charge: Invalid state argument: '%s'",
                self.__class__.__name__,
                state,
            )
            return None

        state = ctl.pin_ch.value()

        logger.info(
            "%s.charge: Charge State for %s %s %s",
            self.__class__.__name__,
            bc_name,
            act,
            "On" if state else "Off",
        )

        return state

    def discharge(self, bc_name: str, state: bool | None = None) -> bool:
        """
        Controls or returns the current discharge state for the given battery
        controller.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Args:
            bc_name: The Battery Controller name. This should be one of the
                names as returned in the list from calling `ctlNames`
            state: Controls either switching the controller on (True or 1), off
                (False or 0), toggle current state ('t') or if None, just
                returns the current state.

        Returns;
            1 if the controller state is currently discharging, or 0 if not.
        """
        ctl = self._bat_ctrl.get(bc_name)
        if ctl is None:
            logger.error(
                "%s.discharge: Controller with name '%s' does not exist.",
                self.__class__.__name__,
                bc_name,
            )
            return None

        if state == "t":
            # Toggle current state
            ctl.pin_dch.value(not ctl.pin_dch.value())
            act = "toggled to"
        elif state in (True, False):
            ctl.pin_dch.value(state)
            act = "set to"
        elif state is None:
            act = "reported as"
        else:
            logger.error(
                "%s.discharge: Invalid state argument: '%s'",
                self.__class__.__name__,
                state,
            )
            return None

        state = ctl.pin_dch.value()

        logger.info(
            "%s.discharge: Discharge State for %s %s %s",
            self.__class__.__name__,
            bc_name,
            act,
            "On" if state else "Off",
        )

        return state

    def state(self, bc_name: str) -> dict:
        """
        Returns the current state for a battery controller.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Args:
            bc_name: The Battery Controller name. This should be one of the
                names as returned in the list from calling `ctlNames`

        Returns;
            If any args errors, an error is logged and None is returned, else a
            dictionary as:

            .. python::

                {
                    'ch_s': bool,  # True if currently charging, False otherwise
                    'dch_s': bool, # True if currently discharging, False otherwise
                    'bat': bool,   # True if not dis/charging and a battery is present
                    'bat_v': float,# Battery or output voltage value in mV
                    'ch': float    # Last charge value measured in mAh
                    'ch_t': int    # Last charge period in seconds
                    'dch': float   # Last discharge value measured in mAh
                    'dch_t': int   # Last discharge period in seconds
                }
        """
        ctl = self._bat_ctrl.get(bc_name)
        if ctl is None:
            logger.error(
                "%s.state: Controller with name '%s' does not exist.",
                self.__class__.__name__,
                bc_name,
            )
            return None

        logger.debug(
            "%s.state: Getting state for %s ...", self.__class__.__name__, bc_name
        )

        ch_s = ctl.pin_ch.value()
        dch_s = ctl.pin_dch.value()
        bat_v = ctl.v_mon.mon.v
        # Definition for battery present is if we are not charging or
        # discharging, and the battery voltage read is greater than 2600mV
        bat = bat_v > 2600 and not (ch_s or dch_s)

        state = {
            "ch_s": ch_s,
            "dch_s": dch_s,
            "bat_v": bat_v,
            "bat": bat,
            "ch": ctl.ch_mon.mon.mAh,
            "ch_t": ctl.ch_mon.mon.tot_time,
            "dch": ctl.ch_mon.mon.mAh,
            "dch_t": ctl.ch_mon.mon.tot_time,
        }

        return state

    def reset(self, bc_name: str, monitors: list | None = None) -> None:
        """
        Resets all or some specific monitors for a given charge controller.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Args:
            bc_name: The Battery Controller name. This should be one of the
                names as returned in the list from calling `ctlNames`
            monitors: A list of specific monitors to reset, or None to reset
                all. Monitors are the various `ChannelMonitor` fields named
                as `ch_mon`, `dch_mon` and `v_mon` in the
                `BatteryControllerCFG` definition.
        """
        ctl = self._bat_ctrl.get(bc_name)
        if ctl is None:
            logger.error(
                "%s.reset: Controller with name '%s' does not exist.",
                self.__class__.__name__,
                bc_name,
            )
            return

        if not (isinstance(monitors, (list, tuple)) or monitors is None):
            logger.error(
                "%s.reset: Invalid value for monitors arg: %s",
                self.__class__.__name__,
                monitors,
            )
            return

        logger.info(
            "%s.reset: Resetting monitor(s) for %s...", self.__class__.__name__, bc_name
        )

        # Instead of validating each of the monitor field names in monitors, we
        # will only reset anything that is valid in there, and ignore anything
        # invalid. This should be slightly better on memory usage
        for mon in ["ch_mon", "dch_mon", "v_mon"]:
            if monitors is not None and mon not in monitors:
                logger.info("   Ignoring %s ...", mon)
                continue
            getattr(ctl, mon).mon.reset()
            logger.info("   Monitor %s has been reset..", mon)
