"""
Module to asynchronously read and keep track of a number of ADC inputs into one
or more ADS1115_ ADC modules.

Required external libs:
    * ads1x15_ - Library forked from Robert Hammelrath's ads1x15 lib for
      MicroPython

.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _ads1x15: http://gitlab.gaul.za/tomc/micropython-ads1x15
"""

import utime as time
import uasyncio as asyncio
from micropython import const
from lib.utils import NullLogger
from lib.ads1x15 import ADS1115

ADS1115_ADDR = [
    0x48,  # ADDR connected to Ground - default via 10k pulldown
    0x49,  # ADDR connected to VDD
    0x4A,  # ADDR connected to SDA
    0x4B,  # ADDR connected to SCL
]
"""Possible I²C addresses for an ADS1115 module"""


class ADCTracker:
    """
    Asynchronous ADC input value reader and tracker.

    This module currently specifically requires one or more ADS1115_ Analog to
    Digital Converter modules. These modules consist of 4 ADC channels
    accessible over an I²C interface.

    Each module can have one of four I²C addresses as defined in the
    `ADS1115_ADDR` constant. The address is set by connecting the ``ADDR`` pin
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

    T_VOLTAGE = const(0)
    """Voltage monitor channel type"""
    T_CURRENT = const(1)
    """Current monitor channel type"""
    T_CHARGE = const(2)
    """Charge monitor channel type"""

    UNITS = ["mV", "mA", "mC"]
    """
    Units for values stored in the ``"val"`` element of channel definitions.
    The ``T_???`` constants for the channel types can be used as index into the
    units list to get the units corresponding to the type.
    """

    # This is the gain to set for the builtin PGA. We will be measuring Lithium
    # cells, so we can go up to 4.2V, which means we need to use the larges Full
    # Scale Reading (FSR) which is ±6.144V or a granularity of 187.5µV per value.
    # The ads1x15 lib uses a gain mapping where the first entry (0) is the one we
    # need for the gain we require.
    ADC_GAIN = 0
    """Gain setting for small ADC values. See code for more details."""

    # Set the sampling rate. This is an index into the rates map of the ads1x15
    # module and set the rate at which the ADS1115 will do the AD conversions. See
    # the datasheet for more, but a rate of 0 uses the slowest, but more accurate,
    # sampling rate of 8 samples per sec (over 500ms to sample all 4 channels),
    # while the max rate of 7 samples at 860 samples per sec (±19ms to sample all
    # four channels, but less accurate). The default rate of 4 does 128 samples per
    # sec and takes about 50ms for a 4 channels.
    ADC_RATE = 4
    """Default ADC conversion rate index. See code for more info."""

    def __init__(
        self, i2c: object, cfg: list, sample_period: int = 300, logger: object = None
    ) -> None:
        """
        Instance init.

        The ``cfg`` argument is a list of channel config definitions the ADC
        tracker should monitor. Each definition is a string in the following
        format:

            ``addr:chan[:R[:c]]``

        where:

        * ``addr`` is the ADS1115 module's I²C address either in hex (``0x48``)
           or decimal (``73``) format. See `ADS1115_ADDR` for valid addresses.
        * ``chan`` is the channel number to set up on this module. Only values
           from 0 - 3 are allowed and corresponds to the ``A0`` to ``A3`` ADC
           input channels on the module
        * ``R`` is a resistor value in ohm is this is a current monitor
          channel. See the class documentation of the different channel types.
        * ``c`` is appended to make this a charge monitor channel. See the
          class documentation of the different channel types.

        The index in this list for each channel definition is the index to be
        used to retrieve the last tracked value using the `getVal()` method.

        Args:
            i2c: An instance for an I²C object used for I²C communications.
            cfg: The channel config definitions list.
            sample_period: The delay between sampling all defined channels in
                milliseconds.
            logger: Optional logger instance can be supplied for message
                logging.

        Raises:
            ValueError:  If any input args are invalid. This includes malformed
                         channel definitions, as well as ADS1115 addresses
                         supplied for which the device is not available on the
                         I²C bus.
        """
        # If a logger is provided, we set that as the logger, else we use a
        # null logger.
        self._logger = logger if logger else NullLogger()
        self._i2c = i2c
        self._sample_period = sample_period
        # Will be a list of found ADC addresses on the I²C bus
        self._adcs = []

        # Scan for all ADS1115 devices.
        self._findDevices()

        # Parse the supplied config
        self._ch_defs = {}
        self._parseCFG(cfg)

    def _parseCFG(self, cfg: list) -> None:
        """
        Parses the supplied channel config.

        Each entry in this list will be parsed to be of the format
        ``addr:chan[:res[:c]]`` (see `ADCTracker` base docs), and if valid,
        will add an entry to the ``self._ch_defs`` dictionary for this channel.

        The key added to the dictionary will be the index for it's definition
        in the ``cfg`` list, and the value will be a dictionary as follows:

        .. python::

            {
                'addr': int,  # The I²C address for the ADC device
                'ch': int,    # The channel number on this device
                'res': int,   # A resistor value if this is a current or charge type
                'type': str,  # One of the ``T_TYPE*`` class level constants
                'val': str|float|int, # Last value sampled
                'l_tick': int # Only for Charge monitor channels - records the last
                              # time the channel was read
                '_raw_v': int,   # For current type channels only, this will be
                                 # the raw mV value read from the ADC.
                '_raw_c': float, # For charge type channels only, this will be
                                 # calculated current value from the raw mV and
                                 # resistor values.
            }

        Side Effects:
            `_ch_defs`: Fills this channel definition dictionary

        Raises:
            ValueError: For any invalid channel definitions

        Returns:
            None
        """
        # Lots happening here so we have a number of different branches, so
        # @pylint: disable=too-many-branches

        self._logger.info("Parsing ADCTracker channel configs...")

        for idx, chan in enumerate(cfg):
            # Split it into parts
            parts = chan.split(":")

            # It must be 2, 3 or 4 components
            if len(parts) not in [2, 3, 4]:
                raise ValueError(f"Invalid channel definition: {chan}")

            # Pop the address and try convert it to int. We set the base 0 to
            # make Python auto distinguish between decimal and hex (starting
            # with 0x) formats.
            try:
                addr = int(parts.pop(0), 0)
            except ValueError as exc:
                raise ValueError(
                    f"Not a valid address for channel definition: {chan}"
                ) from exc

            if addr not in self._adcs:
                raise ValueError(
                    f"ADS1115 address {addr} not connected to bus for channel def {chan}"
                )

            # Now the channel
            try:
                ch = int(parts.pop(0), 0)
            except ValueError as exc:
                raise ValueError(
                    f"Not a valid channel for channel definition: {chan}"
                ) from exc

            if not 0 <= ch <= 3:
                raise ValueError(
                    f"ADS1115 channel must be between 0 and 3. Invalid channel def {chan}"
                )

            # The resistor value if this is a current or charge type channel
            if parts:
                try:
                    res = int(parts.pop(0), 0)
                except ValueError as exc:
                    raise ValueError(
                        f"Not a valid resistor value for channel definition: {chan}"
                    ) from exc

                # Is this a Charge monitor channel?
                if parts:
                    if parts[0] != "c":
                        raise ValueError(
                            f"Only a 'c' allowed to indicate a charge monitor channel. Invalid channel def {chan}"
                        )
                    charge_t = True
            else:
                res = None
                charge_t = False

            self._ch_defs[idx] = {
                "addr": addr,
                "ch": ch,
                "res": res,
                "type": (
                    self.T_VOLTAGE
                    if res is None
                    else (self.T_CURRENT if not charge_t else self.T_CHARGE)
                ),
                "val": 0,
            }
            # Add the raw keys for current and charge type channels, and the
            # l_tick for charge types
            if self._ch_defs[idx]["type"] in (self.T_CURRENT, self.T_CHARGE):
                self._ch_defs[idx]["_raw_v"] = 0
                # Add the raw current and l_tick key for Charge type channels
                if self._ch_defs[idx]["type"] == self.T_CHARGE:
                    self._ch_defs[idx]["l_tick"] = None
                    self._ch_defs[idx]["_raw_c"] = 0.0

            self._logger.debug(
                "Adding channel config for: %s: %s", chan, self._ch_defs[idx]
            )

    def _findDevices(self) -> None:
        """
        Scans the I²c bus for ADS1115 devices.

        Side Effects:
            `_adcs`: Fills this list with any ADS1115 addresses found on the I²C bus

        Returns:
            None
        """
        # Scan the bus looking for ADS1115's
        self._logger.info("ADCTracker scanning I²C bus...")

        for addy in self._i2c.scan():
            if addy in ADS1115_ADDR:
                self._logger.info("   Found ADC at address: %s, ", addy)
                self._adcs.append(addy)

    async def track(self):
        """
        Coro to continuously track ADC inputs.

        This coro will cycle through all defined channels and, read the ADC
        values and convert and save them in the ``self._chan_def[*]['val']``
        variable.
        """
        # If we have no channel definitions we exit
        if not self._ch_defs:
            self._logger.error(
                "No channel definitions found. Not starting tracker coro."
            )
            return

        # Instantiate an ADS1115 instance. We will be updating the address for
        # each channel we read, so the address we use here does not matter too
        # much.
        adc = ADS1115(self._i2c, self._ch_defs[0]["addr"], self.ADC_GAIN)

        # Just keep tracking ....
        while True:
            # Sleep a bit
            await asyncio.sleep_ms(self._sample_period)

            for ch in self._ch_defs.values():
                # For Charge type channels, we need to first set the first tick
                # time if it is not set, or else we can not calculate the
                # current period. Only Charge channels will have an 'l_tick'
                # key, and it will be None on first set.
                if ch.get("l_tick", False) is None:
                    ch["l_tick"] = time.ticks_ms()
                    ch["val"] = 0
                    continue

                # First set the address based on the channel def
                adc.address = ch["addr"]
                # Read the channel ADC value, converted as mV value
                val = adc.raw_to_v(
                    await adc.read_async(rate=self.ADC_RATE, channel1=ch["ch"]), mV=True
                )
                if ch["type"] == self.T_VOLTAGE:
                    # Save as mV value and continue on to next channel
                    ch["val"] = val
                    continue

                # For the other channel types we need to first save the raw
                # voltage and then calculate the current using Ohm's Law.
                ch["_raw_v"] = val
                # Divide the voltage by the resistor value to get the milliamp
                # current
                val = val / ch["res"]

                if ch["type"] == self.T_CURRENT:
                    # Save as mA value and continue on to next channel
                    ch["val"] = val
                    continue

                # For the Charge type channel we need to save the raw current
                # value and then calculate the time since the last conversion
                ch["_raw_c"] = val
                now = time.ticks_ms()
                portion = time.ticks_diff(now, ch["l_tick"])
                # Save the last tick time
                ch["l_tick"] = now

                # The millicoulomb value is the portion of 1000 milliSecs that
                # we assume this milliamps had flown for - accumulated:
                #   portion (ms)
                # ---------------- X val (mA)
                #    1000 ms
                ch["val"] += (portion * val) // 1000

    def getVal(
        self, idx: int, unit: bool = False, intermediate: bool = False
    ) -> str | float | int | list:
        """
        Returns the value for the given channel.

        In order to debug or for additional metrics, the intermediate voltage
        (current and charge type channels) value read from the ADC (as a mV
        value), and also the calculated current (charge type channel only, as
        mA floating value) can be returned along with the actual channel final
        value.

        To do so, set the `intermediate` arg to `True` and the result will be a
        list in the form::

            [current|charge value, ADC voltage mV(, current mA)]

        The 3rd element will only be included for charge type channels.

        In addition, if the `unit` arg is also True, these intermediate values
        will be returned as strings including their units.

        Args:
            idx: The index into the channel list for the value to return
            unit: If True, the value and corresponding unit for that channel
                type will be returned as a string. If False (the default) only
                the value will be returned either as a float, or integer.
            intermediate: If True, also returned intermediate values for this
                channel as described above.

        Returns:
            The channel value in the units for the channel type.

        Raises:
            IndexError: If idx is invalid.
        """
        # First the simplest form
        if not (unit or intermediate):
            return self._ch_defs[idx]["val"]

        # If intermediate is False, then we can only get here if unit is True.
        # In this case still only return the final value, but formatted with
        # the unit
        if not intermediate:
            return (
                f"{self._ch_defs[idx]['val']}{self.UNITS[self._ch_defs[idx]['type']]}"
            )

        # Intermediate is True, so build the list with the values needed
        res = [self._ch_defs[idx]["val"], self._ch_defs[idx]["_raw_v"]]
        if "_raw_c" in self._ch_defs[idx]:
            res.append(self._ch_defs[idx]["_raw_c"])

        if not unit:
            # No units, so we can return the values as is
            return res

        # We need to add the units
        for i, v in enumerate(res):
            # The first element needs to get the unit for the channel type
            if i == 0:
                res[i] = f"{v}{self.UNITS[self._ch_defs[idx]['type']]}"
            elif i == 1:
                # Second element is always mV
                res[i] = f"{v}mV"
            else:
                # Third element if present will always be current
                res[i] = f"{v}mA"
        return res

    def reset(self, idx: int | list) -> None:
        """
        Resets the accumulated charge value for one or more charge type
        channels.

        If a non-charge type channel reset is requested, or the index is
        invalid, an error is logged and the reset is ignored.

        A single channel can be reset by passing it's index in the ``idx`` arg.

        Multiple channels may be reset by passing a list of their indexes in
        the ``idx`` arg.

        All charge type channels may be reset by passing ``-1`` as the ``idx``
        arg.

        Args:
            idx: The index for the channel(s) to reset as described above.

        """
        # Reset all T_CHARGE type channels?
        if idx == -1:
            for i, ch in self._ch_defs.items():
                if ch["type"] == self.T_CHARGE:
                    ch["val"] = 0
                    ch["l_tick"] = None
                    self._logger.debug(
                        "Resetting channel %s @ %s", i, f"{ch['addr']}:{ch['ch']}"
                    )
            return

        # Make idx a list if it is not one already, in order to only have one
        # way of resetting one or more channels
        if not isinstance(idx, list):
            idx = [idx]

        for i in idx:
            if not (isinstance(i, int) and i in self._ch_defs):
                self._logger.error(
                    "Invalid channel index to reset: %s.  Ignoring reset...", i
                )
                continue

            ch = self._ch_defs[i]
            if ch["type"] == self.T_CHARGE:
                ch["val"] = 0
                ch["l_tick"] = None
                self._logger.debug(
                    "Resetting channel %s @ %s", i, f"{ch['addr']}:{ch['ch']}"
                )
            else:
                self._logger.error(
                    "Channel at index %s is not a charge type channel.  Ignoring reset...",
                    i,
                )
