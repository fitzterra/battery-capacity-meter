"""
Various Data Structures used throughout the application

Attributes:

    ADCChannel: ADC address and channel config on and ADS1115 module.

        * Type: **ADCChannel**
        * Fields:
            * ``addr``: The I²C address for the ADS1115 module
            * ``chan``: The channel value between 0 and 3 on the module.

        Example:

        >>> from structures import ADCChannel
        >>> c = ADCChannel(
        ... addr=0x49,   # Use the hex address value
        ... chan=2       # Second channel on the module
        ... )
        >>> c
        ADCChannel(addr=73, chan=2)
        >>> # Note the address is shown in decimal when printing it here.

    SpikeDetectCFG: ADC Spike Detector Config ``namedtuple``.

        This is a configuration for detecting spikes (large jumps or drops) in the
        ADC input stream.

        It is used in `ADCMonitor` and it's derived classes to configure spike
        detection. It is the ``spike_cfg`` arg to `ADCMonitor.__init__`

        * Type: **SpikeDetectCFG**
        * Fields:
            * ``threshold``: The minimum difference between two (post filter)
              ADC readings happening in less than the given period to be considered
              as an input spike.
            * ``period``: The period within which the threshold difference should
              occur. This is in milliseconds.
            * ``callback``: A callable that will be called whenever a spike is
              detected. The callback will get 3 args:

                * The ``drop_arg`` or ``jump_arg`` mentioned below.
                * A ``from`` value which is the value *from* which the change
                  started.
                * A ``to`` value which is the value *to* which the change jumped.

            * ``drop_arg``: Any argument that will be passed to the ``callback`` to
              indicate that this was a drop spike - value dropped by more than
              ``threshold``.
            * ``jump_arg``: Any argument that will be passed to the ``callback`` to
              indicate that this was a jump spike - value jumped by more than
              ``threshold``.

        Example:

        >>> from structures import SpikeDetectCFG
        >>> DROP = 0
        >>> JUMP = 1
        >>>
        >>> def spike_cb(direction):
        ...     '''
        ...     Sample callback function.
        ...     '''
        ...     print(f"Jump dir: {direction}")
        >>>
        >>> # Set up the detector configuration for detecting a
        >>> # 1000mv spike in either direction.
        >>> spike_cfg = SpikeDetectCFG(
        ... threshold=1000,  # 1000mV
        ... callback=spike_cb,
        ... drop_arg=DROP,
        ... jump_arg=JUMP,
        ... )
        >>>
        >>> spike_cfg
        SpikeDetectCFG(threshold=1000, callback=<function spike_cb at 0x3f803b50>, drop_arg=0, jump_arg=1)
        >>>
        >>> # Example of how it may be called from and `ADCMonitor` or derived
        >>> # instance for a drop detected:
        >>> spike_cfg.callback(spike_cfg.drop_arg, v_from, v_to)
        Jump dir: 0
        >>>
"""  # pylint: disable=line-too-long

from collections import namedtuple

# ADC address and channel config on and ADS1115 module.
ADCChannel = namedtuple("ADCChannel", ("addr", "chan"))

# ADC Spike Detector Config namedtuple.
SpikeDetectCFG = namedtuple(
    "SpikeDetectCFG",
    (
        "threshold",
        "period",
        "callback",
        "drop_arg",
        "jump_arg",
    ),
)
