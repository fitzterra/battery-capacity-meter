Battery Capacity Meter
======================

**Table of Content**

1. [Introduction](#introduction)
2. [Components and software Stack](#components-and-software-stack)
3. [Project Layout](#project-layout)
4. [Firmware Development](#firmware-development)
	1. [Dev environment setup](#dev-environment-setup)
	2. [Flashing MicroPython](#flashing-micropython)
	3. [Submodules](#submodules)
	4. [Building and uploading firmware](#building-and-uploading-firmware)
		1. [Building](#building)
		2. [Uploading](#uploading)
	5. [Building docs](#building-docs)
5. [Documentation](#documentation)

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
* TP4056 Breakout
* KiCAD
* Black
* Pylint

Project Layout
--------------

The project contains the hardware sources (schematics, PCB, etc.), firmware
sources, docs, etc. The base structure is:

    ├── doc
    │   ├── design              - Firmware state diagrams, etc.
    │   ├── Electronics         - Schematics, etc in SVG or image format
    │   └── firmware-api        - Firmware auto generated docs - not versioned
    ├── Electronics
    │   └── BatCapMeter         - KiCad project for BC Meter and Controller
    └── Firmware
        ├── ScreenDesign        - Screen design images
        ├── src                 - Firmware source code dir
        │   ├── firmware        - Firmware build dir - not versioned
        │   ├── lib             - Various source libs
        │   ├── micropython_binary - MP binary will be downloaded here - not versioned
        │   ├── pydoctor_templates - Templates for auto HTML api doc building
        │   ├── runtime_conf    - Runtime config before uploading new firmware
        │   ├── testing         - Testing and demos for various libs - NOT testcases
        │   └── ui              - OLED+Rotary Encode UI library
        └── submodules          - All submodules used by the firmware
            ├── micropython-ads1x15
            ├── micropython-mqtt
            ├── micropython-stubs
            ├── micropython-tools
            ├── ssd1306_mp
            ├── ubutton
            └── uencoder

Firmware Development
--------------------

The BCM firmware is in the `Firmware/src` dir and this is the root dir for
development.

There are a number of moving parts to getting the development done, so as much
as possible is set up in a `Makefile` to help with this.

After setting the development environment up (see below), run `make help` to
see what make commands are available.

### Dev environment setup

The development environment also relies on a Python virtual environment to be
available.

The first thing to do is to ensure you set a `venv` up and make sure it is
activated when in the `Firmware/src` dir.

A very easy way to do this is by using [direnv]. This is normally very easy to
install in Linux and MacOS via your package manager or [Homebrew]. An `.envrc`
file for [direnv] is provided in `Firmware/.envrc`. Once you change into this
dir, you will be asked to allow this RC file, and it will set up an Python 3
virtual environment, as well as some other environment variables needed by the
`Makefile`.

You may have to adjust the `DEVICE_PORT` value in this `.envrc` to match the
device your board presents if it is not `/dev/ttyACM0` as the ESP32-S2 does on
Linux. Try `make detect-device` once your environment is set up and the device
is connected - YMMV.

If not using [direnv], make sure you have your own python virtual environment
set up and that the environment variables as in `Firmware/.envrc` are exported
when running any `make` command.

With all this done, run `make dev-env` to install all required Python packages
needed for firmware dev.

### Flashing MicroPython

The Micropython binary to flash to the ESP32 device is defined in the
`MCU_CONF` file.  
Please update this file is required, but this project is built around the Wemos
S2 Mini and all is set up for that device.

The version of the MP binary can be updated though. Look the `MP_DOWNLOAD_SITE`
config value for the download URL. Updated versions may be found there.

In order to get the S2 Mini into flash mode, press and delete both onboard
buttons at the same time. This is needed for all of the binary flash commands
(not needed for firmware flashing as described below).

If this is the first time flashing this device, then the flash first needs to
be erased with `make erase-flash`.

To flash the MP binary, do `make flash-bin`. If the MP binary is not already
downloaded, it will be downloaded from the download URL in the `MCU_CONF` file.

After flashing, reset the device by pressing the reset button.

Now the firmware can be flashed after making sure the submodules are set up.

### Submodules

The firmware uses a number of submodules for various bit of functionality.
These are `git submodules` and you must make sure all submodules have been
cloned. Do this with:

    git submodules sync
    git submodules udate --init

All submodules are cloned as their own repos under `Firmware/submodules`.

I order to include any parts of these submodules in the source, we simply
create symlinks from the submodule to the name we want for it in the source.
For example here are submodules symlinked in the `src/lib` dir:

    ads1x15.py -> ../../submodules/micropython-ads1x15/ads1x15.py
    led.py -> ../../submodules/micropython-tools/led.py
    mqtt_as.py -> ../../submodules/micropython-mqtt/mqtt_as/__init__.py
    ssd1306.py -> ../../submodules/ssd1306_mp/ssd1306.py
    ubutton.py -> ../../submodules/ubutton/ubutton.py
    uencoder.py -> ../../submodules/uencoder/uencoder.py

### Building and uploading firmware

After making sure the submodules are set up as described above, the firmware
can be built and uploaded as described below.

#### Building
This is done with the simple command: `make build`

The way this works is as follows:

* All the Python source files that will make up the final firmware are defined
    in the `MPY_SRC` list in the `Makefile`. If new files are added or others
    removed, this list **MUST** be updated.
* From this list, all source files will first be cross compiled in order to
    speed up runtime.
* As `make` is supposed to do, only changed sources files will be compiled if
    they have not been compiled before.
* All compiled files (`.mpy`) are placed in the `firmware` dir (which will be
    created if it does not exist, and is not versioned), using the same files
    structure as in the `src` dir.
* After this, `firmware` dir is now ready to be uploaded to the device.

#### Uploading

Once the firmware has been built, it can be uploaded.

This is done with `make upload`. Note that the upload target will also first
build any outdated firmware if run directly with having done a `make build`
first.

The firmware allows certain runtime configurations to be made via the OLED +
Encoder UI. These are effectively changes to any default config values and are
then saved in new runtime config files on the device.

In order to make sure **ONLY** the files in the firmware as built will be
placed on the device with the next firmware upload, the upload is a type of
file sync operation where any files not appearing in the built firmware folder,
are deleted from the device, while changed files are uploaded.

This sync operation also makes the uploads faster because only new and changed
compiled files are uploaded.

The problem is with the runtime configs. Since these are not part of the built
firmware, they are also deleted. This is not ideal while developing because
then any runtime config changes needs to be done after every firmware upload.

For this reason the `Makefile` has the `runtime-cfg-backup` target that will
look for any of these runtime config files on the device and copy them to
`runtime_conf/backup`.

The `upload` target has the `runtime-cfg-backup` target as dependency which
will then always first backup any runtime config files before doing the upload
sync. Afterwards, all runtime backups will then be copied back to the device.

To quickly get a REPL after changes were made to any files and an update is
needed, this flow is very useful:

    make upload repl

which will make a new build, backup runtime configs, upload only the changes,
restore runtime config and immediately connect to the device and start the REPL.

### Building docs

The source is extensively documented using Python docstrings. This allows
automatically generating a complete set of source and app documentation using
[pydoctor]

The [pydoctor] main setup is in the `pydoctor.ini` file with some additional
setup in the `docs` target in the `Makefile`.

To build the documentation, run `make docs` - this will show any doc errors,
and build the final static HTML docs in `doc/firmware-api/` from the top level
dir. In this dir will be an `index.html` file that can be opened directly in a
browser.

There is also a CI job for GitLab that will build the docs and make them
available as GitLab pages for the repo. See [Documentation](#Documentation)
below for more.

Documentation
-------------

The application is written in Micropython and the full app docs are available
[here](http://pages.gaul.za/gaulnet/battery-capacity-meter/)


<!-- links -->
[direnv]: https://github.com/direnv/direnv
[Homebrew]: https://brew.sh/
[pydoctor]: https://pydoctor.readthedocs.io
