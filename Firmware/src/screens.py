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
from lib.utils import genBatteryID
from lib.charge_controller import BatteryController
from ui import (
    Screen,
    setupEncoder,
    input_evt,
    Menu,
    FieldEdit,
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

        self.text("To be done...", fmt="^w", y=3)

        self.update()

        # Call out base's setup to auto start a task for auto refreshing the
        # display - this task will be exited once we loose focus
        super().setup()

    def update(self):
        """
        Updates the display.
        """
        self._show()


class FootMenu:
    """
    Class that can be used to show and manage a footer type menu at the bottom
    of the screen.

    An instance of this class can be instantiated in any `Screen` type
    instance, and given a footer menu definition that will be navigable by
    rotating the encoder. The currently selected menu option can be activated
    by pressing the encoder button. This will cause a callback to be called for
    the selected menu option.

    See the menu animation at the bottom of the screen sample below:

    .. image:: ../../Firmware/ScreenDesign/OLED128x64_BatIns_State_larger.gif

    To use this menu, the following has to done:

    * Define your footer menu (see below)
    * Create an instance of this class in your `Screen` as an instance
      property.
    * Once this instance has been created, call the `drawMenu()` at the
      appropriate time.
    * Override or add to the `Screen.actCCW()` method to call the `selectNext()`
      method with an argument of ``-1`` - this select the previous menu option.
    * Override or add to the `Screen.actCW()` method to call the `selectNext()`
      method with an argument of ``1`` - this select the next menu option.
    * Override or add to the `Screen.actShort()` method to call the `activate()`
      method - this make a call to the associated callback for the currently
      selected option.

    **Footer menu definition**:

    .. python::

        [
            ('opt', 'desc'{, optional_callback}),
            ....
        ]

    * The ``opt`` element is the short option displayed as menu option selector.
    * The ``desc`` element is a longer description string for this menu. If it
      is longer than a screen width, it will be truncated. See
      `Screen._max_cols`.
    * Each option can have it's own callback that will be called when the
      option is selected via the `activate()` method. The callback must be
      able to accept the ``opt`` string as only argument.

    This menu definition will be parsed into the final `menu` list as described
    below.


    Attributes:
        OPT_OPT: Index into `menu` option element to get to the option string.
        OPT_DESC: Index into `menu` option element to get to the description string.
        OPT_CB: Index into `menu` option element to get to the callback.
        OPT_PX: Index into `menu` option element to get to the X pixel offset
            where the option is shown on the screen.
        _screen: Reference to the `Screen` instance we are being displayed in.

            This is set from the ``screen`` argument to `__init__`.
        _callback: General option selected callback.

            See ``callback`` argument to `__init__`.
        _active: Index into `menu` to indicate the currently active option.
        menu: This is a list of the menu options.

            Each element in this list is another list defining that menu
            option:

            .. python::

                [
                    [  # First option
                        'opt',                # The option string - OPT_OPT
                        'description string', # Description string - OPT_DESC
                        callback,             # Optional direct callback - OPT_CB
                        x_ofs,                # X pixel display offset - OPT_PX
                    ],
                    [  # Second option
                       ...
                    ],
                    ...
                ]

            This list is created from parsing the ``menu`` arg to `__init__`.
    """

    # Constants defining the index to the various menu option config lists
    OPT_OPT: int = const(0)  # The menu option string is element 0
    OPT_DESC: int = const(1)  # The menu description/help is the 2nd element
    OPT_CB: int = const(2)  # The menu option callback index
    OPT_PX: int = const(3)  # Index for X pixel offset of where the option is displayed.

    def __init__(self, screen: Screen, menu: list, callback: callable | None = None):
        """
        Class initialization.

        Warning:
            No validation is done for any of the args. You get it wrong and it
            gonna break...

        Args:
            screen: The `Screen` instance we are running in. This is needed to
                get access to the display and it's properties. Usually just
                passed as ``self``.
            menu: See `FootMenu` class documentation.
            callback: Optional general callback.
                Only required if any menu option does not have it's own
                callback. It will be called by `activate()` if the active
                option does not have it's own callback defined. The currently
                selected menu option is the only argument passed to the
                callback.
        """
        self._screen: Screen = screen

        # Created an options list of option configs
        offs = 0
        self.menu: list = []
        for opt in menu:
            # Rebuild the passed in menu to ensure we have a callback or None
            # for each option, and also the X offset in pixels of where the
            # option is displayed. This offset is used to both place the option
            # text, and also to later place the indicator lines.
            self.menu.append(
                [
                    opt[0],  # The menu option text - OPT_OPT
                    opt[1],  # The menu option help/description text - OPT_DESC
                    None if len(opt) == 2 else opt[2],  # Optional callback - OPT_CB
                    offs,  # X offset in pixels OPT_OPT display position - OPT_PX
                ]
            )
            # Update offs to the offset of where the next item will start. We
            # leave one space between items. The offset is in pixels.
            offs += (len(opt[0]) + 1) * self._screen.FONT_W

        self._callback: callable = callback

        self._active: int = 0

    def drawMenu(self):
        """
        Draws the menu onto the last screen rows.

        The last two screen rows will be cleared and the option strings for
        each menu will be shown, separated by 1 space.

        The currently active (see `_active`) option's description text will be
        shown in the last screen row, and the option will be highlighted by
        adding a top and bottom line to the option.
        """
        # We will be doing a lot access to protected members in this method, so
        # @pylint: disable=protected-access

        scr = self._screen
        # Clear the last two rows to be sure
        scr._clear(header_lns=scr._max_rows - 2)

        # Draw the options
        opts = " ".join(opt[self.OPT_OPT] for opt in self.menu)
        scr.text(opts, fmt="", y=scr._max_rows - 2)

        # Show the description
        act = self.menu[self._active]
        scr.text(act[self.OPT_DESC], fmt="", y=scr._max_rows - 1)

        # Draw top and bottom lines on the active option
        y_offs = (scr._max_rows - 2) * scr.FONT_H
        x_len = len(act[self.OPT_OPT]) * self._screen.FONT_W
        for _ in range(2):
            scr._display.hline(act[self.OPT_PX], y_offs, x_len, 1)
            y_offs += scr.FONT_H - 1

    def selectNext(self, sel_dir: int):
        """
        Selects the next menu option, either left or right from the current.

        The selection will wrap around when going past either edge.

        This is normally called from the `Screen.actCCW()` and `Screen.actCW()`
        event methods.

        Args:
            sel_dir: Selection direction. This should be any positive value for
                going right, and any negative value for going left. Any other
                value will default to going right.
        """
        # Move in the desired direction
        self._active += -1 if sel_dir < 0 else 1

        # Handle wrapping
        if self._active < 0:
            self._active = len(self.menu) - 1
        if self._active >= len(self.menu):
            self._active = 0

        # Update
        self.drawMenu()

        # Update the display
        self._screen._show()  # pylint: disable=protected-access

    def activate(self):
        """
        Called to activate the currently selected menu option.

        This will either call the option specific ``callback`` defined by the
        active (`_active`) `menu` option if supplied, or else, the general
        `_callback` if supplied.

        If neither callback is available, nothing will be done other logging a
        message.

        This is normally called from the `Screen.actShort()` event method when
        a short press event is received.
        """
        opt = self.menu[self._active]

        logging.info(
            "FootMenu for Screen %s: Activate option '%s'",
            self._screen.name,
            opt[self.OPT_OPT],
        )

        cb = opt[self.OPT_CB] or self._callback
        if not cb:
            logging.info(
                "FootMenu for Screen %s: No callback for option '%s'",
                self._screen.name,
                opt[self.OPT_OPT],
            )
            return

        logging.info(
            "FootMenu for Screen %s: going to call '%s'", self._screen.name, cb
        )
        cb(opt[self.OPT_OPT])


class BCMView(Screen):
    """
    Views and controls Battery Capacity Meter modules.

    Attributes:

        bci: Set from the ``bci`` arg to `__init__` as a `BatteryController`
            instance.

        _bat_id_cnt: Counter to be used to make unique battery IDs.

            Gets incremented every time we change a battery. Used when calling
            `genBatteryID` and updated from the return value.

        bat_id_input: A `FieldEdit` input screen to set the Battery ID.

            This screen will get focus when it is detected that a battery was
            inserted but the `bci` does not have a battery ID
            (`BatteryController.bat_id`) set.

            A default ID will be generated using `genBatteryID()` and the user
            will be able to modify this if this is for a Battery that already
            has an ID for example. Once ``OK`` is selected on this screen, the
            setter, `_setBatID` will be called to update the battery ID for
            `bci`.

        _foot_menu: Will be a `FootMenu` instance or None.

            When a battery has been inserted a `FootMenu` is dynamically defined in the
            `_stBatIns()` and assigned to this instance variable. This will
            allow selecting to start charging or discharging on that view.

            Another dynamic `FootMenu` will be defined when we are currently
            charging or discharing. This will be to either stop the current
            activity or exit the screen to go to another BCMView.

            If we are not in any of these states, this variable will be
            ``None`` to indicate no footer menu is currently active.

            When active, the `actCCW()`, `actCW()` and `actShort()` encoder
            event methods will call the respective methods as needed on this
            instance.
    """

    # The auto refresh rate
    AUTO_REFRESH = 500

    def __init__(self, name: str, px_w: int, px_h: int, bci: BatteryController):
        """
        Overrides base init.

        Args:
            name, px_w, px_h:  See `Screen` base class documentation.
            bci: `BatteryController` instance to control and monitor.
        """
        super().__init__(name, px_w, px_h)
        self.bci: BatteryController = bci
        self._bat_id_cnt: int = 0
        self._foot_menu: FootMenu | None = None

    def _passFocus(self, screen: "Screen" | None, return_to_me: bool = False):
        """
        Overrides the base method so we can do some house keeping on loosing
        focus.

        Tasks we do currently:
            * Reset `_foot_menu` to None to ensure we have no loose hanging
                menu on screen that is not in focus anymore. The various update
                flows will ensure to recreate this menu again when needed after
                we receive focus again.
        """
        self._foot_menu = None
        super()._passFocus(screen, return_to_me)

    def _showHeader(self):
        """
        Shows the current BCM name as a header at the top of the screen
        """
        header = f"{self.name:^{self._max_cols}}"
        self._display.text(header, 0, 0, 1)
        self._invertText(0, 0)

    def _setBatID(self, val, _):
        """
        Called to set the ID for the currently inserted battery.

        This is the `FieldEdit._setter` callback for the `bat_id_input` screen.
        We do not use the ``field_id`` for this field entry screen and thus has
        this args set as ``_``.
        """
        self.bci.bat_id = val.decode("utf-8")
        logging.info("Screen %s: Setting battery ID to: %s", self.name, self.bci.bat_id)

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

        # Show the battery ID if we have one
        if self.bci.bat_id:
            label = "B_ID:"
            id_w = self._max_cols - len(label)
            self._display.text(
                f"{label}{self.bci.bat_id:>{id_w}.{id_w}}", 0, 1 * self.FONT_H, 1
            )

        # Call our base to setup the auto refresher task
        super().setup()

    def _stUnknown(self):
        """
        Handles updating the screen for the ST_UNKNOWN state.

        We only display a message to indicate the state is unknown, and will be
        updated once it is known again.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        self.text(
            "Unknown battery status. Waiting for it become known...", fmt="w^", y=2
        )
        self._show()

    def _stNoBat(self):
        """
        Handles updating the screen for the ST_NOBAT state.

        We only display a message to indicate that we are waiting for a battery
        to be inserted.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        self.text("Waiting for battery to be inserted...", fmt="w^", y=2)
        self._show()

    def _stBatIns(self):
        """
        Handles updating the screen when the `bci` ``state`` is
        `BatteryController.ST_BATINS`.

        On this screen, if we do not yet have a battery ID (``bat_id`` from
        `bci`) for the currently inserted battery, then we first create a
        `FieldEdit` screen to get the battery ID, and then pass focus to this
        screen.

        This screen will callback to `_setBatID()` to set the battery ID. Once
        this is done and a battery ID is available, we will display the current
        battery voltage and show a `FootMenu` to allow selecting to charge or
        discharge the battery, or exit the screen.
        """
        # We do not have a battery ID yet. Deal with that first.
        if self.bci.bat_id is None:
            # Generate a new battery ID, using our counter value, and update
            # the counter value from the result.
            b_id, self._bat_id_cnt = genBatteryID(self._bat_id_cnt)
            # Create a new FieldEdit screen to enter the battery ID
            bat_id_input = FieldEdit(
                "Bat ID",
                self.px_w,
                self.px_h,
                max_len=11,
                val=b_id,
                f_type="num",
                setter=self._setBatID,
            )
            # # Set the new Battery ID, and then pass focus to the Battery ID
            # # FieldEdit screen in self.bat_id_input
            # self.bat_id_input.setVal(b_id)
            self._passFocus(bat_id_input, return_to_me=True)
            return

        # We have the battery ID.
        # We clear only the active bit of the screen, leaving the header,
        # battery ID, and footer menu if it is already there.
        self._clear(header_lns=2, footer_lns=2)

        # Have we created the footer menu yet?
        if self._foot_menu is None:
            logging.info("Creating and showing footer menu for ST_BATINS state.")
            # Create the footer menu, and draw it
            self._foot_menu = FootMenu(
                self,
                [
                    ("Ch", "Start Charge"),
                    ("Dch", "Start Discharge"),
                    ("Exit", "Exit Screen"),
                ],
                self.footMenuCB,
            )
            self._foot_menu.drawMenu()

        # Get the current status
        status = self.bci.status()

        # Show the current battery voltage
        bv = f"BV: {int(status['bat_v']):>{self._max_cols-6}d}mV"
        self.text(bv, fmt="", y=3)

        self._show()

    def _stChargeDisCharge(self):
        """
        Handles updating the screen when the `bci` ``state`` is
        `BatteryController.ST_CHARGING` or `BatteryController.ST_DISCHARGING`.

        Here we will display the current battery voltage, charge/discharge
        current and charge and time.

        A `FootMenu` will be available to allow stopping the charge/discharge,
        or exit the screen.
        """
        # Are we charging?
        charging = self.bci.charge()

        # We clear only the active bit of the screen, leaving the header,
        # battery ID, and footer menu if it is already there.
        self._clear(header_lns=2, footer_lns=2)

        # Have we created the footer menu yet?
        if self._foot_menu is None:
            logging.info(
                "Creating and showing footer menu for ST_CHARGING/ST_DISCHARGING state."
            )
            # Create the footer menu, and draw it
            self._foot_menu = FootMenu(
                self,
                [
                    ("Stop", f"Stop {'Charge' if charging else 'Discharge'}"),
                    ("Exit", "Exit Screen"),
                ],
                self.footMenuCB,
            )
            self._foot_menu.drawMenu()

        # Get the current status
        status = self.bci.status()

        # We show discharging with negative values and charging with positive
        # values. This is only to make it easier to distinguish between the
        # charge and discharge views.
        multiplier = 1 if charging else -1

        # Show the current battery voltage
        ln = f"BV: {int(status['bat_v']):>{self._max_cols-6}d}mV"
        self.text(ln, fmt="", y=2)

        val = int(status["ch_c" if charging else "dch_c"]) * multiplier
        ln = f"A: {val:>{self._max_cols-5}d}mA"
        self.text(ln, fmt="", y=3)

        val = int(status["ch" if charging else "dch"]) * multiplier
        ln = f"CH: {val:>{self._max_cols-7}d}mAh"
        self.text(ln, fmt="", y=4)

        secs = int(status["ch_t" if charging else "dch_t"])
        mins, secs = divmod(secs, 60)
        hrs, mins = divmod(mins, 60)
        val = f"{hrs:02d}H{mins:02d}:{secs:02d}"
        ln = f"T: {val:>{self._max_cols-3}}"
        self.text(ln, fmt="", y=5)

        self._show()

    def update(self):
        """
        Updates the display.
        """
        # Get the current status
        state = self.bci.state

        # If the status is Unknown, we do not know what to do
        if state == BatteryController.ST_UNKNOWN:
            self._stUnknown()
            return

        # Are we waiting for a battery to be inserted?
        if state == BatteryController.ST_NOBAT:
            self._stNoBat()
            return

        if state == BatteryController.ST_BATINS:
            self._stBatIns()
            return

        if state in (BatteryController.ST_CHARGING, BatteryController.ST_DISCHARGING):
            self._stChargeDisCharge()
            return

        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=2)
        self.text(f"Don't know how to handle sate: {state}", fmt="w^", y=3)
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

    def actCCW(self):
        """
        Overrides the base counter-clockwise encoder rotation event.

        We override this so that we can update any footer menu selection
        (`_foot_menu`) on encoder rotation. If no footer menu is active
        currently, we pass the call up to the parent.
        """
        if self._foot_menu is None:
            super().actCCW()
            return

        logging.info("Screen %s: Selecting previous footer menu option.", self.name)
        self._foot_menu.selectNext(-1)

    def actCW(self):
        """
        Overrides the base clockwise encoder rotation event.

        We override this so that we can update any footer menu selection
        (`_foot_menu`) on encoder rotation. If no footer menu is active
        currently, we pass the call up to the parent.
        """
        if self._foot_menu is None:
            super().actCW()
            return

        logging.info("Screen %s: Selecting next footer menu option.", self.name)
        self._foot_menu.selectNext(1)

    def actShort(self):
        """
        Overrides the base short press event.

        We override this so that we can activate the currently selected footer
        menu option (`_foot_menu`) on short press. If no footer menu is active
        currently, we pass the call up to the parent.
        """
        if self._foot_menu is None:
            super().actShort()
            return

        logging.info("Screen %s: Activating selected footer menu option.", self.name)
        self._foot_menu.activate()

    def footMenuCB(self, opt: str):
        """
        Footer menu callback function.

        This is a callback set for any dynamic `FootMenu` instances we set up
        (see `_foot_menu`) for any running state.

        Currently it only handles the footer menu when
        charging/discharging/exit can be selected on the view handled by
        `_stBatIns()`.

        When called, `_foot_menu` will be set to ``None`` to effectively
        disable the footer menu since an option has now been selected.

        If the ``opt`` is ``"Exit"``, then we exit the current Screen by doing
        a call to `actShort()`, effectively simulating a short press to exit
        the screen.

        For the ``"Ch"`` and ``"Dch"`` options, we start charging or
        discharging respectively via a call to the appropriate `bci` method.

        Args:
            opt: The foot menu option string that was active when the option
                was selected.
        """

        # First thing to do is unset the current footer menu
        self._foot_menu = None

        # Are we exiting?
        if opt == "Exit":
            # Simulate the exit by calling the shortpress now that _foot_menu
            # is None.
            self.actShort()

        if opt == "Ch":
            # Switch charging on
            self.bci.charge(True)
        elif opt == "Dch":
            # Switch discharging on
            self.bci.discharge(True)
        elif opt == "Stop":
            # Stop charging/dischargin
            if self.bci.charge():
                self.bci.charge(False)
            else:
                self.bci.discharge(False)
        else:
            logging.info("Received invalid option from footer menu: %s", opt)


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
