"""
All screen and UI related definitions.
"""

import gc
from micropython import const
from ssd1306 import SSD1306_I2C
from lib import ulogging as logging
from ui import (
    Screen,
    setupEncoder,
    input_evt,
    Menu,
)
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

# from interface import MODE_CHARGING, MODE_DISCHARGING
from version import VERSION

# These are constants defining the ellipses quadrants to draw
# There are 4 quadrants from Q1 to Q4 starting in the top right
# going around counter-clockwise
Q1 = const(0b0001)
Q2 = const(0b0010)
Q3 = const(0b0100)
Q4 = const(0b1000)


class Boot(Screen):
    """
    Boot screen
    """

    # We are just extending this class, @pylint: disable=too-few-public-methods

    def __init__(self, name: str, px_w: int, px_h: int, ctls: int) -> None:
        """
        Overrides init to accept the number of battery controllers available.

        Args:
            name, px_w, px_h: See `Screen.__init__`
            ctls: The number of battery controllers detected by the
                `ChargeControl` instance.
        """
        super().__init__(name, px_w, px_h)
        self.num_ctls = ctls

    def _drawLogo(self, x: int, y: int, rad: int = 12, show: bool = False):
        """
        Draws the logo centered at x,y.

        Args:
            x, y: The center pixel coordinates for the logo
            rad: The logo radius
            show: If True, the display will be updated to show the change.
                Default is to not update the display.
        """
        # Draws the right side half outer circle filled
        self._display.ellipse(x, y, rad, rad, 1, True, Q1 | Q4)
        # A smaller full circle in the center also filled
        self._display.ellipse(x, y, rad // 4, rad // 4, 1, True)
        # Clear out the right half of the small center circle
        self._display.ellipse(x, y, rad // 4, rad // 4, 0, True, Q1 | Q4)

        if show:
            self._show()

    def setup(self):
        """
        Shows the screen.

        We're assuming a 128x64 display, so coordinates and positions are hardcoded
        for this screen size.
        """

        head = f"BCM v{VERSION}"
        self._display.text(f"{head:^16}", 0, 0 * self.FONT_W)  # x,y = 0, line 0
        self._display.text(f"Ctls: {self.num_ctls}", 0, 2 * self.FONT_W)
        self._display.text(f"{'Click to start..':^16}", 0, 7 * self.FONT_W)
        # Draw the logo centered in x, and y center (rad = 12) +1 pixel above
        # bottom line (line height = 8)
        rad = 12
        self._drawLogo((self.px_w - 1) // 2, self.px_h - 1 - self.FONT_W - (rad + 1))

        self._show()


class MemoryUsage(Screen):
    """
    Displays the current memory usage.
    """

    # The auto refresh rate
    AUTO_REFRESH = 1000

    # The text line numbers where will display each matric
    ALLOC_Y = 3
    FREE_Y = 5
    FREE_P_Y = 7

    def setup(self):
        """
        Set the screen up.
        """
        self._clear()
        # Show the Screen name centered in line 0
        self._display.text(f"{self.name:^16}", 0, 0 * 8)

        self._display.text("Allocated:", 0, (self.ALLOC_Y - 1) * 8)
        self._display.text("Free:", 0, (self.FREE_Y - 1) * 8)

        self.update()

        # Call out base's setup to auto start a task for auto refreshing the
        # display - this task will be exited once we loose focus
        super().setup()

    def update(self):
        """
        Updates the display.
        """

        alloc = gc.mem_alloc()
        free = gc.mem_free()
        perc = free * 100 / (alloc + free)
        # First clear the alloc and free lines to white
        self._clearTextLine(self.ALLOC_Y, 1)
        self._clearTextLine(self.FREE_Y, 1)
        self._clearTextLine(self.FREE_P_Y, 0)
        # Update with the new values. We display then 4 pixel in from the edge
        # for a slightly better view
        self._display.text(f"{alloc} bytes", 4, self.ALLOC_Y * 8, 0)
        self._display.text(f"{free} bytes", 4, self.FREE_Y * 8, 0)
        self._display.text(f"{perc:.2f}% free", 0, self.FREE_P_Y * 8)

        self._show()


class BCMView(Screen):
    """
    Views and controls Battery Capacity Meter modules.
    """

    def setup(self):
        """
        Override Screen setup for BatCapMeter modules.
        """

        self._clear()

        self._display.text("To be done...", 0, 5, 1)
        self.update()

    def update(self):
        """
        Updates the display.
        """
        self._show()


MENU_DEF = (
    ("BCM View", BCMView("BCM View", OLED_W, OLED_H)),
    ("Memory usage", MemoryUsage("Memory Usage", OLED_W, OLED_H)),
)


def uiSetup(bat_ctrls: list) -> list:
    """
    Sets up the UI.

    This function will set the rotary encoder up from the ``ENC_??`` constants
    from `config`.

    It also sets the screens up and pass them back to the caller.

    Args:
        bat_ctrls: A list of all available battery controller names as retuens
            by `ChargeControl.ctlNames`

    Returns:
        A list of the following screens:

            [boot_screen]
    """
    logging.info("Setting up UI..")

    # Encoder setup
    setupEncoder(
        Pin(ENC_DT, Pin.IN),
        Pin(ENC_CLK, Pin.IN),
        Pin(ENC_SW, Pin.IN),
    )

    # Set up the OLED
    oled = SSD1306_I2C(OLED_W, OLED_H, i2c, OLED_ADDR)

    menu = Menu("MainMenu", OLED_W, OLED_H, MENU_DEF)

    # Set up the boot screen and give it focus it
    bootscreen = Boot("Boot", OLED_W, OLED_H, len(bat_ctrls))
    logging.info("  Passing focus to boot screen.")
    bootscreen.focus(oled, input_evt, focus_on_exit=menu)
