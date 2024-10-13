"""
Various Data Structures used throughout the application
"""

from collections import namedtuple
from utime import ticks_ms, ticks_diff


class ADCChannel:
    """
    Defines an object for configuring and ADC address and channel on an ADS1115
    module.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, addr: int, chan: int):
        self.addr = addr
        """The I²C address for the ADS1115 module"""

        self.chan = chan
        """The channel value between 0 and 3 on the module."""


class VoltageMonitor:
    """
    Voltage monitor object.

    Example:

    >>> vm = VoltageMonitor()
    >>> vm
    v: 0
    >>> vm.v = 23.432  # Set voltage as mV
    >>> vm
    v: 23.432
    >>> print(vm)
    23.432mV
    >>> print(vm.v)
    23.432
    """

    def __init__(self):
        self._v: float = 0
        """The voltage value read from the ADC in millivolt (mV)"""

    @property
    def v(self):
        """
        Property to return the privately stored voltage value.
        """
        return self._v

    @v.setter
    def v(self, val: float | int):
        """
        Sets the voltage in mV read from the ADC,
        """
        self._v = val

    def __str__(self):
        """
        Show the value including it's units as a string.
        """
        return f"{self.v}mV"

    def __repr__(self):
        """
        Programmers representation.
        """
        return f"v: {self.v}"


class CurrentMonitor:
    """
    Current monitor object.

    Requires a known and accurate resistor value and the voltage drop measured
    across this resistor to calculate the current flow using Ohm's law.

    Example:

    >>> cm = CurrentMonitor(10)
    >>> cm
    c: 0, _v: 0, r: 10
    >>> cm.res = 5  # Change shunt resistor value to 5Ω
    >>> cm
    c: 0, _v: 0, r: 5
    >>> print(cm)
    0mA
    >>> cm.v = 2500  # Set ADC value read as 2500mv
    >>> # I = (V / R) = (2500 / 5) = 500.0mA
    >>> cm
    c: 500.0, _v: 2500, r: 5
    >>> print(cm)
    500.0mA
    >>> print(cm.v)
    2500
    >>> print(cm.c)
    500.0

    """

    def __init__(self, res: int = 1):
        self.res: float = res
        """The known and accurate resistor across which the voltage value is read."""

        self._v: float = 0
        """The voltage value read from the ADC in millivolt (mV)"""

        self.c: float = 0
        """
        The current calculated from the last voltage setting and
        resistor (`res`) value in milliamp (mA)
        """

    @property
    def v(self):
        """
        Property to return the privately stored voltage value.
        """
        return self._v

    @v.setter
    def v(self, val: float | int):
        """
        Setter for the voltage that will auto calculate and set the current
        value from the voltage and resistor value using Ohm's law.
        """
        self._v = val
        # Calculate the current
        self.c = val / self.res

    def reset(self):
        """
        Resets the monitor to zero
        """
        # Also resets self.c by virtue of calculating the current
        self.v = 0

    def __str__(self):
        """
        Show the value including it's units as a string.
        """
        return f"{self.c}mA"

    def __repr__(self):
        """
        Programmers representation.
        """
        return f"c: {self.c}, _v: {self._v}, r: {self.res}"


class ChargeMonitor:
    """
    Charge monitor object.

    Charge is measured in Coulomb (C) and one Coulomb is defined as the total
    current passing a point in a circuit in a period of one second, so that 1C
    is 1A of current flowing for 1 second.

    In order to measure the charge, we need to make many current measurements
    per second in so that we ensure we capture the true current flow for a one
    second period. Since this is impractical with an ADC, we do this:

    * Mark the current time
    * Some time now passes, or we do some other processing
    * Take a current measurement and assume that this current has been flowing
      continuously since we marked the time.
    * Calculate the elapse time as a portion of 1 second between now and when
      we marked the time. Take this same proportion of the current we measured
      now. This will then be the total charge that had flown for that potion of
      1 second, or otherwise seen as a portion of a Coulomb (<1C if the
      elapsed time was less than a second, >1C if the time was greater than 1s)
    * Accumulate all these charge portions, effectively measuring the full
      Charge in potions of a second or portions of a Coulomb.

    The more measurements we take in 1 second, the more accurate the result
    will be.

    The charge can also be converted to amp-hour (or mAh since `v` and `c` are
    in millis-) by dividing by 3600.

    As for the `CurrentMonitor`, this monitor requires a known and accurate
    resistor value across which a voltage is measured. The current is then
    calculated using Ohm's law.

    In addition to calculating the Current (`c`) and Charge (`ch`) value on
    every voltage measurement, this monitor also calculates the milliamp-hour
    (`mAh`) value, and also keeps track of how long the monitor has been
    running (`tot_time`).

    The `reset` method should be called before every new charge monitor session
    is started.

    Example:

    >>> chm = ChargeMonitor(10)
    >>> chm
    mAh: 0.0, ch: 0.0, c: 0, _v: 0, r: 10, t: 0
    >>> chm.res = 2  # Change the resistor value as 2Ω
    >>> # Set a voltage measurement of 500mv every 0.5 seconds
    >>> for m in range(10): chm.v = 500; chm; time.sleep(0.5)
    ...
    mAh: 0.0, ch: 0.0, c: 250.0, _v: 500, r: 2, t: 0
    mAh: 0.03493056, ch: 125.75, c: 250.0, _v: 500, r: 2, t: 503
    mAh: 0.07, ch: 252.0, c: 250.0, _v: 500, r: 2, t: 1008
    mAh: 0.105, ch: 378.0, c: 250.0, _v: 500, r: 2, t: 1512
    mAh: 0.14, ch: 504.0, c: 250.0, _v: 500, r: 2, t: 2016
    mAh: 0.175, ch: 630.0, c: 250.0, _v: 500, r: 2, t: 2520
    mAh: 0.21, ch: 756.0, c: 250.0, _v: 500, r: 2, t: 3024
    mAh: 0.245, ch: 882.0, c: 250.0, _v: 500, r: 2, t: 3528
    mAh: 0.28, ch: 1008.0, c: 250.0, _v: 500, r: 2, t: 4032
    mAh: 0.315, ch: 1134.0, c: 250.0, _v: 500, r: 2, t: 4536
    >>> chm
    mAh: 0.315, ch: 1134.0, c: 250.0, _v: 500, r: 2, t: 4536
    >>> print(chm)
    0.32mAh
    >>> chm.ch   # The current total charge value in mC
    1134.0
    >>> chm.tot_time    # The current measurement period in ms
    4536
    >>> chm.reset()
    >>> chm
    mAh: 0.0, ch: 0.0, c: 0.0, _v: 0, r: 2, t: 0
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, res: int = 1):
        self.res: float = res
        """The known and accurate resistor across which the voltage value is read."""

        self._v: float = 0
        """The voltage value read from the ADC in millivolt (mV)"""

        self.c: float = 0
        """
        The current calculated from the last voltage setting and
        resistor (`res`) value in milliamp (mA)
        """

        self.ch: float = 0.0
        """The charge accumulated so far in millicoulomb (mC)"""

        self.mAh: float = 0.0  # pylint: disable=invalid-name
        """The total charge as a milliamp-hour value (mAh)"""

        self._last_tick: int | None = None
        """The last time as ticks_ms we received an updated voltage value"""

        self.tot_time: int = 0
        """The total time in milliseconds we have been monitoring the charge so far"""

    @property
    def v(self):
        """
        Property to return the privately stored voltage value.
        """
        return self._v

    @v.setter
    def v(self, val: float | int):
        """
        Setter for the voltage value to also calculate the other values.

        Other values calculated are the current value from the voltage and
        resistor value using Ohm's law, the charge and amp-hour values, and
        also updates the time and last tick values.
        """
        self._v = val
        # Calculate the current
        self.c = val / self.res

        # If _last_tick is None, then this is the first value we received for
        # this monitor session. In this case, all we do if set _last_tick and
        # exit. This looses the first value, but measure difference and not
        # instances, so this is OK.
        if self._last_tick is None:
            self._last_tick = ticks_ms()
            return

        # Calculate the time in ms since the last update
        now = ticks_ms()
        ms_time = ticks_diff(now, self._last_tick)
        # Update the total monitor time so far, and reset to the last tick
        self.tot_time += ms_time
        self._last_tick = now

        # The millicoulomb value is the portion of 1000 milliSecs that
        # we assume this milliamps had flown for - accumulated:
        #  ms_time
        # --------- X self.c (mA)
        #  1000 ms
        #
        # Accumulate the mC value
        self.ch += (ms_time * self.c) / 1000

        # Calculate the mAh value. A Coulomb is defines as 1 Amp flowing past a
        # point for 1 sec. We have been counting/calculating this in self.ch.
        # Amp-hour is how many amps of current has flown past a point in one
        # hour, or 3600 seconds.
        # Since we have been accumulating the charge as the number of mA
        # flowing past a point per second, we only need to divide this value by
        # 3600 seconds to get the mAh value
        self.mAh = self.ch / 3600  # pylint: disable=invalid-name

    def reset(self):
        """
        Resets all values for this monitor.
        """
        # Also resets self.c by virtue of calculating the current
        self.v = 0

        # Also reset these
        self.ch = 0.0
        self.mAh = 0.0
        self._last_tick = None
        self.tot_time = 0

    def __str__(self):
        """
        We show the mAh value as string representation for this value.
        """
        return f"{self.mAh:0.2f}mAh"

    def __repr__(self):
        """
        Programmers representation.
        """
        return (
            f"mAh: {self.mAh}, ch: {self.ch}, c: {self.c}, "
            + f"_v: {self._v}, r: {self.res}, t: {self.tot_time}"
        )


ChannelMonitor = namedtuple(
    "ChannelMonitor",
    (
        "adc",
        "mon",
    ),
)
"""
    Channel monitor `namedtuple`.

    * Name: **ChannelMonitor**
    * Fields:
        * `adc`: Expects an `ADCChannel` instance
        * `mon`: Expects one of `VoltageMonitor`, `CurrentMonitor` or `ChargeMonitor`

    Example:

    >>> cm = ChannelMonitor(
    ... ADCChannel(addr=0x48, chan=1),
    ... ChargeMonitor(res=1)
    ... )
    >>> cm
    ChannelMonitor(adc=<ADCChannel object at 3f804d20>, mon=mAh: 0.0, ch: 0.0, c: 0, _v: 0, r: 1, t: 0)
    >>> cm.adc.addr
    72
    >>> cm.mon
    mAh: 0.0, ch: 0.0, c: 0, _v: 0, r: 1, t: 0
"""  # pylint: disable=line-too-long

BatteryControllerCFG = namedtuple(
    "BatControlCFG",
    (
        "name",
        "pin_ch",
        "pin_dch",
        "ch_mon",
        "dch_mon",
        "v_mon",
    ),
)
"""
    Battery Controller Config `namedtuple`

    * Name: **BatControlCFG**
    * Fields:
        * `name`: A name to uniquely identify this controller
        * `pin_ch`: Expects a `Pin` instance for charging control on and off
        * `pin_dch`: Expects a `Pin` instance for discharging control on and off
        * `ch_mon`: Expects a `ChannelMonitor` instance for charge monitoring
        * `dch_mon`: Expects a `ChannelMonitor` instance for discharge monitoring
        * `v_mon`: Expects a `ChannelMonitor` instance for battery voltage monitoring

    Example:

    >>> B0 = BatteryControllerCFG(
        "B0",
        Pin(16, Pin.OUT, value=0),  # Charge control pin
        Pin(18, Pin.OUT, value=0),  # Discharge control pin
        ChannelMonitor(
            # Charge monitor dict: adc and charge monitor
            ADCChannel(addr=0x48, chan=2),
            ChargeMonitor(res=1),
        ),
        ChannelMonitor(
            # Discharge monitor dict: adc and charge monitor
            ADCChannel(addr=0x48, chan=0),
            ChargeMonitor(res=LOAD_R),
        ),
        ChannelMonitor(
            # Battery voltage monitor dict: adc and voltage monitor
            ADCChannel(addr=0x48, chan=1),
            VoltageMonitor(),
        ),
    )
"""
