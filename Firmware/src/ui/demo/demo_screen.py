"""
Demo UI Screen
"""

import random
from micropython import const
from ssd1306 import SSD1306_I2C
import uasyncio as asyncio
from lib import ulogging as logging
from ui.ui_output import Screen
from ui.ui_input import setupEncoder, input_evt

from config import (
    Pin,
    i2c,
    ENC_CLK,
    ENC_DT,
    ENC_SW,
    OLED_ADDR,
    OLED_W,
    OLED_H,
)

X = const(0)
Y = const(1)


class Clock(Screen):
    """
    Demo Screen
    """

    AUTO_REFRESH = 1000
    """Refresh every 1 second"""

    def __init__(self, name, px_w, px_h):
        """
        Override base __init__ to add a time settings
        """
        super().__init__(name, px_w, px_h)

        self.curr_time = [
            random.randrange(100),
            random.randrange(60),
            random.randrange(60),
        ]
        """Holds the current time as hh:mm:ss"""

        self.tx = (self.px_w - self.FONT_W * 8) // 2
        """Screen X coord of where the time is displayed"""

        self.ty = 1 * self.FONT_H
        """Screen Y coord for the time display"""

        self.dot = [self.px_w // 2, 0]
        self.dot_step = 6

    def _refreshTime(self):
        """
        Refresh the time output
        """
        # First clear the time rectangle since overwriting with spaces does not
        # seem to clear the screen
        self._display.rect(self.tx, self.ty, self.FONT_W * 8, self.FONT_H, 0, True)

        # Show the time
        h, m, s = self.curr_time
        col = ":" if s % 2 else " "
        self._display.text(f"{h:02d}H{m:02d}{col}{s:02d}", self.tx, self.ty)
        self._display.show()

    def setup(self):
        """
        Overriding setup
        """
        logging.info("Setting up...")
        self._clear()

        info = ["Rotate dot.", "Short faster.", "Long slower."]

        for y, i in enumerate(range(len(info))):
            self._display.text(info[i], 0, self.FONT_H * (y + 3))

        self._display.pixel(self.dot[0], self.dot[1], 1)
        self._display.text(f"{self.dot_step}", 1, 1)
        self._refreshTime()

        super().setup()

    def update(self):
        """
        Called every AUTO_REFRESH millis.
        """
        logging.info("Updating...")
        h, m, s = self.curr_time
        s += 1
        if s == 60:
            s = 0
            m += 1
        if m == 60:
            m = 0
            h += 1
        if h == 100:
            h = 0
        self.curr_time = [h, m, s]

        self._refreshTime()

    def actCCW(self):
        """
        Move CCW
        """
        logging.info("Rotate CCW")
        self._display.pixel(self.dot[0], self.dot[1], 0)
        if self.dot[X] == 0:
            # We're in the left column
            self.dot[Y] += self.dot_step
            if self.dot[Y] >= self.px_h:
                self.dot = [self.dot_step, self.px_h - 1]
        elif self.dot[Y] == self.px_h - 1:
            # We're in the bottom row
            self.dot[X] += self.dot_step
            if self.dot[X] >= self.px_w:
                self.dot = [self.px_w - 1, self.px_h - self.dot_step - 1]
        elif self.dot[X] == self.px_w - 1:
            # We're in the right column
            self.dot[Y] -= self.dot_step
            if self.dot[Y] <= -1:
                self.dot = [self.px_w - self.dot_step - 1, 0]
        elif self.dot[Y] == 0:
            # We're in the top row
            self.dot[X] -= self.dot_step
            if self.dot[X] <= -1:
                self.dot = [0, self.dot_step]
        logging.info("   Dot: %s", self.dot)
        self._display.pixel(self.dot[0], self.dot[1], 1)
        self._display.show()

    def actCW(self):
        """
        Move CW
        """
        logging.info("Rotate CW")
        self._display.pixel(self.dot[0], self.dot[1], 0)
        if self.dot[X] == 0:
            # We're in the left column
            self.dot[Y] -= self.dot_step
            if self.dot[Y] <= -1:
                self.dot = [self.px_w - self.dot_step - 1, 0]
                self.dot = [self.dot_step, 0]
        elif self.dot[Y] == self.px_h - 1:
            # We're in the bottom row
            self.dot[X] -= self.dot_step
            if self.dot[X] <= -1:
                self.dot = [0, self.px_h - self.dot_step - 1]
        elif self.dot[X] == self.px_w - 1:
            # We're in the right column
            self.dot[Y] += self.dot_step
            if self.dot[Y] >= self.px_h:
                self.dot = [self.px_w - self.dot_step - 1, self.px_h - 1]
        elif self.dot[Y] == 0:
            # We're in the top row
            self.dot[X] += self.dot_step
            if self.dot[X] >= self.px_w:
                self.dot = [self.px_w - 1, self.dot_step]
        logging.info("   Dot: %s", self.dot)
        self._display.pixel(self.dot[0], self.dot[1], 1)
        self._display.show()

    def actShort(self):
        """
        Override short press for increasing the dot rotation speed.
        """
        if self.dot_step >= 30:
            return
        self.dot_step += 2
        self._display.rect(1, 1, self.FONT_W * 2, self.FONT_H, 0, True)
        self._display.text(f"{self.dot_step}", 1, 1)
        self._display.show()

    def actLong(self):
        """
        Override Long press for decreasing the dot rotation speed.
        """
        if self.dot_step < 4:
            return
        self.dot_step -= 2
        self._display.rect(1, 1, self.FONT_W * 2, self.FONT_H, 0, True)
        self._display.text(f"{self.dot_step}", 1, 1)
        self._display.show()


def demo():
    """
    Demo entry point
    """
    logging.info("Setting up encoder...")
    # Set up the encoder
    setupEncoder(
        Pin(ENC_DT, Pin.IN),
        Pin(ENC_CLK, Pin.IN),
        Pin(ENC_SW, Pin.IN),
    )

    oled = SSD1306_I2C(OLED_W, OLED_H, i2c, OLED_ADDR)

    clock = Clock("clock", OLED_W, OLED_H)
    clock.focus(oled, input_evt)

    asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    demo()
