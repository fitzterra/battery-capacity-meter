"""
All screen and UI related definitions.

Attributes:
    Q1: Bit definition for drawing an ellipse_ in quadrant 1, top right
    Q2: Bit definition for drawing an ellipse_ in quadrant 2, bottom right
    Q3: Bit definition for drawing an ellipse_ in quadrant 3, bottom left
    Q4: Bit definition for drawing an ellipse_ in quadrant 4, top left

.. _ellipse:
    https://docs.micropython.org/en/latest/library/framebuf.html#framebuf.FrameBuffer.ellipse
"""

import gc
from micropython import const
from ssd1306 import SSD1306_I2C
from lib import ulogging as logging
from lib.charge_controller import BatteryController
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
    Boot screen.

    It only shows some boot info and then uses the base button press
    functionality to allow exiting the screen.

    Attributes:
        num_bcms: Set from the ``bcms`` arg to `__init__`.
    """

    # We are just extending this class, @pylint: disable=too-few-public-methods

    def __init__(self, name: str, px_w: int, px_h: int, bcms: int) -> None:
        """
        Overrides init to accept the number of BCMs available.

        We expect the ``name`` arg be something like "BCM vx.y.z" as this will
        be shown as the screen header and the version number is expected to be
        shown there.

        Args:
            name, px_w, px_h: See `Screen.__init__`
            bcms: The number of BCMs available.
        """
        super().__init__(name, px_w, px_h)
        self.num_bcms = bcms

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
        """
        self._clear()
        # Show the name as centered header
        self.nameAsHeader(fmt="^")

        self._display.text(f"BCMs: {self.num_bcms}", 0, 2 * self.FONT_W)
        self._display.text(f"{'Click to start..':^16}", 0, 7 * self.FONT_W)
        # Draw the logo centered in x, and y center (rad = 12) +1 pixel above
        # bottom line (line height = 8)
        rad = 12
        self._drawLogo((self.px_w - 1) // 2, self.px_h - 1 - self.FONT_W - (rad + 1))

        self._show()


class MemoryUsage(Screen):
    """
    Displays the current memory usage.

    Attributes:
        AUTO_REFRESH: Enable auto refresh every this many ms
        ALLOC_Y: Text row number to display the amount of memory allocated
            metric
        FREE_Y: Text row number to display the amount of free memory metric
        FREE_P_Y: Text row number to display the free memory percentage metric
    """

    # The auto refresh rate
    AUTO_REFRESH = 1000

    # The text line numbers where will display each metrics
    ALLOC_Y = 3
    FREE_Y = 5
    FREE_P_Y = 7

    def setup(self):
        """
        Set the screen up.
        """
        self._clear()
        # Show the Screen name centered in line 0
        self.nameAsHeader(fmt="^")

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
        # Update with the new values. We display them 4 pixel in from the edge
        # for a slightly better view
        self._display.text(f"{alloc} bytes", 4, self.ALLOC_Y * self.FONT_H, 0)
        self._display.text(f"{free} bytes", 4, self.FREE_Y * self.FONT_H, 0)
        self._display.text(f"{perc:.2f}% free", 0, self.FREE_P_Y * self.FONT_H)

        self._show()


class Config(Screen):
    """
    Config screen
    """

    def setup(self):
        """
        Set the screen up.
        """
        self._clear()
        # Show the Screen name centered in line 0
        self.nameAsHeader(fmt="^")

        self._display.text("To be done...", 0, 3 * 8)

        self.update()

        # Call out base's setup to auto start a task for auto refreshing the
        # display - this task will be exited once we loose focus
        super().setup()

    def update(self):
        """
        Updates the display.
        """
        self._show()


class BCMView(Screen):
    """
    Views and controls Battery Capacity Meter modules.
    """

    # The auto refresh rate
    AUTO_REFRESH = 500

    def __init__(self, name: str, px_w: int, px_h: int, bci: BatteryController):
        """
        Overrides base init.

        Args:
            name, px_w, px_h: See `Screen` base class documentation.
            bci: `BatteryController` instance to control and monitor.
        """
        super().__init__(name, px_w, px_h)
        self.bci = bci

    def _showHeader(self):
        """
        Shows the current BCM name as a header at the top of the screen
        """
        header = f"{self.name:^{self._max_cols}}"
        self._display.text(header, 0, 0, 1)
        self._invertText(0, 0)

    def setup(self):
        """
        Override Screen setup for BatCapMeter modules.
        """
        self._clear()
        self._showHeader()

        # If there are missing ADCs (only while developing really), we just
        # show a message. We do not start auto refresh task either.
        if self.bci.state == self.bci.ST_NOADC:
            msg = ["Missing ADC", "modules.", "", "Press to exit."]
            for l, m in enumerate(msg, 3):
                self._display.text(f"{m:^{self._max_cols}s}", 0, l * self.FONT_H, 1)
            logging.info("Unusable BCM %s - Missing ADC modules.", self.name)
            self._show()
            return

        # Call our base to setup the auto refresher task
        super().setup()

    def update(self):
        """
        Updates the display.
        """
        # Get the current status
        status = self.bci.status()

        ln = 3

        # Clear the full display line
        self._display.rect(0, ln * self.FONT_H, self.px_w, self.FONT_H, 0, 1)
        self._display.text(f"St: {status['state']}", 0, ln * self.FONT_H, 1)

        self._show()

    def menuText(self):
        """
        Allows for dynamically updating the menu screen entry for this BCM to
        also show current status.

        This method will be called by the `Menu` listing all the BCMs every
        time it needs to render the menu screen. To make it easier for the user
        to see at a glance what the BCM is doing, we can return a string of
        what we want to show on the menu from here.

        Returns:
            A string with this BMC name and a status indicator.
        """
        return f"{self.name} [{self.bci.state}]"


def uiSetup(bcms: list):
    """
    Sets up the UI.

    This function will set the rotary encoder up from the ``ENC_??`` constants
    from `config`.

    It then sets up the following screens and menus:

    * A `BCMView` screen for each of the `BatteryController` instances in the
        ``bcms`` list.
    * A `Menu` to list all these `BCMView` s and to open any of them
    * The main menu which consists of:

        * The BCMs menu
        * A `Config` option for future config and setup from the UI
        * An entry for the `MemoryUsage` screen

    * The `Boot` Screen.

    After all this, it passes focus to the boot screen and sets the main menu
    to receive focus when the boot screen exits.

    Args:
        bcms: A list of `BatteryController` instances to create BCMView
            screens for.
    """
    logging.info("Setting up UI..")

    # Encoder setup
    setupEncoder(
        Pin(ENC_DT, Pin.IN),
        Pin(ENC_CLK, Pin.IN),
        Pin(ENC_SW, Pin.IN, Pin.PULL_UP),
    )

    # Set up the OLED
    oled = SSD1306_I2C(OLED_W, OLED_H, i2c, OLED_ADDR)

    # Setup the BCMView list menu definition using a generator expression to
    # create a menu definition tuple
    bcms_def = tuple(
        (bcm.cfg.name, BCMView(bcm.cfg.name, OLED_W, OLED_H, bcm)) for bcm in bcms
    )
    # Now create the BCM list menu
    bcm_menu = Menu("BCMs", OLED_W, OLED_H, bcms_def, True)

    # Now we can dynamically create the main menu def
    main_menu_def = (
        ("BCMs View", bcm_menu),
        ("Config", Config("Config", OLED_W, OLED_H)),
        ("Memory usage", MemoryUsage("Memory Usage", OLED_W, OLED_H)),
    )
    main_menu = Menu("MainMenu", OLED_W, OLED_H, main_menu_def, True)

    # Set up the boot screen and give it focus it
    bootscreen = Boot(f"BCM v{VERSION}", OLED_W, OLED_H, len(bcms))
    logging.info("  Passing focus to boot screen.")
    bootscreen.focus(oled, input_evt, focus_on_exit=main_menu)
