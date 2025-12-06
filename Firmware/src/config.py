"""
Project configuration module.

This module is responsible for defining the config to match the hardware_.

The `hardware config`_ section defines the various hardware configs based on
the `schematic`_, which are then encoded in the `HARDWARE_CFG` structure.

The controller config elements in this structure can then be used to
instantiate `BatteryController` instances which are the low level control and
monitor interfaces to the hardware.

Besides the hardware_ config, there are also other runtime config values. All
configs are usually static and baked into the firmware, but the
`sitelocal_conf` module provides functionality to override these config values
and maintain the updated configs across restarts in the running system.

The `RUNTIME_CONF` in the `screens` module provides a UI config screen where
many of these values can be overridden, for example.

Attributes:
    PIN_LED: Onboard LED pin. Default for S2 Mini

    ADC_GAIN: This is the gain to set for the builtin ADS1115_ PGA.

        We will be measuring Lithium cells, so we can go up to 4.2V, which
        means we need to use the larges Full Scale Reading (FSR) which is
        ±6.144V or a granularity of 187.5µV per value.  The ads1x15 lib uses a
        gain mapping where the first entry (0) is the one we need for the gain
        we require.

        Note:
            We use the same gain for voltage and current/charge monitors. This
            needs some more investigation to see if the current/charge monitors
            may need a different GAIN scale.

    ADC_SAMPLE_RATE: The number of ADC samples any monitor should take per
        second.

        This will be the ``rate`` arg for `VoltageMonitor` and `ChargeMonitor`
        instances for each `BatteryController` set up. Each one of these
        monitors can be queried to see how long they take to complete an
        ADC sample by looking at the `ADCMonitor._tm_adc_sample` variable.

        The higher this value, the more samples are taken and possibly
        increased accuracy, but the less time is left over for other asyncio
        tasks. For what this application does, 2 samples per second should be
        plenty, and the only negative side effect will be that spikes will not
        be detected too quickly (battery inserts and yanks)


    OLED_ADDR: I²C address for SSD1306 OLED

    OLED_W: OLED width in pixels

    OLED_H: OLED height in pixels

    ENC_CLK: GPIO for encoder ``clk`` pin.

    ENC_DT: GPIO for encoder ``data`` pin.

    ENC_SW: GPIO for encoder ``switch`` pin. Will enable internal pull up for
        this pin.

    LOAD_R: The value to use for all battery controller load resistors.

        This is the resistor used for discharge measurement. Currently all
        battery controllers are expected to use the same load resistor value.
        The unit is ohm (Ω).

    HARDWARE_CFG: Complete hardware config for all available battery
        controllers supported by the hardware.

        This is a list of configs per battery controller as defined in the
        `Hardware config`_ section.

        Each list entry is a 4 element tuple as follows:

        .. python::

            (
                "BC0",     # Controller friendly name
                (          # Battery voltage monitor config
                    0x48,  #   ADC Address
                    1,     #   ADC Channel
                    None   # Averaging window if not None
                           # See ``avg_w`` arg to `VoltageMonitor.__init__`
                ),
                (          # Charge control and monitor on TP4056
                    16,    #   IO pin to enable charging
                    0x48,  #   ADC Address
                    2,     #   ADC Channel
                    1,     #   Shunt resistor value
                           #   See "ADC Inputs per battery controller" in module doc
                    None   # Averaging window if not None
                           # See ``avg_w`` arg to `ChargeMonitor.__init__`
                ),
                (          # Discharge control and monitor
                    18,    #   IO pin to enable discharging
                    0x48,  #   ADC Address
                    0,     #   ADC Channel
                    LOAD_R,#   Shunt resistor value
                    None   # Averaging window if not None
                           # See ``avg_w`` arg to `ChargeMonitor.__init__`
                )
            )

    LOGGING_CFG: Used to disable logging per named logger.

        By default logging is enabled for all log requests (barring the level
        allows it), but this config allows specific loggers to be disabled per
        destination. See `lib.ulogging.LOGGING_CFG` for more details and info
        about destinations.

        For effective use of this mechanism, it would be best to set up a
        logger per module via `getLogger` ``(__name__)`` and then the module name
        can be used as the logger name in this structure.

        Then, for the module/logger name, the standard logging or telemetry
        logging can be disabled/enabled by the destination keys as explained in
        `lib.ulogging.LOGGING_CFG`.

    ads1115: An ADS1115 instance set to the default I²C address, available for
        all monitors to use.

        This is used in `VoltageMonitor` and `ChargeMonitor` configs for the
        battery controllers. These controllers will set the address up as they
        need to when reading the specific ADS1115 modules/channels as needed.

    V_SPIKE_TH: Voltage spike threshold in mV.

        If a change in battery voltage (up or down) greater than this threshold is
        detected for a period less than `V_SPIKE_TH_T`, a voltage spike event
        is triggered.

        See:
            `SpikeDetectCFG`

    V_SPIKE_TH_T: Voltage spike detection threshold time in ms.

        This is the max time allowed for a voltage change greater than
        `V_SPIKE_TH` to trigger a voltage spike event.

        For a quick change in voltage, the event will be triggered immediately,
        but when removing a battery, the smoothing caps over the battery takes
        time to discharge, so the voltage change takes longer.

        This time value should be greater than the time it takes for a
        `V_SPIKE_TH` change to occur while discharging these caps.

        See:
            `SpikeDetectCFG`

    C_SPIKE_TH: Charge current spike threshold in mA.

        Any charge current change greater than this threshold value (up or
        down), occurring within a period less than `C_SPIKE_TH_T`, will cause a
        charge spike event to be triggered.

        See:
            `SpikeDetectCFG`

    C_SPIKE_TH_T: Charge current spike detection threshold time in ms.

        This is the max time allowed for a charge current change greater than
        `C_SPIKE_TH` to trigger a charge current spike event.

        See:
            `SpikeDetectCFG`

    D_SPIKE_TH: Discharge current spike threshold in mA.

        Any discharge current change greater than this threshold value (up or
        down), occurring within a period less than `D_SPIKE_TH_T`, will cause a
        discharge spike event to be triggered.

        Important:
            This value is used to detect when discharge is completed. Full
            discharge is reached when the DW01_ chips detects the battery
            voltage to be around 2.4V. When this voltage is reached,
            discharging stops and the discharge current drops to zero.

            In order for this to be detected, this threshold should be less
            than the final current still flowing when the battery discharged
            threshold voltage (2.4V) is reached. Thus this value should be less
            than ``2.4 / LOAD_R``.

        See:
            `SpikeDetectCFG`

    D_SPIKE_TH_T: Discharge current spike detection threshold time in ms.

        This is the max time allowed for a discharge current change greater
        than `D_SPIKE_TH` to trigger a discharge current spike event.

        See:
            `SpikeDetectCFG`

    C_VOLTAGE_TH: The battery threshold voltage at which we determine full
        charge to be completed in mV.

        This voltage is not used directly, but rather, when 
        `BatteryController._chargeSpike` detects a current spike, and the last battery
        voltage is above this threshold, then we generate fully charged event.

    D_VOLTAGE_TH: The battery threshold voltage at which we determine full
        discharge to be completed in mV.

        This voltage is not used directly, but rather, when a
        `BatteryController._dischargeSpike` is detected, and the last battery
        voltage is below this threshold, then we generate fully discharged
        event.

    D_V_RECOVER_TH: The voltage the battery needs to return to after discharge
        before we deem it recovered from discharge.
    
        The DW01 has this set to between 2.9V and 3.1V as a guide.

    D_RECOVER_MAX_TM: The max time we will allow for recovery after a discharge.

        If the recovery conditions are not met in this period, we will assume
        the battery is not a good state.

    D_RECOVER_TEMP: Once we bring in temperature measurement, this will be the
        recovery temp we expect the battery to be at.

    D_RECOVER_MIN_TM: Since we do not have battery temperature measurement
        currently, we will use a min rest time instead. This must be less than
        D_RECOVER_TM

    TELEMETRY_EMIT_FREQ: For continues telemetry emission states like charging
        and discharging, this is the frequency (in milliseconds) with which to
        emit telemetry updates.

    SOC_REST_TIME: The amount of time to rest after a charge or discharge
        complete to allow the battery and/or load temperatures to stabilize.

    SOC_NUM_CYCLES: The number of cycles to run for a SoC measurement

    CALIB_STEP: The step value to increase or decrease a shunt resistor value
       by when calibrating the shunt, via the `Calibration` UI screen.

.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _DW01: https://www.best-microcontroller-projects.com/support-files/dw01a.pdf
.. _hardware: index.html#rst-hardware
.. _hardware config: index.html#rst-hardware-config
.. _schematic: index.html#rst-schematic
"""

from i2c_config import const, i2c

from lib.ads1x15 import ADS1115

from shunt_conf import (
    BC0_CH_R,
    BC1_CH_R,
    BC2_CH_R,
    BC3_CH_R,
    BC0_DCH_R,
    BC1_DCH_R,
    BC2_DCH_R,
    BC3_DCH_R,
)

from sitelocal_conf import overrideLocal

# Pins used on the S2 Mini. See docstring Attributes for more.
PIN_LED = 15

# See docstring Attributes for more.
ADC_GAIN: int = const(0)

# See docstring Attributes for more.
ads1115 = ADS1115(i2c, gain=ADC_GAIN)

# See docstring Attributes for more.
ADC_SAMPLE_RATE = 3

# OLED. See docstring Attributes for more.
OLED_ADDR = 0x3C
OLED_W = const(128)
OLED_H = const(64)

# Encoder pins. See docstring Attributes for more.
ENC_CLK = const(4)
ENC_DT = const(2)
ENC_SW = const(1)

# Load resistor
LOAD_R = 8


# Config for all battery controllers
HARDWARE_CFG = [
    (
        "BC0",
        (0x48, 1, 5),
        (16, 0x48, 2, BC0_CH_R, None),
        (18, 0x48, 0, BC0_DCH_R, None),
    ),
    (
        "BC1",
        (0x49, 3, 5),
        (33, 0x49, 2, BC1_CH_R, None),
        (35, 0x48, 3, BC1_DCH_R, None),
    ),
    (
        "BC2",
        (0x49, 0, 5),
        (37, 0x4A, 0, BC2_CH_R, None),
        (39, 0x49, 1, BC2_DCH_R, None),
    ),
    (
        "BC3",
        (0x4A, 2, 5),
        (40, 0x4A, 3, BC3_CH_R, None),
        (38, 0x4A, 1, BC3_DCH_R, None),
    ),
]

# Default spike detection thresholds and times for voltage spike detection.
V_SPIKE_TH = 600  # Threshold for detecting voltage spikes
# Max time for this change to happen - removing a battery has a slow ramp down
# to 0V
V_SPIKE_TH_T = 1000

# Default spike detection thresholds and times for charge current spike detection.
C_SPIKE_TH = 100
# Max time for this change to happen
C_SPIKE_TH_T = 600

# Default spike detection thresholds and times for discharge current spike detection.
D_SPIKE_TH = 100
# Max time for this change to happen
D_SPIKE_TH_T = 600

# The battery voltage threshold at which we determine that charge is
# completed.
C_VOLTAGE_TH = 4180
## Discharge thresholds
# The battery voltage threshold at which we determine that discharge is
# completed. This should be above the DW01 over-discharge threshold of between
# 2.3V and 2.5V in order to not have the DW01 disconnect the battery. Keep in
# mind that id the Voltage monitor has an averaging window set, that the
# averaging may be lagging the voltage that the DW01 sees.
D_VOLTAGE_TH = 2600
# The voltage the battery needs to return to after discharge before we deem it
# recovered from discharge. The DW01 has this set to between 2.9V and 3.1V as a
# guide.
D_V_RECOVER_TH = 2900
# The max time we will allow for recovery after a discharge. If the recovery
# conditions are not met in this period, we will assume the battery is not a
# good state.
D_RECOVER_MAX_TM = 7 * 60
# Once we bring in temperature measurement, this will be the recovery temp we
# expect the battery to be at.
D_RECOVER_TEMP = 40
# Since we do not have battery temperature measurement currently, we will use a
# min rest time instead. This must be less than D_RECOVER_TM
D_RECOVER_MIN_TM = 3 * 60

##### Telemetry config #####
# For continues telemetry emission states like charging and discharging, this is
# the frequency (in milliseconds) with which to emit telemetry updates.
TELEMETRY_EMIT_FREQ = 5000

##### SoC Measurement config ####
# The amount of time to rest after a charge or discharge complete to allow the
# battery and/or load temperatures to stabilize.
SOC_REST_TIME = 5 * 60

# The number of cycles to run for a SoC measurement
SOC_NUM_CYCLES = 2

##### Calibration config ######
# The step value to increase or decrease a shunt resistor value by when
# calibrating the shunt.
CALIB_STEP = 0.05

#### Watchdog module config ######
# If we should log memory usage stats or not.
WD_LOG_MEM = True

##### Logging config #####
LOGGING_CFG = {
    "__main__": {
        "log": True,
        "telem": False,
    },
    "watchdog": {
        "log": True,
        "telem": True,
    },
    "screens": {
        "log": True,
        "telem": False,
    },
    "telemetry": {
        "log": True,
        # If True, it causes recursive telemetry logging. Keep it False
        "telem": False,
    },
}

# Override any site local values
overrideLocal(__name__, locals())
