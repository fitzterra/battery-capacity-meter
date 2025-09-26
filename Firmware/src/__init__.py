"""
Battery Capacity Meter
======================

Introduction
------------

This is the documentation for a **Battery Capacity Meter** (BCM)

This **BCM** is used to measure the capacity, or **State of Charge** (SoC_), of
Li-ion_ batteries, and more specifically 18650_ cells, like those salvaged from
old laptop batteries.

Caution:
    The accuracy of the SoC_ as measured by this BCM depends on many factors
    and can **NOT** be considered an absolute exact measure of the battery
    capacity.

    It should rather be thought of as a fair estimate of the battery capacity
    measured relative to the accuracy of the components used in **this** BCM.
    
    It also helps when measuring multiple batteries and then trying to find
    batteries of similar capacity for building battery packs etc. Since all the
    batteries measure with the same BCM will all show a SoC_ relative to the BCM,
    so their measured capacities will be on a par with each other.

The method used for measuring the battery SoC_ is called `Coulomb Counting`_.
For this  method the amount of charge going into (while charging) and out of
(while discharging) the battery are calculated from basic voltage drops
measured across known resistor values. From this the charge/discharge current
is calculated, and keeping time of charge, one can calculate the Coulomb value
and from there the Ah value, which then gives you the SoC_ relative to this
measurement instrument.

Features
--------

The following are some of the features of this project:
    * Hands-off measuring and history recording (see `Telemetry Recording`_).
        * Once a test cycles is started, the battery will be fully charged.
        * From a fully charged state, one or more discharge/charge cycles can be
          started automatically to measure the SoC_.
    * Multiple batteries can be measured simultaneously
    * Various User Interfaces such as:
        * Direct Serial - implemented,
        * WebRepl Serial - implemented,
        * Onboard OLED and Rotary Encoder - implemented,
        * MQTT - telemetry output, but can be extended to be also be a UI of
          sorts
        * Bluetooth - can be implemented since the ESP32 has bluetooth
          capabilities.
    * Allows each battery to be given a unique ID which is used to keep a history
      of all tests and measurements over time.
    * Live broadcasting of measurement data via MQTT. This data feed can then
      be recorded in a Database for the given battery ID.
    * The following information is measured and broadcast in this way:
        * Battery ID
        * Charge/discharge cycle start and end
        * During charge/discharge the terminal voltage, charge/discharge current,
          cycle time, Coulomb charge and mAh up to that point.
        * Additional information like when a battery was inserted in the battery
          holder, when the battery ID was set, if it was removed before or during a
          test cycle, and more.
    * Uses off the shelve components:
        * TP4056_ charger module for charging and charge current measurement,
          including the DW01_ battery protector on the board for battery
          protection.
        * ADS1115_ 4 channel ADC for voltage/current measurements.
        * KY-040_ Rotary Encoder as user input
        * `SSD1306 OLED`_ for user output interface
        * `Wemos S2 Mini`_ ESP32 MCU running Micropython_

Telemetry Recording
-------------------

Since it takes a long time to charge and discharge a battery, this is a very
tedious process for a human to monitor and record.

Automating this process was the primary design goal for the BCM.

The `telemetry` part of the BCM firmware monitors the status of the
`BatteryController` all the time and reports this as telemetry events. When
certain events like battery inserted, battery removed, battery ID set,
charging, discharging, cycle complete etc.  happens, it will send a telemetry
message via MQTT_ on a specific topic (`net_conf.MQTT_PUB_TOPIC`).

From this it is then possible to record these messages into a database and by
processing the information from there, one can build a history and status for
each battery by ID.

During a charge or discharge cycle, measurement messages will be sent every few
seconds (configurable). This can be used to graph the charge/discharge data if
this has any interest.

Operation
---------

The basic user flow and operation is as follows:
    * Insert battery.
    * The battery ID should now be supplied.
        * If the battery does not have an ID yet, you can use the  ID suggested
          by the BCM. In this case it is advisable to immediately mark the with
          the new ID.
        * If it already has an ID, then use the encoder and screen UI to enter
          the ID.
    * The Battery Voltage and any other info that is available will be
      displayed. In Future, this may be the last time it was tested, what the
      known SoC_ was then ,etc.
    * You can now select one of the following options:
        * Measure: This starts one or more measurement cycles of
          charging/discharging the battery to determine it's SoC_.
        * Charge: This just charges the battery. All measurements will still be
          recorded.
        * Discharge: This is less useful, but is available for completeness. It
          discharges the battery fully and records the details.
    * When complete, the battery can be removed and all data would have been
      recorded

Hardware
--------

Below is a `Block Diagram`_ showing the BCM Controller and separate Battery
Controllers.

The `Schematic`_ Diagram is also shown below.

Block Diagram
~~~~~~~~~~~~~

.. image:: img/BCMBlockDiagram.drawio.svg
   :width: 80%

The complete BCM consists of the main **Controller** and 4 x pluggable
**Battery Controllers** (BCs).

The main **Controller** contains the ESP32, display, rotary encoder and button and
3 X 4 channel ADC modules.

A **Battery Controller** (BC) contains the TP4056 charger module, a high
wattage shunt resistor of known value used to measure the discharge capacity,
some MOSFETs to switch between charge and discharge, and the battery holder or
connector.

The **BCs** connect to the main **Controller** via a connector plug. This plug
is the same for all **BCs** and providers the power lines (5V), IO control
lines for the MOSFETs, and ADC inputs from monitoring the battery voltage,
charge current (via voltage on the TP4056) and the discharge current as the
voltage drop over the shunt resistor.

The controller can control and monitor each of the 4 BCs independently.

Note:
    The ADC modules (ADS1115_) each contains 4 ADC channels, but each BC only
    has 3 analog points to monitor. In order to monitor 4 BCs, we then only
    need 3 ADC modules, which means that we split the channels on the ADS1115_
    modules between the BCs.

The BC has two MOSFET switches that can switch to charging by powing up the
TP4056_, discharging by connecting the shunt resistor to the battery, or switch
both off.

Caution:
    In theory we can switch both charging and discharging on at the same time
    since there is nothing in the hardware to prevent this.  
    Doing so though is not a good idea and the firmware on the Controller goes
    to great lengths to prevent this.

Once charging or discharging is active, the Controller firmware can then
monitor the charge or discharge current (see `Current Monitoring`_ below) and
use `Coulomb Counting`_ to measure the dis/charge capacity.

By monitor the battery voltage, the BC can also detect when a battery is
inserted, which will then require a battery ID to assigned to the newly
inserted battery.

Once this has been done the various measure, charging or discharging options for
the battery and BC becomes available.

All state and measurement values per operating cycle is published on various
MQTT_ channels per battery ID. These details can then be recorded and analysed
by an external application.

Current Monitoring
^^^^^^^^^^^^^^^^^^

In order to monitor the charge current on the TP4056_ module, we monitor the
voltage on the PROG pin as per the datasheet. The charge current at this point
can then be calculated using the formula::

          Vprog
    Ich = ----- x 1200
          Rprog

where ``Rprog`` is the value of the current programming resistor on the board.

For a 1000mA charge current a 1200Ω resistor should be used for ``Rprog``.
Since these boards normally have a 1200Ω resistor installed, they are set to
charge at 1000mA.
From the formula above, the 1200 multiplier cancels the 1200Ω resistor
divisor, leaving the charge current (``Ich``) equal to the voltage measured on
the pin (``Vprog``).

To use the ``PROG`` pin of the TP4056_ as charge monitor input for the
`BatteryController`, we can effectively say the "current sensing" resistor is
1Ω. This is however not 100% accurate and the resistor value can be calibrated
at runtime. See `shunt_conf`.

For the discharge monitor, the load resistor is also defined in `shunt_conf` and
can be calibrated at runtime.


Schematic
~~~~~~~~~

.. image:: img/BatCapMeter-schematic.svg
   :width: 100%


Hardware config
~~~~~~~~~~~~~~~

Mapping the various MCU IO pins and ADC channels to the correct hardware pins
are done in the `config` module. This config is based on the config table
below.

See `Current Monitoring`_ above and `shunt_conf` for more info on the
**resistor** values.

.. Note: The table below is a bit tricky to render with pydoctor. To keep it
   fairly compact some headers span columns, and are double line header. This
   is supported with RST markup, but having empty cells is an error. Spaces do
   not work, normal hyphens start bullet list, underscores does not work.
   One option as used here is to use the Unicode point U+2010 which looks
   like a hyphen and renders a hyphen. Even Unicode space type characters does
   not seem to help.
   BTW: This is RST comment, but will probably render as an HTML comment :-(

====== ========= ================ ======= ==== ==== =========== ========== ========
 ‐        ‐             ‐         Control    ADC       ‐             Schematic
------ --------- ---------------- ------- --------- ----------- -------------------
Ctrl   Function  Type               GPIO  Addr Chan Resistor    CTL Pin    ADC Chan
====== ========= ================ ======= ==== ==== =========== ========== ========
**B0** Bat V     `VoltageMonitor`    ‐    0x48  1   ‐           ‐          B0_O+B_V
**B0** Charge    `ChargeMonitor`    16    0x48  2   `BC0_CH_R`  B0_CH_CTL  B0_CH_C
**B0** Discharge `ChargeMonitor`    18    0x48  0   `BC0_DCH_R` B0_DCH_CTL B0_DCH_C
**B1** Bat V     `VoltageMonitor`    ‐    0x49  3   ‐           ‐          B1_O+B_V
**B1** Charge    `ChargeMonitor`    33    0x49  2   `BC1_CH_R`  B1_CH_CTL  B1_CH_C
**B1** Discharge `ChargeMonitor`    35    0x48  3   `BC1_DCH_R` B1_DCH_CTL B1_DCH_C
**B2** Bat V     `VoltageMonitor`    ‐    0x49  0   ‐           ‐          B2_O+B_V
**B2** Charge    `ChargeMonitor`    37    0x4A  0   `BC2_CH_R`  B2_CH_CTL  B2_CH_C
**B2** Discharge `ChargeMonitor`    39    0x49  1   `BC2_DCH_R` B2_DCH_CTL B2_DCH_C
**B3** Bat V     `VoltageMonitor`    ‐    0x4A  2   ‐           ‐          B3_O+B_V
**B3** Charge    `ChargeMonitor`    40    0x4A  3   `BC3_CH_R`  B3_CH_CTL  B3_CH_C
**B3** Discharge `ChargeMonitor`    38    0x4A  1   `BC3_DCH_R` B3_DCH_CTL B3_DCH_C
====== ========= ================ ======= ==== ==== =========== ========== ========

________________

.. _Li-ion: https://en.wikipedia.org/wiki/Lithium-ion_battery
.. _18650: https://en.wikipedia.org/wiki/18650_battery
.. _SoC: https://www.batterydesign.net/battery-management-system/state-of-charge
.. _`Coulomb Counting`: https://www.batterydesign.net/soc-estimation-by-coulomb-counting/
.. _TP4056: https://components101.com/modules/tp4056a-li-ion-battery-chargingdischarging-module
.. _DW01: https://www.best-microcontroller-projects.com/support-files/dw01a.pdf
.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _`SSD1306 OLED`: https://components101.com/displays/oled-display-ssd1306
.. _KY-040: https://components101.com/modules/KY-04-rotary-encoder-pinout-features-datasheet-working-application-alternative
.. _Wemos S2 Mini: https://www.wemos.cc/en/latest/s2/s2_mini.html
.. _MQTT: https://en.wikipedia.org/wiki/MQTT
.. _Micropython: https://micropython.org
"""
