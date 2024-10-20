Micropython AsyncIO uUI
=======================

**Table of Content**

1. [Introduction](#introduction)
2. [Basic Concept](#basic-concept)
3. [Requirements](#requirements)
	1. [Hardware](#hardware)
	2. [Libraries](#libraries)
4. [Usage](#usage)
5. [Included Utilities](#included-utilities)
	1. [UI Menu](#ui-menu)

Introduction
------------

This package contains a simple Micropython UI framework that was specifically
tested on this hardware:

* ESP8266 and ESP32
* SSD1306 128x64 OLED (I²C version) for the display output
* KY-040 or clone type rotary encoder for user input

The framework is fairly generic, so should be able to run on other
environments, but may need some slight modifications.

It is meant to be run in an [asyncio] application. Any application that calls
the standard `sleep` function, or has long running functions or methods that is
not run asynchronously, will not allow user input to be detected as needed.


Basic Concept
-------------

The basic concept is as follows:

* Any number of `Screen` instances are created and can get focus.
* On application startup, focus is given to the first `Screen` to show.
* When a `Screen` instance gets focus, it has control of the `display` to
    show, draw, print, etc. user output, and will receive all user input from
    the input hardware (the Rotary encoder for now).
* The `Screen` instance will now do whatever it needs to do with user input,
    external input, etc. and update the display as and when needed.
* It will do this **asynchronously**.
* The `Screen` instance can at any point pass focus to another `Screen`
    instance, and can even suggest to the other `Screen` instance to pass focus
    back to it when it is done with whatever it needed to do.

Requirements
------------

### Hardware
* SSD1306 display
* KY-040 type rotary encoder
    * Pull-ups ????
* MCU running micropython

### Libraries
* uencoder ????
* ubutton ????
* ulogging ????
* typing ?????

Usage
-----
???? Understand the FrameBuffer ?????

See `ui.ui_output.Screen` ....
* 


Included Utilities
------------------

### UI Menu

A hierarchical menu system build as a `Screen`.....

Allows hierarchical menu ....

Menu actions are other `Screen` objects or submenu ...

<!-- links -->
[asyncio]: https://github.com/peterhinch/micropython-async/blob/master/v3/README.md

