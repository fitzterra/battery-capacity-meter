"""
Battery Capacity Meter + Monitor

Warning:
    Incomplete...

Introduction
------------

This is the documentation for a **Battery Capacity Meter + Monitor** (BCM² or
just BCM)

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
    * Various User Interfaces such as Serial, direct OLED and Rotary Encoder, MQTT,
      Bluetooth, etc.
    * Allows each battery to be given a unique ID which is used to keep a history
      of all tests and measurements over time.
    * Live broadcasting of measurement data via MQTT.
    * This data feed can then be recorded in a Database for the given battery ID.
    * The following information is measured and broadcast in this way:
        * Battery ID
        * Charge/discharge cycle start and end
        * During charge/discharge the terminal voltage, charge/discharge current,
          cycle time, Coulomb charge and mAh up to that point.
        * Additional information like when a battery was inserted in the battery
          holder, when the battery ID was set, if it was removed before or during a
          test cycle, and more.
    * Uses off the shelve components:
        * TP4056_ charger module for charging and charge current measurement.
        * ADS1115_ 4 channel ADC for voltage/current measurements.
        * KY-040_ Rotary Encoder as user input
        * `SSD1306 OLED`_ for user output interface
        * `Wemos S2 Mini`_ ESP32 MCU running Micropython_

Telemetry Recording
-------------------

Since it takes a long time to charge and discharge a battery, this is a very
tedious process for a human to monitor and record.

Automating this process was the primary design goal for the BCM².

The `telemetry` part of the BCM² firmware monitors the status of the
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
    * The Battery Voltage and any other info that is a available will be
      displayed. In Future, this may be the last time it tested, what the known
      SoC_ was then ,etc.
    * You can now select one of the following options:
        * Measure: This starts one or more measurement cycles of
          charging/discharging the battery to determine it's SoC_.
        * Charge: This just charges the battery. All measurements will still be
          recorded.
        * Discharge: This is less useful, but is available for completeness. It
          discharges the battery fully and records the details.
    * When complete, the battery can be removed and all data would have been
      recorded

Limitations and accuracy
------------------------

Due to the way blah, blah, blah....

.. _Li-ion: https://en.wikipedia.org/wiki/Lithium-ion_battery
.. _18650: https://en.wikipedia.org/wiki/18650_battery
.. _SoC: https://www.batterydesign.net/battery-management-system/state-of-charge
.. _`Coulomb Counting`: https://www.batterydesign.net/soc-estimation-by-coulomb-counting/
.. _TP4056: https://components101.com/modules/tp4056a-li-ion-battery-chargingdischarging-module
.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _`SSD1306 OLED`: https://components101.com/displays/oled-display-ssd1306
.. _KY-040: https://components101.com/modules/KY-04-rotary-encoder-pinout-features-datasheet-working-application-alternative
.. _Wemos S2 Mini: https://www.wemos.cc/en/latest/s2/s2_mini.html
.. _MQTT: https://en.wikipedia.org/wiki/MQTT
.. _Micropython: https://micropython.org
"""
