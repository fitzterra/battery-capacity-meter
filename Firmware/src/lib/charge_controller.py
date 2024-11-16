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

from micropython import const
import utime as time
import uasyncio as asyncio
from lib import ulogging as logger
from lib.ads1x15 import ADS1115
from config import BatteryControllerCFG, I2C

ADC_ADDRS = [
    0x48,  # ADDR connected to Ground - default via 10k pulldown
    0x49,  # ADDR connected to VDD
    0x4A,  # ADDR connected to SDA
    0x4B,  # ADDR connected to SCL
]
"""Possible I²C addresses for ADS1115 modules"""


def ewAverage(alpha: float, new: float | int, avg: float | int):
    """
    Function to calculate an Exponentially Weighted Average of a series of data
    points.

    This is useful to smooth out ADC readings over time.

    See WikiPedia_ for in-depth details, but this idea was taken from here_ and
    adapted.

    In order to use this function, ``alpha`` should be calculated and stored
    locally by the caller to be the sample window over which we will be
    averaging. This is basically the inverse of window size:

        alpha = 1 / samples

    Args:
        alpha: See above
        new: The new sample just read
        avg: The current running average. For the first sample, the same value
            may be used for both ``new`` and ``avg``

    Returns:
        The new filtered average value

    .. _WikiPedia: https://en.wikipedia.org/wiki/Exponential_smoothing
    .. _here: https://forums.raspberrypi.com/viewtopic.php?t=69797#p508217
    """
    # In case the more simple description in the link above gets lost, here it
    # is with some changes to fit this situation:
    #
    # An exponentially weighted average is an average of all the previous data
    # points, but weighted so that the most recent values contribute the most,
    # and the contributions of older and older data values decay exponentially.
    #
    # Consider the simplest case where alpha = 1/2. Then the current average is
    # 1/2 of the most recent reading, plus 1/4 of the previous reading, plus
    # 1/8 of the reading before that, plus 1/16 of the reading before that, all
    # the way back to the start. (Notice this adds to 1, so it is a true
    # average.)
    #
    # One of the advantages is that we do not need to retain the individual
    # values. If we multiply the current average by 1/2, we have automatically
    # shifted all the contributions back one place, and then we can add 1/2 of
    # the next reading.
    #
    # This works just as well with other alpha values. (For alpha=1/30, the
    # contribution of the kth term is (1/30)*(29/30)**k, so multiply by 29/30
    # moves them down and we add 1/30 of the next reading.)
    #
    # I do not think it is necessary or beneficial to change the rules at the
    # beginning, except that we may want to use the first reading as a guess at
    # the long-term average if there is no better guess available. If the
    # initial averages are displaced as a result, then just drop the first few
    # outputs.
    #
    # In Python:
    #
    #     N = 30
    #     alpha = 1.0/N  # or: 2.0/(N+1)
    #     average = wind_tally() # or: guess_at_long_term_average()
    #     while True:
    #         count = wind_tally()
    #         average = alpha*count + (1-alpha)*average
    #         print("current = ", count, ", average = ", average)
    #         time.sleep(1)
    #
    # Compared to a simple average of the last N values, the exponentially
    # weighted average is more affected by the recent readings, but less
    # affected by readings suddenly dropping out of the window. So it is
    # arguably both more smooth and faster to respond to genuine trends.

    return alpha * new + (1 - alpha) * avg


class BatteryController:
    """
    Manager and charge monitor for a single battery controller circuit.

    This class currently specifically requires one or more ADS1115_ Analog to
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

    Truth Table
    ^^^^^^^^^^^
    +--------+---------+-------+--------+---------+-------------+----------------+
    | ch_ctl | dch_ctl | v_mon | ch_mon | dch_mon | bat_present | state          |
    +========+=========+=======+========+=========+=============+================+
    |   0    |    0    | <100mV|   X    |    X    |    no       | NO_BAT         |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   0    |    0    |>2000mV|   X    |    X    |    yes      | BAT_INS        |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   0    |    1    | <100mV|   X    |   0mA   |    no       | BAT_YANKED     |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   0    |    1    |>2000mV|   X    | >100mA  |    yes      | DISCHARGING    |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   1    |    0    | >4.0V | <10mA  |    X    | no/charged  | CHARGED/YANKED |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   1    |    0    | <4.2V | >10mA  |    X    | yes/charging| CHARGING       |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   1    |    1    | <3.0V | >400mA |  >300mA | no/dis input| INVALID        |
    +--------+---------+-------+--------+---------+-------------+----------------+
    |   1    |    1    | >3.0V | >600mA |  >600mA | yes/ch+dch  | INVALID        |
    +--------+---------+-------+--------+---------+-------------+----------------+


    Attributes:
        ADC_GAIN: Gain setting for small ADC values. See code for more details.

        ADC_RATE: Default ADC conversion rate index. See code for more info.

        ST_NOADC: One or more of the ADC input addresses are not available on
            the I²C bus. This controller is not available to use in this state.
        ST_NOBAT: No Battery: Not charging or discharging and Voltage monitor
            is at 0V.
        ST_BATINS: Battery Installed: Not charging or discharging and voltage
            monitor > 2.6V.
        ST_CHARGING: Charging: Battery is being charged. Charge is on and
            current flowing.
        ST_DISCHARGING: Discharging: Battery is being discharged. Discharge is
            on and current flow.
        ST_CHARGED: Charging is complete. Charge is on, bat at full voltage and
            no current flow.
        ST_DISCHARGED: Discharging is complete. Voltage dropped to min and
            current stopped when protection kicked in.
        ST_YANKED: The battery was removed while charging or discharging.
        ST_UNKNOWN: The current status is unknown at the moment.

        JUMP_THRESHOLDS: Thresholds set for the different monitors to detect
            large value jumps between readings.

            This is to mostly to detect a battery being yanked (or possibly
            inserted?) while dis/charging, or for any other anomalies that
            could indicate issues:

            - **bat_v**: Battery voltage change threshold in mV
            - **ch_c**: Charge current change threshold in mA
            - **dch_c**: Charge current change threshold in mA

        _i2c: Set from ``i2c`` param to `__init__`

        cfg: Set from ``cfg`` param to `__init__`

        sample_period: Set from ``sample_period`` param to `__init__`

        _alpha: Alpha value for weighted average calculations.

            This value is calculated for the exponentially weighted average we
            calculate for all samples using `ewAverage()`. We calculate this to
            be the average over the number of samples we will take in 1 second:
            ``1 / sample_period``

        state: This will be set to one of the ``ST_???`` status constants
            defined for the class.

        _me: Shortcut to ``self.__class__.__name__`` Used in log messages to
            identify the log source.

        _jump_flags: Keeps track of last battery voltage, charge and discharge
            readings, as well as flags to indicate if there were big jumps in
            these values between readings.

            Each key has a corresponding key in `JUMP_THRESHOLDS` for the
            specific value to track.

            The values are 2-element lists as: ``[last_value, jumped]`` where
            the ``last_value`` element keeps track of the previous value read
            for this metric (None on reset), and the ``jumped`` element being a
            boolean to indicate if a jump was detected.

            The ``last_value`` may also be a negative value (set via `reset()`)
            to start a settlement period during which big jumps are ignored.
            This is normally right after starting or ending a charge/discharge
            cycle if needed.

            These can be reset via the `reset()` method.

        _mon_time: Records the time each monitor run takes.

            This is used to get a view on if there is too much being done per
            monitor loop. This value must be well below `sample_period` to
            ensure there is time to do other things besides monitoring.

        bat_id: An identifier for this battery.

            This can be used to keep track
            of charge cycles and status for a specific battery over time. The
            application may set this ID from a UI or similar when a new battery
            is inserted for this controller. Usually this ID will be available
            on the battery (written, label, etc.). When the controller detects
            that the battery was removed, it will automatically reset this ID
            to None, ready for a new battery.


    .. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
    .. _datasheet: https://www.ti.com/lit/gpn/ads1115
    .. _Coulomb: https://en.wikipedia.org/wiki/Coulomb
    """

    # We do need many instance attributes:
    # @pylint: disable=too-many-instance-attributes

    # This is the gain to set for the builtin PGA. We will be measuring Lithium
    # cells, so we can go up to 4.2V, which means we need to use the larges Full
    # Scale Reading (FSR) which is ±6.144V or a granularity of 187.5µV per value.
    # The ads1x15 lib uses a gain mapping where the first entry (0) is the one we
    # need for the gain we require.
    ADC_GAIN: int = const(0)

    # Set the sampling rate. This is an index into the rates map of the ads1x15
    # module and sets the rate at which the ADS1115 will do the AD conversions. See
    # the datasheet for more, but a rate of 0 uses the slowest, but more accurate,
    # sampling rate of 8 samples per sec (over 500ms to sample all 4 channels),
    # while the max rate of 7 samples at 860 samples per sec (±19ms to sample all
    # four channels, but less accurate). The default rate of 4 does 128 samples per
    # sec and takes about 50ms for a 4 channels.
    ADC_RATE: int = const(4)

    # Different possible states - see class docstring Attributes section
    ST_NOADC: int = const(0)
    ST_NOBAT: int = const(1)
    ST_BATINS: int = const(2)
    ST_CHARGING: int = const(3)
    ST_DISCHARGING: int = const(4)
    ST_CHARGED: int = const(5)
    ST_DISCHARGED: int = const(6)
    ST_YANKED: int = const(7)
    ST_UNKNOWN: int = const(99)

    JUMP_THRESHOLDS = {
        "bat_v": const(100),
        "ch_c": const(100),
        "dch_c": const(100),
    }

    def __init__(
        self,
        i2c: I2C,
        cfg: BatteryControllerCFG,
        sample_period: int = 300,
        start_monitor: bool = True,
    ):
        """
        Instance init.

        Args:
            i2c: An ``I2C`` (or ``SoftI2C``) instance for accessing the ADCs.
            cfg: A `BatteryControllerCFG` instance.
            sample_period: The delay in milliseconds between sampling all
                defined ADC monitor channels. This should be less than 1000ms
            start_monitor: If True, `monitor()` will automatically be started as
                an asyncio task and will start to run as soon as the asyncio
                loop is started.
        """
        self._i2c: I2C = i2c
        self.cfg = cfg
        self.sample_period = sample_period
        self._alpha = 1.0 / (1000 / self.sample_period)
        self.state = None
        self._me = self.__class__.__name__
        self._jump_flags = {
            "bat_v": [None, False],
            "ch_c": [None, False],
            "dch_c": [None, False],
        }
        self._mon_time: int = 0
        self.bat_id: str | None = None

        # Check if all ADCs are available
        self._checkADCs()

        # Do we start the monitor?
        if start_monitor:
            if self.state != self.ST_NOADC:
                logger.info(
                    "%s: Will start monitor for %s as soon as asyncIO loop starts.",
                    self._me,
                    self.cfg.name,
                )
                asyncio.get_event_loop().create_task(self.monitor())
            else:
                logger.error(
                    "%s: Not starting monitor for %s as one or more ADC"
                    "addresses are not on the I²C bus..",
                    self._me,
                    self.cfg.name,
                )

    def _checkADCs(self):
        """
        Checks that the ADCs set up for the various inputs are all available on
        the I²C bus.

        SideEffect:
            Sets `state` to either `ST_NOADC` if at least monitors ADC address
            is not available on the I²C bus, or to `ST_UNKNOWN` if all is good.
        """
        logger.info(
            "%s: Checking all I²C addresses to be valid for %s", self._me, self.cfg.name
        )

        # Filter all available addresses in the I²C bus for only those we know
        # to be ADS1115 addresses
        adcs = [addy for addy in self._i2c.scan() if addy in ADC_ADDRS]

        # Preset status to invalid
        self.state = self.ST_NOADC

        for mon in ["ch_mon", "dch_mon", "v_mon"]:
            addr = getattr(self.cfg, mon).adc.addr
            if not addr in adcs:
                logger.error(
                    "%s: Controller %s disabled due to "
                    "ADC address '%s' for '%s' monitor not available on I²C bus.",
                    self._me,
                    self.cfg.name,
                    addr,
                    mon,
                )
                return

        # Set to unknown state, indicating we are good to go
        self.state = self.ST_UNKNOWN

    def _updateState(self):
        """
        Updates the current state by examining the available inputs and
        controls.

        ToDo: HOW???

        """

        # If we are in ST_YANKED state, we can not allow any auto updates
        # until a reset is done. A reset from ST_YANKED will set the state to
        # ST_UNKNOWN which we can deal with here.
        if self.state == self.ST_YANKED:
            return

        # Get the current charge/discharge control states
        charging = self.cfg.pin_ch.value()
        discharging = self.cfg.pin_dch.value()

        if not (charging or discharging):
            # Not charging or discharging.
            # If the battery/output voltage is > 2000mV we assume a battery
            # is present.
            # A battery at a voltage lower than this we are not interested
            # in since it is probably good for the dump anyway.
            if self.cfg.v_mon.mon.v > 2000:
                # If the previous state was not ST_BATINS, a battery was just
                # inserted now, so we reset the battery ID too
                if self.state != self.ST_BATINS:
                    logger.info(
                        "%s - %s: Seems we just got a battery inserted. Resetting battery ID",
                        self._me,
                        self.cfg.name,
                    )
                    self.bat_id = None
                self.state = self.ST_BATINS
            else:
                self.state = self.ST_NOBAT
            return

        # Must mean we are charging or discharging. Check for a big voltage
        # jump to see if the battery was yanked
        if self._jump_flags["bat_v"][1]:
            logger.error("%s: Detected large voltage jump. Battery yanked!", self._me)
            # First we need to switch dis/charging off
            if charging:
                self.charge(False)
            else:
                self.discharge(False)
            # Then we have to reset the jump flag
            self.reset(["v_jump"])
            # And lastly set the state
            self.state = self.ST_YANKED
            return

        if charging:
            # TODO:
            # For now we simply set charging state. Still need to figure
            # out what it means to be fully charged
            self.state = self.ST_CHARGING
        elif discharging:
            # TODO:
            # For now we simply set discharging state. Still need to figure
            # out what it means to be fully discharged
            self.state = self.ST_DISCHARGING
        else:
            # Default state if nothing else works
            self.state = self.ST_UNKNOWN

    async def monitor(self):
        """
        Async coroutine to continuously monitor the current battery controller
        state.

        This method will read all ADC inputs ± every `sample_period`.

        It will then do the following:

        * Check for any large voltage or current jumps in the various monitors.
            See `JUMP_THRESHOLDS` for more...
        * What else?????
        """
        logger.info("%s: Starting async monitor for: %s", self._me, self.cfg.name)

        # Instantiate an ADS1115 instance. We will be updating the address for
        # each channel we read, so the address we use here does not matter too
        # much.
        adc = ADS1115(self._i2c, ADC_ADDRS[0], self.ADC_GAIN)

        def checkForJump(metric: str, val: int):
            """
            Function to check and set the jump flag for this metric if the new
            value read is outside of the jump threshold set for it.

            Args:
                metric: Any one of "bat_v", "ch_c" or "dch_c"
                val: The voltage or current value just read for this metric.

            Note:
                No validation is done on the args, so: Garbage in, things
                break.
            """
            # Get the threshold value for this metric
            th_val = self.JUMP_THRESHOLDS[metric]
            # Get the jump tracker list for this metric.
            # tracker[0] == the previous value, or None after reset
            # tracker[1] == The flag to be set if a jump is detected
            tracker = self._jump_flags[metric]

            # We also allow a settle period right after switching charging on
            # or off. This is (crudely) done by the setting the ``last_value``
            # for the metric (1st list element) in `_jump_flags` to a negative
            # value.
            # In this case, we will start incrementing this value until we get
            # to zero, at which time it is set to None to simulate a reset.
            # The settle period is thus directly proportional to the
            # `sample_time` since the settle time will be:
            #
            #   (abs(last_value) * sample_period ) + 1
            #
            # The ``+ 1`` takes into account that we go to the reset state
            # (None) which requires one additional sample_period to start
            # working.
            if tracker[0] is not None and tracker[0] < 0:
                tracker[0] += 1
                # Simulate a reset so we can continue as normal.
                if tracker[0] == 0:
                    tracker[0] = None
                return

            # After reset the previous value will be None so we need to take
            # that into account the first time we run this after a reset or on
            # startup.
            # Also, the change may be negative while out threshold value is
            # positive, so we also handle this.
            if tracker[0] is not None and abs(val - tracker[0]) > th_val:
                # Large jump detected, set the flag
                tracker[1] = True
            # Keep track of the last raw value
            tracker[0] = v

        # Just keep monitoring...
        while True:
            # Sleep a bit
            await asyncio.sleep_ms(self.sample_period)

            # Start timer
            t_start = time.ticks_ms()

            # Get the current charge/discharge control states
            charging = self.cfg.pin_ch.value()
            discharging = self.cfg.pin_dch.value()

            # If we are charging, we read the charge monitor
            if charging:
                # First set the address based on the channel def
                adc.address = self.cfg.ch_mon.adc.addr
                # Read the channel ADC value, converted as mV value
                v = adc.raw_to_v(
                    await adc.read_async(
                        rate=self.ADC_RATE, channel1=self.cfg.ch_mon.adc.chan
                    ),
                    mV=True,
                )
                # Filter and then save it as a rounded integer
                self.cfg.ch_mon.mon.v = round(
                    ewAverage(self._alpha, v, self.cfg.ch_mon.mon.v)
                )
                # Check for large current jumps
                checkForJump("ch_c", self.cfg.ch_mon.mon.c)

            # If we are discharging, we read the discharge monitor
            if discharging:
                # First set the address based on the channel def
                adc.address = self.cfg.dch_mon.adc.addr
                # Read the channel ADC value, converted as mV value
                v = adc.raw_to_v(
                    await adc.read_async(
                        rate=self.ADC_RATE, channel1=self.cfg.dch_mon.adc.chan
                    ),
                    mV=True,
                )
                # Filter and then save it as a rounded integer
                self.cfg.dch_mon.mon.v = round(
                    ewAverage(self._alpha, v, self.cfg.dch_mon.mon.v)
                )
                # Check for large current jumps
                checkForJump("dch_c", self.cfg.dch_mon.mon.c)

            # Always read the battery/output voltage. First set the address
            # based on the channel def
            adc.address = self.cfg.v_mon.adc.addr
            # Read the channel ADC value, converted as mV value
            v = adc.raw_to_v(
                await adc.read_async(
                    rate=self.ADC_RATE, channel1=self.cfg.v_mon.adc.chan
                ),
                mV=True,
            )
            # Filter and then save it as a rounded integer
            self.cfg.v_mon.mon.v = round(
                ewAverage(self._alpha, v, self.cfg.v_mon.mon.v)
            )
            # Check for large voltage jumps. Here we use the unaveraged raw
            # voltages, unlike for the current values which are the averaged
            # values.
            checkForJump("bat_v", v)

            # Update status
            self._updateState()

            # Update monitor time
            self._mon_time = time.ticks_diff(time.ticks_ms(), t_start)

    def charge(self, state: bool | None = None) -> bool | None:
        """
        Manages or returns the controller charge switch.

        If any of the arguments are invalid, an error is logged and the request
        is ignored and None is returned.

        Args:
            state: Controls either switching the controller on (True or 1), off
                (False or 0), toggle current state ('t') or if None, just
                returns the current state.

        Returns;
            1 if the controller state is currently charging, or 0 if not. If
            there was an error and state was not changed, None will be
            returned.

        Notes:
            * We will never allow the charge and discharge state to be set
              simultaneously. If this call is to switch charging on while
              already discharging, an error will be logged and the call will be
              ignored with None returned.
            * We will not allow charging to start unless we are in the
              `ST_BATINS` state
        """
        if state is None:
            # Only repost current state.
            return self.cfg.pin_ch.value()

        if state == "t":
            # Toggle current state
            set_to = not self.cfg.pin_ch.value()
        elif state in (True, False):
            set_to = state
        else:
            logger.error(
                "%s.charge: Invalid state argument: '%s'",
                self.__class__.__name__,
                state,
            )
            return None

        # We can not switch charging on if we are currently discharging
        if self.cfg.pin_dch.value():
            logger.error(
                "%s.charge: Can not switch charging on if already discharging.",
                self._me,
            )
            return None

        # We can not start charging unless we are in the `ST_BATINS` state
        if set_to and not self.state == self.ST_BATINS:
            logger.error(
                "%s.charge: Can not start charging unless a battery is present.",
                self._me,
            )
            return None

        # Set the new value and then read it back
        self.cfg.pin_ch.value(set_to)
        state = self.cfg.pin_ch.value()

        # Reset the jump detectors to settle for 4 sample_periods
        self.reset(["v_jump", "c_jump", "dc_jump"], -4)

        logger.info(
            "%s.charge: Charge State for %s set to %s",
            self._me,
            self.cfg.name,
            "On" if state else "Off",
        )

        return state

    def discharge(self, state: bool | None = None) -> bool | None:
        """
        Manages or returns the controller discharge switch.

        If any of the arguments are invalid, an error is logged and the request
        is ignored and None is returned.

        Args:
            state: Controls either switching the controller on (True or 1), off
                (False or 0), toggle current state ('t') or if None, just
                returns the current state.

        Returns;
            1 if the controller state is currently discharging, or 0 if not. If
            there was an error and state was not changed, None will be
            returned.

        Notes:
            * We will never allow the charge and discharge state to be set
              simultaneously. If this call is to switch discharging on while
              already charging, an error will be logged and the call will be
              ignored with None returned.
            * We will not allow discharging to start unless we are in the
              `ST_BATINS` state
        """
        if state is None:
            # Only repost current state.
            return self.cfg.pin_dch.value()

        if state == "t":
            # Toggle current state
            set_to = not self.cfg.pin_dch.value()
        elif state in (True, False):
            set_to = state
        else:
            logger.error(
                "%s.charge: Invalid state argument: '%s'",
                self.__class__.__name__,
                state,
            )
            return None

        # We can not start discharging unless we are in the `ST_BATINS` state
        if set_to and not self.state == self.ST_BATINS:
            logger.error(
                "%s.charge: Can not start discharging unless a battery is present.",
                self._me,
            )
            return None

        # We can not switch charging on if we are currently discharging
        if self.cfg.pin_ch.value():
            logger.error(
                "%s.charge: Can not switch discharging on if already charging.",
                self._me,
            )
            return None

        # Set the new value and then read it back
        self.cfg.pin_dch.value(set_to)
        state = self.cfg.pin_dch.value()

        # Reset the jump detectors to settle for 4 sample_periods
        self.reset(["v_jump", "c_jump", "dc_jump"], -4)

        logger.info(
            "%s.discharge: Discharge State for %s set to %s",
            self._me,
            self.cfg.name,
            "On" if state else "Off",
        )

        return state

    def reset(
        self, monitors: list | None = None, jump_settle: None | int = None
    ) -> None:
        """
        General reset function to reset certain states, monitors or large jump
        indicators.

        * **Monitors** are the voltage and charge monitors for the
          `BatteryControllerCFG` in the `cfg` property.
        * **Jump Indicators** are the large change jump flags we maintain in
          the `_jump_flags` property.

        The ``monitors`` arg is a list of strings names indicating which monitors
        or jump indicators to rest. If it is None, then all are rest. The
        allowed names are::

            [
                "ch_mon",  # Resets the charge monitor values
                "dch_mon", # Resets the discharge monitor values
                "v_mon",   # Resets the charge monitor values
                "v_jump",  # Resets the large battery voltage jump flag
                "c_jump",  # Resets the large charge current jump flag
                "dc_jump",  # Resets the large discharge current jump flag
            ]

        Rules are:

        * If the current `state` is `ST_YANKED`, we change the `state` to
          `ST_UNKNOWN` and also reset any monitor and/or jump flags. The
          `_updateState()` methods that gets called regularly from `monitor()`
          will not update the state while we are in `ST_YANKED` state.
        * Reset any monitors found in the list
        * Reset any jump indicators found in the list, optionally setting a
          *settle time* if needed.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Args:
            monitors: As noted above, or ``None`` (the default) to reset all
                monitors.
            jump_settle: For any of the jump flags, this value can be used to
                set settle delay for the jump detection. See `checkForJump` for
                more info. This must be a negative value or None for no settle
                delay
        """
        # Reset the battery yanked state
        if self.state == self.ST_YANKED:
            self.state = self.ST_UNKNOWN

        if not (isinstance(monitors, (list, tuple)) or monitors is None):
            logger.error(
                "%s.reset: Invalid value for monitors arg: %s",
                self._me,
                monitors,
            )
            return

        logger.info("%s.reset: Resetting monitor(s) for %s...", self._me, self.cfg.name)

        if jump_settle is not None and jump_settle >= 0:
            logger.error(
                "%s.reset: Ignoring invalid jump_settle value: %s",
                self._me,
                jump_settle,
            )
            jump_settle = None

        # Instead of validating each of the monitor field names in monitors, we
        # will only reset anything that is valid in there, and ignore anything
        # invalid. This should be slightly better on memory usage
        for mon in ["ch_mon", "dch_mon", "v_mon", "v_jump", "c_jump", "dc_jump"]:
            if monitors is not None and mon not in monitors:
                logger.debug("   Ignoring %s ...", mon)
                continue
            # The voltage and charge monitors are straight forward
            if mon.endswith("_mon"):
                getattr(self.cfg, mon).mon.reset()
                logger.info("   Monitor %s has been reset..", mon)
                continue

            # For the jump flags we need to do a bit of translation
            if mon == "v_jump":
                metric = "bat_v"
            elif mon == "c_jump":
                metric = "ch_c"
            else:
                metric = "dch_c"

            # Reset the correct jump tracker
            self._jump_flags[metric] = [jump_settle, False]
            logger.info("   Jump flag %s (%s) has been reset..", mon, metric)

    def status(self) -> dict:
        """
        Returns the current status for this battery controller.

        If any of the arguments are invalid, an error is logged and the request
        is ignored.

        Returns;
            If any args errors, an error is logged and None is returned, else a
            dictionary as:

            .. python::

                {
                    'ch_s': bool,  # True if currently charging, False otherwise
                    'dch_s': bool, # True if currently discharging, False otherwise
                    'bat_v': float,# Battery or output voltage value in mV
                    'v_jump': bool,# True if a large battery voltage jump was detected
                    'state': int,  # One of ST_??? class constants
                    'ch': float    # Last charge value measured in mAh
                    'ch_t': int    # Last charge period in seconds
                    'ch_c': int    # Last charge current in mA
                    'c_jump': bool,# True if a large charge current jump was detected
                    'dch': float   # Last discharge value measured in mAh
                    'dch_t': int   # Last discharge period in seconds
                    'dch_c': int   # Last discharge current in mA
                    'dc_jump': bool,# True if a large discharge current jump was detected
                    'mon_t': int,  # Time in ms for the last monitor loop
                    'bat_id': str|None, # The current `bat_id` value
                }
        """
        logger.debug("%s.status: Getting status for %s ...", self._me, self.cfg.name)

        # Get the current charge and discharge controller states, and the
        # battery/output voltage
        ch_s = self.cfg.pin_ch.value()
        dch_s = self.cfg.pin_dch.value()
        bat_v = self.cfg.v_mon.mon.v

        status = {
            "ch_s": ch_s,
            "dch_s": dch_s,
            "bat_v": bat_v,
            "v_jump": self._jump_flags["bat_v"][1],
            "state": self.state,
            "ch": self.cfg.ch_mon.mon.mAh,
            "ch_t": self.cfg.ch_mon.mon.tot_time,
            "ch_c": self.cfg.ch_mon.mon.c,
            "c_jump": self._jump_flags["ch_c"][1],
            "dch": self.cfg.dch_mon.mon.mAh,
            "dch_t": self.cfg.dch_mon.mon.tot_time,
            "dch_c": self.cfg.dch_mon.mon.c,
            "dc_jump": self._jump_flags["dch_c"][1],
            "mon_t": self._mon_time,
            "bat_id": self.bat_id,
        }

        return status
