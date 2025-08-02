"""
This module defines an asyncio input interface.

The input control is a rotary encoder with a standard push button.
To use this module, call the `setupEncoder` function to set the encoder up and
to start an ISR and coro to monitor for rotation and button events.

To be notified when these events occurs, the `input_evt` Asyncio Event_
primitive should be *await* ed on. When this event is set, the following
attributes on the event can be used to determine the event type and event
value:

* ``e_type``: The event type.
    One of `EV_ROTATE` for rotation, or `EV_BUTTON` for button presses
* ``e_val``: For `EV_ROTATE` type, this will be either `DIR_CW` or
    `DIR_CCW`. For `EV_BUTTON`, this will be one of `SHORT_PRESS` or
    `LONG_PRESS`

The monitor should reset (``clear()``) the input event after servicing it in
order for new events to be registered.

.. _Event: https://docs.micropython.org/en/latest/library/asyncio.html#class-event
"""

import uasyncio as asyncio
from micropython import const
from machine import Pin
from lib.uencoder import Encoder, DIR_CCW, DIR_CW
from lib.ubutton import uButton
from lib.ulogging import getLogger

logger = getLogger(__name__)

# Event type indicators
EV_ROTATE = const(1)
EV_BUTTON = const(2)

# Short and long press indicators
SHORT_PRESS = const(1)
LONG_PRESS = const(2)

input_evt = asyncio.Event()
"""This synchronisation primitive instance is used to signal an encoder event.
Events that can happen are rotation, clockwise and counter-clockwise, and
button presses, short or long.
In addition to the normal event methods, ``input_evt`` will have the following
attributes available to determine the event type:

* ``e_type``: the event type. One of EV_ROTATE for rotation, or EV_BUTTON for
          button presses
* ``e_val``: for EV_ROTATE type, this will be either DIR_CW or DIR_CCW. For
         EV_BUTTON, this will be one of SHORT_PRESS or LONG_PRESS
"""


rotate_evt = asyncio.ThreadSafeFlag()
"""This synchronisation primitive is used by the encoder to signal a rotation
event. See `rotateISR()` for more."""


async def rotationMonitor():
    """
    Monitors the `rotate_evt` sync primitive for an encoder rotation event, and
    then translates this event to the `input_evt` general input event sync
    primitive.

    The encoder changes are detected by an ISR which sets the `rotate_evt` sync
    primitive, while the button press events are detected by the
    `buttonPressed()` callback.
    In order to amalgamate the rotation and button press events into one event
    sync primitive (`input_evt`), we need a coro to monitor `rotate_evt` and
    also set the event details on `input_evt` as the `buttonPressed()` callback
    does.

    When a rotation event is detected, we will set `input_evt` and also the
    ``e_type`` and ``e_val`` attributes as noted for this sync primitive.
    """
    logger.debug("Starting rotationMonitor.")
    # Monitor continuously
    while True:
        # Wait for the event
        await rotate_evt.wait()
        logger.debug(
            "Rotation event: %s", "CW" if rotate_evt.rot_dir == DIR_CW else "CCW"
        )
        # Translate to input event
        input_evt.e_type = EV_ROTATE
        input_evt.e_val = rotate_evt.rot_dir
        input_evt.set()


def rotateISR(direction: DIR_CW | DIR_CCW):
    """
    Encoder rotation ISR.

    This is called from the encoder ISR on every leading and falling edge of
    the encoder switch contacts.

    It gets called 4 times per detent rotation as the switches open and close.
    For the first 3 callbacks, ``direction`` will be 0, until the 4th time when
    the final contacts position and direction can be determined and direction
    will then be one the final direction indicators.

    In order to use this in an asyncio application, we would want to set some
    event flag for other coros to wait on as an event signal. Since this
    callback is in an ISR, we can not use ``asyncio.Event()`` but rather
    ``asyncio.ThreadSafeFlag()``.
    The global `rotate_evt` is the synchronisation primitive we will then set.
    In addition to setting the flag, we will also add an additional attribute
    to this flag called ``rot_dir`` and set this to the direction value to
    indicate the rotation direction.

    See `rotationMonitor()` for info on how this flag is then used to link the
    rotation and encoder buttons into an asyncio app via the Event_
    synchronisation primitive.

    Args:
        direction: The direction that the encoder was turned, either clockwise
            (DIR_CW) or counter-clockwise (DIR_CCW). See the note above.

    .. _Event: https://docs.micropython.org/en/latest/library/asyncio.html#class-event
    """
    logger.debug("Encoder rotation callback. dir: %s", direction)
    # We ignore the direction while it is still settling
    if direction == 0:
        return

    # We have the final rotation direction, so we can set the flag and rotation
    # direction.
    rotate_evt.rot_dir = direction
    rotate_evt.set()
    logger.debug("Set rotate_evt...")


def buttonPressed(which: SHORT_PRESS | LONG_PRESS):
    """
    Called when a button press event happens, either for a short or long press.

    This callback only sets the input_evt sync primitive to indicate that a
    button press event has happened, and which press it was.

    Args:
        which: Indicates if it was short or long press.
    """
    logger.debug("Button pressed: %s", "Short" if which == SHORT_PRESS else "Long")
    input_evt.e_type = EV_BUTTON
    input_evt.e_val = which
    input_evt.set()


def setupEncoder(
    clk_pin: Pin, dat_pin: Pin, sw_pin: Pin, bounce_t: int = 25, long_t: int = 500
) -> None:
    """
    Sets up the encoder to detect rotation and button presses.

    Note this code assumes a KY-040_ style encoder with ``clk`` and ``data``
    pins. Other encoders could have A/B pins or similar.

    The encoder button will generate both a long and short press event. The
    long press time is determined by the ``long_t`` argument. In order to detect
    the long press, the short press will only be triggered on releasing the
    button. This behaviour can be changed via the `uButton` class, but should
    work for the most part for most applications.

    Args:
        clk_pin: A ``machine.Pin`` instance for the pin the ``clk`` input is
            connected to. It must be set as an input. Pull-ups should be set as
            required for the device or circuit.
        dat_pin: A ``machine.Pin`` instance for the pin the ``dat`` input is
            connected to. It must be set as an input. Pull-ups should be set as
            required for the device or circuit.
        sw_pin: A ``machine.Pin`` instance for the pin the ``sw`` button input is
            connected to. It must be set as an input with pulls-ups to VCC so
            that a press with take the input low.
        bounce_t: The amount of time to allow for debouncing the switch
            contacts in milliseconds.
        long_t: The amount of time to wait for long press. Default is 500ms.

    .. _KY-040: https://components101.com/modules/KY-04-rotary-encoder-pinout-features-datasheet-working-application-alternative
    """
    logger.debug(
        "setting up encoder. clk_pin: %s, dat_pin: %s, sw_pin: %s",
        clk_pin,
        dat_pin,
        sw_pin,
    )

    # Create the encoder rotation instance
    Encoder(pin_A=clk_pin, pin_B=dat_pin, callback=rotateISR)

    # Create the button monitor for both short and long presses.
    button = uButton(
        sw_pin,
        cb_short=lambda: buttonPressed(SHORT_PRESS),
        cb_long=lambda: buttonPressed(LONG_PRESS),
        bounce_time=bounce_t,
        long_time=long_t,
    )

    # Get the asyncio loop so we can create asyncio task for the button.run()
    # and rotationMonitor coros
    loop = asyncio.get_event_loop()
    loop.create_task(button.run())
    loop.create_task(rotationMonitor())
