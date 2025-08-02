"""
Module containing a base ADC monitor and various inherited classes for
monitoring voltages, currents and charge.
"""

from math import ceil

import uasyncio as asyncio

from micropython import const
import utime as time

from i2c_config import AVAILABLE_ADCS

from lib.ulogging import getLogger
from lib.ads1x15 import ADS1115
from lib.utils import ewAverage

from structures import ADCChannel, SpikeDetectCFG

logger = getLogger(__name__)


class ADCMonitor:
    """
    Provides the base interface for various types of ADC Monitors based on the
    ADS1115_ ADC module.

    At the lowest level, an instance of an ``ADCMonitor`` does the following:

    * Start an ``asyncio`` monitor that reads an ADC input at a given rate
      (number of times per second)
    * The value may optionally be smoothed via the `ewAverage` function if an
      ``avg_w`` value was passed in on instantiation.
    * The read ADC value is then passed to the internal `_interpret()` method
      where the derived class can reinterpret this voltage value to something
      it is monitoring for. This could be voltage, current, charge, a
      potentiometer position, etc.

      This method can then store any locally interpreted values as it needs to.
    * After the value has been interpreted, the `_spikeDetect()` method is
      called if the ``spike_cfg`` arg was supplied.

        * If a spike (jump or drop in value >= to the *spike threshold* config
          value) is detected, and the rest of the spike config is valid, the
          spike callback function will be called, passing the correct drop or
          jump arg to the callback.

    It also provides interfaces to read the latest interpreted value,
    pause/resume the asyncio monitor, and any other interfaces the derived class
    may add.

    Attributes:
        ADC_GAIN: Gain setting for small ADC values. See code for more details.
        ADC_RATE: Default ADC conversion rate index. See code for more info.

        _me: Convenience used for logging context. From ``self.__class__.__name__``

        _disabled: ``True`` if this monitor is disable due to any init error. ``False`` otherwise.

        _val: The (possibly filtered) value from the last ADC read.

        _adc: From the ``ads1115`` arg to `__init__`

        _chan: From the ``chan`` arg to `__init__`

        _rate: From the ``rate`` arg to `__init__`

        _sample_delay: Calculated from the ``rate`` arg to `__init__`

        _alpha: The ``alpha`` user for averaging the ADC value using
            `ewAverage()` if filtering is enabled.

            If filtering is disabled (``avg_w`` was ``None`` on `__init__`)
            this value will be ``None``, otherwise it will be ``1 / avg_w``.
            See the ``avg_w`` arg to `__init__` for more info.

        _spike: ``None`` if the ``spike_cfg`` arg to `__init__` is ``None``,
            else it is `SpikeDetectCFG` named tuple for spike detection on the
            ADC stream.
            Spike detection is disabled if this value is ``None``.

        _spike_buf_len: Buffer length needed to detect the spike threshold
            difference within the allowed period.

            The `_sample_delay` is more or less the time between successive
            ADC sample calls that will be going to `_spikeDetect`. The buffer
            length therefore is calculated as the spike detection period
            divided by the `_sample_delay`, rounded up to ensure we always have
            at least one buffer entry.

            Not defined with `_spike` detection is disabled.

            See:
                `SpikeDetectCFG` and `_spike_buf`

        _spike_buf: The buffer used for spike detection of length
            `_spike_buf_len`.

            From the `_spike_buf_len` calculated, this buffer will be large
            enough to hold sample that spans the max spike detection period.

            Not defined with `_spike` detection is disabled.

            See:
                `_spikeDetect`

        _raw_avg: Keeps track of the filtered average if filtering is enabled.


        _paused: Internal pause indicator.

            Set from the ``paused`` arg to `__init__`.

        _tm_adc_sample: The average time it takes to sample and process an ADC
            reading in milliseconds.

            Since we take multiple samples per second, and it is not practical
            to monitor this value on every sample taken, the value is averaged
            over a window of 20 samples using `ewAverage`. This will catch any
            spikes when we are not looking.

            The larger this value is, the more time is taken per slice given to
            process the ADC reading, and the less time is left for the other
            tasks to be run.

            If the application is sluggish or values seems incorrect, this will
            be the place to start looking. This value should be a fraction of
            the value you get from ``1000 / _rate`` (`_sample_delay`).

            It will be reset on a `resume()` after the monitor has been
            `paused`. While `paused` it will have the last average value
            available.

            It will also be reset on a `reset()` call.

            Warning:
                This value will be ``None`` on startup and immediately after a
                `resume()`. As soon as the `_monitor` loop has run once, on
                startup or after `resume()`, the value will be an integer.
                Although the changes of an upper layer seeing this as ``None``,
                it is still possible and should be taken into account.

        _tm_mon_loop: The average time it takes to process the monitor loop.

            This time is also averaged over the same sample window as for
            `_tm_adc_sample`.

            This time does not include the `_sample_delay` time in the loop,
            but only the time to do the actual processing.

            This time can be used to show if the loop processing takes too
            long.

            As for `_tm_adc_sample`, this value is also reset on `resume()`,
            and the same warning of a ``None`` applies.

        _tm_sample_interval: The interval between samples in milliseconds.

            Note that this will be 0 on the first sample taken and only from
            sample 2 onwards will the value be correct.

    .. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
    """

    # pylint: disable=too-many-instance-attributes

    # Set the sampling rate. This is an index into the rates map of the ads1x15
    # module and sets the rate at which the ADS1115 will do the AD conversions. See
    # the datasheet for more, but a rate of 0 uses the slowest, but more accurate,
    # sampling rate of 8 samples per sec (over 500ms to sample all 4 channels),
    # while the max rate of 7 samples at 860 samples per sec (±19ms to sample all
    # four channels, but less accurate). The default rate of 4 does 128 samples per
    # sec and takes about 50ms for a 4 channels.
    ADC_RATE: int = const(4)

    def __init__(
        self,
        ads1115: ADS1115,
        chan: ADCChannel,
        rate: float,
        avg_w: int | None = None,
        spike_cfg: SpikeDetectCFG | None = None,
        paused: bool = False,
    ):
        """
        Instance initialiser.

        Args:
            ads1115: An `ADS1115` instance. The ``address`` value used to init
                this instance does not matter, as it will be set, along with
                the channel number, on every ADC read. The address and channel
                values are in the ``chan`` argument - see below.

                Setting the address and channel on every read, makes it
                possible to have multiple `ADCMonitor` instances use the same
                `ADS1115` instance.

            chan: This is an `ADCChannel` instance that defines the I²C access
                for the ADS1115_ module, as well as the specific ADC channel to
                use for this input.

                Note:
                    If the address or channel is invalid, an error will be
                    logged and this monitor will be `_disabled`.

            rate: This is the rate at which ADC samples should be taken, and is
                expressed as the number of samples per second.

                The way this is implemented, is to calculate the amount of time
                (ms) to delay between getting samples with ``delay = 1000/rate``,
                and then delaying by this number of milliseconds between ADC
                readings. Since the actual read and processing of the ADC value
                also takes time, this will never be a 100% accurate sampling
                rate.

                The higher this value, the busier the asyncio loop will be, so
                keep it reasonable. Maybe around 0.1 to max about 10.0 is
                probably OK, depending on your application.

            avg_w: If you want to filter the input values for possibly noisy
                input signals, then use this value to define a window period
                over which to sample.

                The averaging will be done with the `ewAverage` function and
                this value will be used to calculate the ``alpha`` value for
                `ewAverage()` as ``1 / avg_w``.

                If set, then the ADC value read will be run through the
                `ewAverage()` function using this ``alpha`` value. If the value
                is ``None``, then no filtering will be done.

            spike_cfg: This is used to configure optional spike detection in
                the ADC input stream.

                If ``None``, then no spike detection will be done. Otherwise it
                should be a `SpikeDetectCFG` namedtuple.

                **NOTE**: The callback should be quick about what it needs to
                do (just setting a flag is a good idea) since it is called from
                inside the asyncio loop, and all scheduling is stopped until
                this callback returns.

            paused: Start in the paused state when True (default), or in the
                run state when False.

                See `resume()`.

        Warning:
            Any errors in input args will log an error and the monitor will
            become unusable or functionality will be limited.

        .. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
        """
        # Yes, we need all the args, so
        # @pylint: disable=too-many-arguments,too-many-positional-arguments

        # Convenience name for logging
        self._me: str = self.__class__.__name__

        logger.info("%s: Initializing...", self._me)

        # This is the monitor value
        self._val: float = 0.0

        # We are enabled by default
        self._disabled: bool = False

        self._adc: ADS1115 = ads1115
        self._chan: ADCChannel = chan
        # Validate address and channel
        if not chan.addr in AVAILABLE_ADCS:
            logger.error(
                "  ADC address %s not available on the bus. Monitor disabled.",
                chan.addr,
            )
            self._disabled = True
        if not (isinstance(chan.chan, int) and 0 <= chan.chan <= 3):
            logger.error("  Invalid ADC channel: %s. Monitor disabled.", chan.chan)
            self._disabled = True

        # We store this only for completeness
        self._rate = rate
        if not isinstance(rate, (int, float)):
            logger.error("  Invalid rate: %s. Monitor disabled.", rate)
            self._disabled = True
            self._sample_delay = None
        else:
            # Calculate the sample delay
            self._sample_delay = int(1000 / self._rate)
            logger.info(
                "  Will delay by %sms between samples from sample rate of %s",
                self._sample_delay,
                self._rate,
            )

        # Calculate the averaging alpha value from the averaging window size.
        if avg_w is None:
            logger.info("  Filtering disabled.")
            self._alpha = None
        else:
            # See ewAverage
            self._alpha = 1 / avg_w

        # Local spike config
        self._spike = spike_cfg
        if self._spike:
            # Calculate the buffer length needed to detect the spike threshold
            # difference over the allowed period.
            # The _sample_delay is more or less how the time between successive
            # calls that will be going to _spikeDetect. The buffer length
            # therefore is the allowed period divided by the _sample_delay
            self._spike_buf_len = ceil(spike_cfg.period / self._sample_delay)
            # We initialize the buffer as empty so that the first value into
            # the buffer is the first real ADC value. This means we will not
            # get false spikes if the value is not 0.
            # This may also mean that we will not detect a situation like the
            # battery already inserted on startup, but this should be dealt
            # with somewhere else.
            self._spike_buf = []

        # This is the value to be used for spike detection, and the value the
        # spike threshold refers to. For raw ADC values this could be
        # self._val, but for other monitor types this may be an interpreted
        # value. The derived monitor can set this in the _interpret() call if
        # it should be anything other than self._val. The base class will set
        # this to self._val in it's interpret() method.
        self._spike_val = self._val

        self._paused: bool = paused

        self._raw_avg: float | None = None
        self._tm_adc_sample: float | None = None
        self._tm_mon_loop: int | None = None
        self._tm_sample_interval: int = 0

        # Start the monitor if we're not disabled
        if not self._disabled:
            asyncio.get_event_loop().create_task(self._monitor())
        else:
            logger.info("  Not starting monitor since we are disabled.")

    def __str__(self):
        """
        Returns a string showing status details.
        """
        return f"{self._me}, disabled:{self._disabled}, paused:{self.paused}, adc:{self._chan}"

    def _spikeDetect(self):
        """
        Spike detector.

        Called from `_monitor` after value interpretation (`_interpret()`) to
        detect if a spike has occurred.

        A spike is defined as a change larger than the ``threshold`` value in
        `_spike` (positive or negative) from the oldest value stored in
        `_spike_buf` to the current value read.

        If a spike is detected, the spike ``callback`` will be called with the
        ``drop_arg`` value as first argument for a negative spike, or
        ``jump_arg`` for positive spikes. These variables are defined in the
        `_spike` config.

        It will also receive the ``from`` and ``to`` jump values that caused
        the threshold to be crossed.

        On startup, `_spike_buf` is first incremented with new values until it
        reaches `_spike_buf_len` length. After this, for every new value, the
        oldest is popped off the buffer and the new `_spike_val` value
        appended. The old value is then compared to the new value to see if the
        difference is larger than the threshold set in `_spike`.

        Side Effect:
            Updates `_spike_buf` if spike detection is enabled.
        """
        # We ignore this if spike detection is disabled.
        if self._spike is None:
            return

        # Is our buffer full?
        if len(self._spike_buf) < self._spike_buf_len:
            self._spike_buf.append(self._spike_val)
            return

        # Shift the buffer left, keeping the old value and push the new one
        oldest = self._spike_buf.pop(0)
        self._spike_buf.append(self._spike_val)

        delta = self._spike_val - oldest
        if abs(delta) >= self._spike.threshold:
            # Spike detected...
            # Reset the buffer so we do not double detect
            self._spike_buf = []
            try:
                # Do the callback, passing the jump arg if the spike is
                # positive, or else the drop arg if negative.
                self._spike.callback(
                    self._spike.drop_arg if delta < 0 else self._spike.jump_arg,
                    oldest,
                    self._spike_val,
                )
            except Exception as exc:
                logger.error(
                    "%s: Disabling spike detection due to error calling callback: %s",
                    self,
                    exc,
                )
                self._spike = None

    def _interpret(self):
        """
        Reinterprets the ADC value just read and saves it back to `_val` when done.

        The child class can do anything it needs to with the value based on
        what it is deriving from the ADC voltage.

        This base class does nothing here, so the base class is an effective
        simple direct voltage monitor.

        In addition to interpreting the base `_val`, this method could
        also be used to set `_spike_val` to one of the interpreted values if
        `_val` should not be used for spike detection in any derived class.

        In this base class we set `_spike_val` to `_val` by default.
        """
        # Set spike detection to use `_val`
        self._spike_val = self._val

    async def _monitor(self):
        """
        Coro to continuously monitor and read the ADC input.

        Started automatically on instance init unless the monitor is disabled
        due to invalid init data, or subsequently disabled by setting
        `_disabled` to True.

        Will start running as soon as the AsyncIO scheduler is started.

        Can be `pause()` ed and `resume()` ed.
        """
        logger.info("%s: Starting monitor on ADC channel %s ...", self._me, self._chan)

        # Timer for interval between measurements
        sample_interval_timer = None

        # The alpha to use for the averaging of the ADC sample timer. We
        # average over a 20 window sample.
        adc_tm_alpha = 1 / 20

        # Just keep looping....
        while not self._disabled:
            # First we delay...
            await asyncio.sleep_ms(self._sample_delay)

            # Just cycle if we're paused
            if self._paused:
                # If we get paused, we want to also pause the
                # _tm_sample_interval time. This can be done by setting the
                # sample_interval_timer to None.
                # Since we are not updating this timer while paused, as soon as
                # we resume, we will miss one timer update while
                # sample_interval_timer get's set to the current time and from
                # then on the _tm_sample_interval will continue again.
                if sample_interval_timer is not None:
                    sample_interval_timer = None
                continue

            # Update sample interval timer. On the first time around we will
            # not have a start time, so need to set that first.
            if sample_interval_timer is not None:
                self._tm_sample_interval = time.ticks_diff(
                    time.ticks_ms(), sample_interval_timer
                )
            # Update the interval timer to now.
            sample_interval_timer = time.ticks_ms()

            # Timer for the sample timer
            loop_timer = time.ticks_ms()

            # Set up the ADS1115 instance with the address for our monitor.
            # Remember that there may be multiple monitors using the same self._adc
            # instance we use, and every time these monitors runs, they will change
            # the address for the self._adc (self._adc is shared amongst them all).
            self._adc.address = self._chan.addr

            # Read the channel ADC value, converted as mV value
            val = self._adc.raw_to_v(
                self._adc.read(rate=self.ADC_RATE, channel1=self._chan.chan),
                mV=True,
            )

            # Update the ADC read timer average
            self._tm_adc_sample = ewAverage(
                adc_tm_alpha,
                time.ticks_diff(time.ticks_ms(), loop_timer),
                self._tm_adc_sample,
            )

            # Filter?
            if self._alpha is not None:
                # We filter on the raw ADC value and thus need to keep track of
                # that before any interpreting happens
                self._raw_avg = ewAverage(self._alpha, val, self._raw_avg)
                # Now we set _val to the averaged value which can be
                # interpreted later if needed.
                self._val = self._raw_avg
            else:
                # Not filtering, save the value as is.
                self._val = val

            # Reinterpret if needed
            self._interpret()

            # Detect spike if needed
            self._spikeDetect()

            # If timing is an issue, remove this:
            self._logDebug()

            # Update the loop process time average. We use the same alpha as
            # for the ADC sample timer.
            self._tm_mon_loop = ewAverage(
                adc_tm_alpha,
                time.ticks_diff(time.ticks_ms(), loop_timer),
                self._tm_mon_loop,
            )

        logger.info("Exiting monitor since we became disabled.")

    def _logDebug(self):
        """
        Debugger method to help with testing.

        This method is called as the last thing in the monitor loop. The
        intention is that this method does logging at the DEBUG level to help
        testing and debugging.

        Derived classes can override this, or call up here... it's up to the
        class.

        This output could be massive when running in a full application and
        there is much debug logging in the rest of the app.

        If this becomes a problem, then possibly think of adding yet another
        property that can be set or clear to do or ignore this logging... but
        we are drowning in properties already, so time will tell.
        """
        logger.debug(
            "%8d: _tm_adc_sample: %3dms`, _val: %4.2fmV, _tm_sample_interval: %5dms",
            self._tm_adc_sample,
            self._val,
            self._tm_sample_interval,
        )

    @property
    def value(self):
        """
        Property to get the last (possibly filtered) ADC value.

        Returns:
            The value in `_val` as a rounded integer.
        """
        return round(self._val)

    def pause(self):
        """
        Pauses the monitor loop until `resume()` is called again.

        While paused, no ADC updates are made and values are left as they were
        when `pause()` was called.

        See:
            The `paused` property.
        """
        # If we are disabled, we log an error and return
        if self._disabled:
            logger.error("%s: Monitor disable. Ignoring pause.", self._me)
            return

        if self._paused:
            logger.error("%s: Already paused.", self._me)
            return

        self._paused = True

        # Also empty the spike buffer so we do not detect false spikes when we
        # start again
        if self._spike:
            self._spike_buf = []

        logger.info("%s: Entering paused state.", self._me)

    @property
    def paused(self):
        """
        Property to determine the current `pause` state.


        See:
            The `pause()` and `resume()` methods.

        Returns:
            ``True`` if currently paused, ``False`` otherwise.
        """
        return self._paused

    def resume(self):
        """
        Resumes the monitor loop after a previous `pause()`.

        See:
            The `paused` property.

        Side Effect:
            Resets `_tm_adc_sample` and `_tm_mon_loop`
        """
        # If we are disabled, we log an error and return
        if self._disabled:
            logger.error("%s: Monitor disable. Ignoring resume.", self._me)
            return

        if not self._paused:
            logger.error("%s: Not currently paused in resume() call.", self._me)
            return

        self._paused = False

        # Also reset the timers
        self._tm_adc_sample = self._tm_mon_loop = None

        logger.info("%s: Resuming from pause.", self._me)

    def reset(self):
        """
        Resets the monitor.

        The following values would be reset to these values:

        * `_val`: None
        * `_raw_avg`: None - used for input filtering
        * `_spike_buf`: None - used for detecting spikes
        * `_tm_adc_sample`: None
        * `_tm_mon_loop`: None

        Returns:
            True if reset was successful, False if the monitor is `_disabled`.
        """
        # If we are disabled, we log an error and return
        if self._disabled:
            logger.error("%s: Monitor disable. Ignoring reset.", self._me)
            return False

        logger.info("%s: Resetting monitor...", self._me)

        # Reset
        self._val = self._raw_avg = self._tm_adc_sample = self._tm_mon_loop = None
        if self._spike:
            self._spike_buf = []

        return True


class VoltageMonitor(ADCMonitor):
    """
    A voltage monitor based on `ADCMonitor`.

    The base `ADCMonitor` is already a voltage monitor, so this class simply
    interprets the `_val` property as the `_voltage` property in millivolt via
    `_interpret()`

    Attributes:
        _voltage: The measured ADC input as a voltage in millivolt (float),
            possibly filtered (see `_alpha`).

            This value is set from the `ADCMonitor._val` property.

        voltage: The `_voltage` as a rounded integer.
    """

    def __init__(
        self,
        ads1115: ADS1115,
        chan: ADCChannel,
        rate: float,
        avg_w: int | None = None,
        spike_cfg: tuple | None = None,
    ):
        """
        Voltage monitor initialiser.

        Args:
            ads1115, chan, rate, avg_w, spike_cfg: See `ADCMonitor.__init__`
        """
        # Yes, we need all the args, so
        # @pylint: disable=too-many-arguments,too-many-positional-arguments

        # Call up.
        super().__init__(ads1115, chan, rate, avg_w, spike_cfg)

        # Set up the voltage property
        self._voltage: float = 0.0

    def _interpret(self):
        """
        Overrides the base methods to add the `voltage` property.

        Side Effects:
           Updates `voltage` property to be the same as `_val`
        """
        # Call up
        super()._interpret()

        self._voltage = self._val

    @property
    def voltage(self):
        """
        Returns `_voltage` as a rounded integer.
        """
        return round(self._voltage)

    def _logDebug(self):
        """
        Overrides the base class to show `voltage` property.
        """
        logger.debug(
            "sample_time: %3dms`, voltage: %4dmV",
            self._tm_adc_sample,
            self.voltage,
        )

    def reset(self):
        """
        Resets the monitor.

        In addition to the values reset base the base `ADCMonitor.reset()`, we
        will also reset the `voltage` property here.

        Returns:
            True if reset was successful, False if the monitor is `_disabled`.
        """
        # Call up
        if not super().reset():
            logger.error("%s: Monitor disable. Ignoring reset.", self._me)
            return False

        logger.info("%s: Resetting monitor...", self._me)

        # Reset
        self._voltage = 0.0

        return True


class CurrentMonitor(VoltageMonitor):
    """
    Monitors current in a circuit via ADC input.

    This class extends the `VoltageMonitor` for monitoring current.

    In order to monitor current you need to have a known and accurate resistor.
    By monitoring the voltage drop across this resistor, you can then use `Ohm's
    Law`_ to calculate the current through the resistor::

             V
        I = ---
             R

    The resistor will normally be a very low value, often high power, *shunt*
    resistor connected in series with GND, and the ADC input connected to the
    other end of the resistor in order to monitor the voltage across the
    resistor.

    On every ADC read, the `_interpret()` function will convert the base
    `VoltageMonitor._voltage` to `current` using `Ohm's Law`_ and store this
    current value as the monitor value.

    The `_current` value will be in milliamps as the `VoltageMonitor._voltage`
    is in millivolts.

    Attributes:
        _shunt: The current shunt resistor value in ohm.
        _current: Calculated current through the `_shunt` resistor.

        current: Returns the `_current` value as a rounded integer.

            The current is calculated from the base `VoltageMonitor.voltage`
            and `_shunt` values, using `Ohm's Law`_

    .. _`Ohm's Law`: https://en.wikipedia.org/wiki/Ohm%27s_law
    """

    def __init__(
        self,
        ads1115: ADS1115,
        chan: ADCChannel,
        rate: float,
        shunt: int | float,
        avg_w: int | None = None,
        spike_cfg: tuple | None = None,
    ):
        """
        Current monitor instance init.

        Args:
            shunt: The shunt resistor value in ohm.
            ads1115, chan, rate, avg_w, spike_cfg: See `VoltageMonitor.__init__`

        """
        # Yes, we need all the args, so
        # @pylint: disable=too-many-arguments,too-many-positional-arguments

        # Call up..
        super().__init__(ads1115, chan, rate, avg_w, spike_cfg)

        self._shunt = shunt
        self._current: float = 0.0

    def __str__(self):
        """
        Returns a string showing status details.
        """
        return (
            f"{self._me}, disabled:{self._disabled}, paused:{self.paused}, "
            + f"shunt:{self._shunt}, adc:{self._chan}"
        )

    def _interpret(self):
        """
        Converts the sampled voltage to a current value.

        Also sets `_spike_val` to the calculated current so that spike
        detection is done against the current.

        Side Effect:
            Sets `current` to the current in milliamps.
        """
        # Call up
        super()._interpret()

        # Calculate to current
        self._current = self._voltage / self._shunt

        # Set spike detection to be against the current value
        self._spike_val = self._current

    @property
    def current(self):
        """
        Property to return `_current` as a rounded integer.
        """
        return round(self._current)

    def _logDebug(self):
        """
        Overrides the base class to show `voltage`, '_shunt` and `current` properties.
        """
        logger.debug(
            "sample_time: %3dms`, voltage: %4dmV, shunt_r: %4dΩ, current: %4dmA",
            self._tm_adc_sample,
            self.voltage,
            self._shunt,
            self.current,
        )

    def reset(self):
        """
        Resets the monitor.

        In addition to the values reset by the base `VoltageMonitor.reset()`, we
        will also reset the `_current` property here.

        Returns:
            True if reset was successful, False if the monitor is `_disabled`.
        """
        # Call up
        if not super().reset():
            logger.error("%s: Monitor disable. Ignoring reset.", self._me)
            return False

        logger.info("%s: Resetting monitor...", self._me)

        # Reset
        self._current = 0.0

        return True


class ChargeMonitor(CurrentMonitor):
    """
    Extends the `CurrentMonitor` to calculate the amount of Charge that has
    flown past a point in the circuit.

    This monitor is useful to calculate battery charge or discharge or
    capacity or energy usage.

    Charge is measured in Coulomb_ (C) and one Coulomb is defined as the total
    current passing a point in a circuit in a period of one second, so that 1C
    is 1A of current flowing for 1 second.

    In order to measure Charge, one needs to make continuous current
    measurements so that you ensure you capture the most accurate current flow
    for the measurement period.

    Since this is impractical with an ADC, a way to get a good estimate of the
    Charge is to make many current measurements, but calculate the elapsed
    period between each measurement. We then **assume** that this instantaneous
    current measured has been flown during the elapsed period.

    This means that for this portion of a second, the current measured is a
    portion of a Coulomb so that::

             period (ms)
        Cp = ----------- X current (A)
              1000 (ms)

             period (ms) X current (A)
           = ------------------------
                    1000 (ms)

    where:
        * ``period`` is the elapsed time since the last measurement
        * ``current`` is the current measure at the end of the ``period``
        * ``Cp`` is the calculated portion of a Coulomb, or Charge for this
          period

    We then simply accumulate the potions of Charge to get a running total
    Charge at any point in time.

    Obviously the more such measurements we make, the more accurate the final
    Charge value will be. The ``rate`` argument to `__init__` directly
    influences this, since this will be the rate at which we make measurements
    per second.

    Note:
        The period between measurements may also be more than 1 second since
        the above formula will still measure the Charge, but in this case,
        unless the current flow is very stable, the final total Charge measure
        would be less accurate.

    The Charge can also be converted from Coulomb_ to Amp-Hour by dividing by
    3600, since ``1Ah = 1A x 3600s = 3600C``

    As for the `CurrentMonitor`, this monitor also requires a known and
    accurate `_shunt` resistor.

    On every ADC read, the `_interpret()` function will convert the base
    `CurrentMonitor._current` to Charge as explained above, and accumulate this
    as the total Charge in the `_charge` property.

    The `_charge` value will be in millicoulomb as the
    `CurrentMonitor._current` is in milliamps.

    In addition to `_charge` in Coulomb_, the Amp-Hour Charge value will also be
    calculated in the `_mAh` property. This is also in millis, since everything
    else is in millis.

    Attributes:
        _charge: Calculated Charge in millicoulomb (mC).
        _mAh: The total Charge in milliamp-hour (mAh).
        charge_time: The total charge time used to get to this charge state.
            Will be set to 0 on `reset()`

        charge: A property to return the `_charge` as a rounded integer
        mAh: A property to return the `_mAh` as a rounded integer

    .. _Coulomb: https://en.wikipedia.org/wiki/Coulomb
    """

    def __init__(
        self,
        ads1115: ADS1115,
        chan: ADCChannel,
        rate: float,
        shunt: int | float,
        avg_w: int | None = None,
        spike_cfg: tuple | None = None,
    ):
        """
        Charge monitor instance init.

        Args:
            ads1115, chan, rate, shunt, avg_w, spike_cfg: See `CurrentMonitor.__init__`

        """
        # Yes, we need all the args, so
        # @pylint: disable=too-many-arguments,too-many-positional-arguments

        # Call up..
        super().__init__(ads1115, chan, rate, shunt, avg_w, spike_cfg)

        self._charge: float = 0.0
        self._mAh: float = 0.0  # It's OK @pylint: disable=invalid-name
        self.charge_time: int = 0

    def _interpret(self):
        """
        Converts the sampled current to a Charge value in both mC and mAh.

        Note:
            The base `CurrentMonitor` sets the current as the value against
            which we do spike detection. We do not change it here since that is
            probably the correct value for spike detection, and not the charge
            or mAh value.

        Side Effect:
            Sets `charge` and `mAh` to the current total charge in mC and mAh
            respectively.
        """
        # Call up
        super()._interpret()

        # On the first round, our _tm_sample_interval will be 0, so we can not
        # calculate the charge yet
        if self._tm_sample_interval == 0:
            return

        # We calculate the portion of a Coulomb measured using the
        # _tm_sample_interval and the instantaneous current value, and
        # accumulate this in the `charge` property
        self._charge += (self._tm_sample_interval * self._current) / 1000

        # And from here we do the mAh
        self._mAh = self._charge / 3600

        # Update the accumulated charge time
        self.charge_time += self._tm_sample_interval

    @property
    def charge(self):
        """
        Property to return `_charge` as a rounded integer.
        """
        return round(self._charge)

    @property
    def mAh(self):  # It's OK @pylint: disable=invalid-name
        """
        Property to return `_mAh` as a rounded integer.
        """
        return round(self._mAh)

    def _logDebug(self):
        """
        Overrides the base class to show `voltage`, '_shunt`, `current`,
        `_tm_sample_interval`, 'charge' and `mAh`  properties.
        """
        logger.debug(
            "sample_time: %3dms`, voltage: %4dmV, shunt_r: %4dΩ, "
            "current: %4dmA, _tm_sample_interval: %3d, Coulomb: %5dmC, "
            "Amp-Hour: %4dmAh",
            self._tm_adc_sample,
            self.voltage,
            self._shunt,
            self.current,
            self._tm_sample_interval,
            self.charge,
            self.mAh,
        )

    def reset(self):
        """
        Resets the monitor.

        In addition to the values reset base the base `ChargeMonitor.reset()`,
        we will also reset the `charge`, `mAh` and `charge_time` properties here.

        Returns:
            True if reset was successful, False if the monitor is `_disabled`.
        """
        # Call up
        if not super().reset():
            logger.error("%s: Monitor disable. Ignoring reset.", self._me)
            return False

        logger.info("%s: Resetting monitor...", self._me)
        # Reset
        self._charge = self._mAh = 0.0
        self.charge_time = 0

        return True
