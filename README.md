Battery Capacity Meter
======================

Introduction
------------

This is a project to build something that can measure the capacity of
Lithium-Ion batteries, specifically 18650 cells, but not limited to those.

In order to fairly accurately measure the cell capacity, one has to do a full
discharge of the cell, and measure the energy used during the recharge. Or
alternatively, charge a fully discharged cell, measuring the energy used to get
battery to full capacity.

To get fairly accurate measurements from these techniques are more difficult
that it sounds due to some factors such as:

* Fully charged, or fully discharged are relative states. Unless whatever is
    used to accurately measure fully dis/charged state, there could be large
    variances.
* Unless the dis/charge cycle is done at a very high current rate, it could
    take a long time to fully dis/charge a cell of even a nominal capacity.
* Using large dis/charge currents is not the best way to measure capacity and
    may be more damaging than it needs to be.

To solve this, this meter has these features:

* Allows multiple (up to 4) batteries to be measured independently and
    concurrently.
* Uses known components and calibration to ensure that the fully dis/charged
    states are as close as the same at all times as possible.
* Does not use very large dis/charge currents to do the measurements.
* All dis/charge telemetry are streamed as MQTT data points to allow these to be
    captured in a separate system or database for further analysis - The
    **Battery Capacity Meter UI** project is a UI that evaluates these data
    points and record history and state for a collection of batteries.
* Each battery being measured is given, and expected to have, a unique ID that
    can be used to identify that battery in the telemetry as well as for
    keeping history.
* Allows singe charging, single discharging or full measurement cycles to be
    run per battery.
* A full measurement cycle will first charge the battery fully, then run 2
    (configurable) discharge and then charge cycles.

Components and software Stack
-----------------------------

* ESP32
* Micropython
* ADC ???
* OLED
* Encoder
* TP4056 Breakoput
* Other?

Documentation
-------------

The application is written in Micropython and the full app docs are available
here: [http://gaulnet.pages.gaul.za/battery-capacity-meter]

