"""
Demo for the UI Input module.
"""

import uasyncio as asyncio
from lib import ulogging as logging
from ui.ui_input import (
    input_evt,
    setupEncoder,
    EV_ROTATE,
    EV_BUTTON,
    DIR_CW,
    # DIR_CCW,
    SHORT_PRESS,
    # LONG_PRESS,
)
from config import (
    Pin,
    # i2c,
    ENC_CLK,
    ENC_DT,
    ENC_SW,
)


async def trackEncoder():
    """
    Shows Encoder events
    """
    logging.info("Starting encoder tracker...")
    e_type = e_val = None

    while True:
        logging.info("Waiting for encoder event...")
        await input_evt.wait()
        if input_evt.e_type == EV_ROTATE:
            e_type = "Rotate"
            e_val = "CW" if input_evt.e_val == DIR_CW else "CCW"
        elif input_evt.e_type == EV_BUTTON:
            e_type = "Button Press"
            e_val = "Short" if input_evt.e_val == SHORT_PRESS else "Long"
        else:
            logging.error(
                "Unknown even type: %s (with value: %s)",
                input_evt.e_type,
                input_evt.e_val,
            )
        logging.info(
            "Input event: %s (%s): %s (%s)",
            e_type,
            input_evt.e_type,
            e_val,
            input_evt.e_val,
        )
        input_evt.clear()


def demo():
    """
    Demo entry for UI Input.
    """
    logging.info("Setting up encoder...")
    # Set up the encoder
    setupEncoder(
        Pin(ENC_CLK, Pin.IN),
        Pin(ENC_DT, Pin.IN),
        Pin(ENC_SW, Pin.IN),
    )

    asyncio.run(trackEncoder())


if __name__ == "__main__":
    demo()
