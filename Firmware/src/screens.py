"""
All screen and UI related functionality.

Attributes:
    Q1: Bit definition for drawing an ellipse_ in quadrant 1, top right
    Q2: Bit definition for drawing an ellipse_ in quadrant 2, bottom right
    Q3: Bit definition for drawing an ellipse_ in quadrant 3, bottom left
    Q4: Bit definition for drawing an ellipse_ in quadrant 4, top left
    NET_CONF: A menu structure for a `Menu` screen to allow updating some
        network configs in the `net_conf` module.

        Each entry is a tuple of these fields (see `Menu`):

        * The menu entry name to display
        * The function to call when the option is selected, always
          `updateConfig` in this case,
        * The module name (`net_conf`) in which the config constant resides
        * The actual config constant name since we have more human readable
          menu entry names
        * The field type as name from `FieldEdit.F_TYPES` - defaults to "num"
          if not supplied.

    RUNTIME_CONF: A menu structure for a `Menu` screen to allow updating some
        configs in the `config` module.

        Each entry is a tuple of these fields (see `Menu`):

        * The menu name to display - we simply use the config constant names
          here. Not too user friendly, but the screen limitation makes it
          difficult to use a human readable menu name here.
        * The function to call when the option is selected, always
          `updateConfig` in this case,
        * The module name (`config`) in which the config constant resides

        Note: These fields are all numeric types, so we do not pass a field
        type arg as we do for `NET_CONF` since the default is the numeric field
        type.


.. _ellipse:
    https://docs.micropython.org/en/latest/library/framebuf.html#framebuf.FrameBuffer.ellipse
"""

# We do have much to do here, so
# @pylint: disable=too-many-lines

import gc
from micropython import const
from machine import Pin
from ssd1306 import SSD1306_I2C
from lib import ulogging as logging
from lib.bat_controller import BatteryController
from ui import (
    Screen,
    setupEncoder,
    input_evt,
    Menu,
    FieldEdit,
)
from config import (
    i2c,
    ENC_CLK,
    ENC_DT,
    ENC_SW,
    OLED_ADDR,
    OLED_W,
    OLED_H,
)
import config
import net_conf
from sitelocal_conf import updateLocal

# from interface import MODE_CHARGING, MODE_DISCHARGING
from version import VERSION

# These are constants defining the ellipses quadrants to draw
# There are 4 quadrants from Q1 to Q4 starting in the top right
# going around counter-clockwise
Q1 = const(0b0001)
Q2 = const(0b0010)
Q3 = const(0b0100)
Q4 = const(0b1000)


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


class Calibration(Screen):
    """
    Calibration Screen.

    This screen is used to adjust the shunt resistor used for ``charge`` or
    ``discharge`` current calculations. The idea is that a multimeter is
    connecting in series with the battery and set to current monitoring.

    The shunt resistor is then adjusted on screen until the calculated current
    matches the current displayed on the multimeter.

    This screen provides the following:

    * Show a short help message on startup with a footer menu listing all
      available BCs that can be calibrated, and an ``Exit`` menu option.
    * Only BCs that have a battery inserted, but no ID has been set for it yet,
      can be calibrated.
    * Once a BC is selected, the calibration selection screen is displayed.
    * This is also a screen with a quick help message, and then a footer
      menu to select ``charge`` or ``discharge`` calibration, with an
      ``Exit`` option to return to the BC selection screen.
    * Once the calibration option is selected, the screen changes to
      display the current **shunt** resistor value, as well as the current
      charge or discharge current.
    * Rotating the encoder will adjust the shunt resistor value by 0.1Ω
      increments and the dis/charge current will auto update to based on
      the shunt value change.
    * The display and multimeter currents are compared until the display
      matches the multimeter.

    Attributes:

        AUTO_REFRESH: Sets the auto refresh rate for the screen.

        S_SEL_BC: State: Selecting a BC to calibrate
        S_SEL_CALIB: State: Selecting to calibrate charging or discharging
        S_CALIB: State: Busy calibrating

        C_CH: Indicator that charge calibration is in progress
        C_DCH: Indicator that discharge calibration is in progress

        _bcms: Set to the list `BatteryController` instances received in
            `__init__`.
        _state: The current calibration state. One of `S_SEL_BC`, `S_SEL_CALIB`
            or `S_CALIB`
        _foot_menu: The `FootMenu` currently in operation, or None if no footer
            menu is currently active.
        _cal_opt: The current calibration option. One of `C_CH` or `C_DCH`
        _bc: The current `BatteryController` selected for calibration, or
            ``None`` if not selected yet.
        _curr_mon: Pointer to `BatteryController._ch_mon` or
            `BatteryController._dch_mon` for the BC set in `_bc`.

            This is set as a shortcut to this current monitor while in
            calibration mode.

        _shunt_row: The display row on which to put the shunt value display
            while in calibration mode.
    """

    # pylint: disable=too-many-instance-attributes

    # Refresh every 200 millis
    AUTO_REFRESH = 200

    # Various internal states
    S_SEL_BC = 0  # Select BC
    S_SEL_CALIB = 1  # Select what to calibrate
    S_CALIB = 2  # Calibration in progress

    # Current calibration option
    C_CH = 0  # Charge calibration
    C_DCH = 1  # Discharge calibration

    def __init__(self, name: str, px_w: int, px_h: int, bcms: list[BatteryController]):
        """
        Overrides base init.

        Args:
            name, px_w, px_h:  See `Screen` base class documentation.
            bcms: List of `BatteryController` instance to calibrate.
        """
        super().__init__(name, px_w, px_h)

        self._bcms = bcms

        self._state: int = self.S_SEL_BC
        self._foot_menu: FootMenu | None = None
        self._cal_opt: int | None = None
        self._bc: BatteryController | None = None
        self._curr_mon: "CurrentMonitor" | None = None
        self._shunt_row = 2

    def _setupSelectBC(self):
        """
        Called to set up for selecting the BC to calibrate.

        This method will clear the screen, show the BC selection help text and
        set up the footer menu to select the BC.

        It will also set the `_state` to `S_SEL_BC`.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        self.text("Select the BC with battery to calibrate", "w^", 0, 2)

        # Only add BCs that have a battery inserted but have not set an ID yet
        opts = [
            (str(i), f"Calibrate {bc.name}")
            for i, bc in enumerate(self._bcms)
            if bc.state == bc.S_GET_ID
        ]
        opts.append(("Exit", "Exit calibration"))
        # Set up the footer menu
        self._foot_menu = FootMenu(
            self,
            opts,
            self.footMenuCB,
        )
        self._foot_menu.drawMenu()

        self._state = self.S_SEL_BC

    def _setupSelectCalibrate(self):
        """
        Called to set up for selecting the calibration option.

        This method will clear the screen, show the calibration selection help
        text and set up the footer menu to select the calibration option.

        It will also set the `_state` to `S_SEL_CALIB`.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        self.text("Select calibration option.", "w^", 0, 2)

        # Only add BCs that have a battery inserted but have not set an ID yet
        opts = [
            ("Ch", "Charging"),
            ("DCh", "Discharging"),
            ("Exit", "Exit calibration"),
        ]
        # Set up the footer menu
        self._foot_menu = FootMenu(
            self,
            opts,
            self.footMenuCB,
        )
        self._foot_menu.drawMenu()

        self._state = self.S_SEL_CALIB

    def _setupCalibration(self):
        """
        Sets up for calibration.

        This method will clear the screen, show the shunt label and resistor
        value, as well as the the dis/charge current label.

        It will then switch on charging or discharging as required and set the
        `_state` to `S_CALIB`.

        From here the `update` method will update the shunt and current values.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        # Set a pointer to the correct charge/current monitor in the selected
        # BC for easier access
        self._curr_mon = getattr(
            self._bc, "_ch_mon" if self._cal_opt == self.C_CH else "_dch_mon"
        )

        # Instructions at the bottom of the display.
        self.text("Rotate to change, press to save.", "w<", 0, self._max_rows - 2)

        # The shunt and current display
        self.text(f"Shunt: {self._shunt}", "<", 0, self._shunt_row)
        self.text("Curnt: ", "<", 0, self._shunt_row + 1)

        # Start charging or discharing
        self._bc._cdControl(
            state=True, ch=self._cal_opt == self.C_CH, dch=self._cal_opt == self.C_DCH
        )

        self._state = self.S_CALIB

    @property
    def _shunt(self):
        """
        Property to return the shunt resistor value for the BC being calibrated.

        We get the shunt value from `_curr_mon` which is set up in
        `_setupCalibration`.

        Returns:
            The shunt resistor value or None if `_curr_mon` is ``None``.
        """
        if self._curr_mon is None:
            return None

        # It's OK to access the private value here @pylint: disable=protected-access
        return self._curr_mon._shunt

    @_shunt.setter
    def _shunt(self, val: int | float):
        """
        Setter for the current BC's charge monitor shunt value.

        Note:
            This is an adjuster for the current shunt, and not an absolute
            value setter. The ``val`` passed in will be added to the current
            shunt value, thus adjusting it either up or down (when ``val`` is
            negative)

        Args:
            val: A positive or negative integer or float by which to adjust the
                shunt value
        """
        self._curr_mon._shunt += val
        # We can not let this value go equal to or below zero
        if self._shunt <= 0:
            logging.error("Screen %s: Shunt value can not go below zero.", self.name)
            # Return to previous
            self._curr_mon._shunt -= val

    def _saveCalibration(self):
        """
        Save the value that have now been calibrated.

        This function will import `shunt_conf`, then use the ``name`` attribute
        of the current BC (`_bc`) and whether we are calibrating charging or
        discharging, to construct the shut resistor config name as:

            BCn_CH_R   # Charge calibration

        or

            BCn_DCH_R  # Discharge calibration

        where ``BCn`` comes from the `_bc` ``name`` attribute.

        This config variable is then set to the current `_shunt` value in
        `shunt_conf`, after which `sitelocal_conf.updateLocal` is called to
        save this shunt config value to a site local config file.

        These saved values will then later be applied when constructing
        `config.HARDWARE_CFG` from imports from `shunt_conf` and this site
        local config file.
        """
        try:
            # We only import these when needed
            # pylint: disable=import-outside-toplevel
            import shunt_conf
            from sitelocal_conf import updateLocal

            # Build up the config value based on how it is expected in
            # shunt_conf.py
            conf_name = (
                f"{self._bc.name}_{'D' if self._cal_opt == self.C_DCH else ''}CH_R"
            )

            setattr(shunt_conf, conf_name, self._shunt)

            updateLocal(conf_name, shunt_conf)
        except Exception as exc:
            logging.error(
                "Screen %s: Error saving local calibrated shunt.  Error: %s",
                self.name,
                exc,
            )
            return

        logging.info(
            "Screen %s: Saved calibration %s=%s to site local shunt_conf_local.py",
            self.name,
            conf_name,
            self._shunt,
        )

    def setup(self):
        """
        Set the screen up.

        This method is called on first initializing the screen.

        It clears the screen, adds a header and goes into the BC selection
        state by calling `_setupSelectBC`.
        """
        self._clear()
        # Show the Screen name centered in line 0
        self.nameAsHeader(fmt="^")
        self._invertText(0, 0)

        self._setupSelectBC()

        self.update()

        # Call out base's setup to auto start a task for auto refreshing the
        # display - this task will be exited once we loose focus
        super().setup()

    def update(self):
        """
        Continuously updates the display.

        While in the calibration `_state` (`S_CALIB`), this method will update
        the battery current and shunt value display on every call.
        """
        # Update values when calibrating
        if self._state == self.S_CALIB:
            # Clear the block to the right of the labels. The X pos is
            # hardcoded here since it's a fairly fixed width.
            self._display.rect(
                6 * self.FONT_W,
                self._shunt_row * self.FONT_H,
                self._display.width - 6 * self.FONT_W,
                (self._shunt_row + 1) * self.FONT_H,
                0,
                True,
            )
            # Update shunt value
            self._display.text(
                f"{self._shunt:0.1f} ohm",
                7 * self.FONT_W,
                self._shunt_row * self.FONT_H,
                1,
            )
            # Update current value
            self._display.text(
                f"{self._curr_mon.current} mA",
                7 * self.FONT_W,
                (self._shunt_row + 1) * self.FONT_H,
                1,
            )

        self._show()

    def actCCW(self):
        """
        Overrides the base counter-clockwise encoder rotation event.

        We override this so that we can update the shunt value (`_shunt`) or
        any footer menu selection (`_foot_menu`) on encoder rotation.

        If in `S_CALIB` `_state`, we subtract 0.1Ω from the `_shunt`, else if
        `_foot_menu` is active, we update the selected option.

        If no footer menu is active, we pass the call up to the parent.
        """
        # When we're calibrating CCW rotation decreases the shunt value by one
        if self._state == self.S_CALIB:
            self._shunt = -0.10
            # Update immediately to give instant feedback
            self.update()
            return

        if self._foot_menu is None:
            super().actCCW()
            return

        logging.info("Screen %s: Selecting previous footer menu option.", self.name)
        self._foot_menu.selectNext(-1)

    def actCW(self):
        """
        Overrides the base clockwise encoder rotation event.

        We override this so that we can update the shunt value (`_shunt`) or
        any footer menu selection (`_foot_menu`) on encoder rotation.

        If in `S_CALIB` `_state`, we add 0.1Ω to the `_shunt`, else if
        `_foot_menu` is active, we update the selected option.

        If no footer menu is active, we pass the call up to the parent.
        """
        # When we're calibrating CW rotation increases the shunt value by one
        if self._state == self.S_CALIB:
            self._shunt = 0.10
            # Update immediately to give instant feedback
            self.update()
            return

        if self._foot_menu is None:
            super().actCW()
            return

        logging.info("Screen %s: Selecting next footer menu option.", self.name)
        self._foot_menu.selectNext(1)

    def actShort(self):
        """
        Overrides the base short press event.

        We override this so that we can save the updated shunt value or
        select the current footer menu selection if a footer is active.

        If in `S_CALIB` `_state`, we save the current shunt value, else if
        `_foot_menu` is active, we select the current option.

        If no footer menu is active, we pass the call up to the parent.
        """
        # If we're calibrating, this click means we are exiting.
        if self._state == self.S_CALIB:
            logging.info("Screen %s: Completed calibration.", self.name)
            # Switch off both charge and discharge controllers.
            # It's OK to use _cdControl here @pylint: disable=protected-access
            self._bc._cdControl(state=False, ch=True, dch=True)

            # Save the calibrated value
            self._saveCalibration()

            # Reset the current monitor pointer and return to selecting the
            # option to calibrate
            self._curr_mon = None
            self._setupSelectCalibrate()
            return

        if self._foot_menu is None:
            super().actShort()
            return

        logging.info("Screen %s: Activating selected footer menu option.", self.name)
        self._foot_menu.activate()

    def actLong(self):
        """
        Overrides the base long press event.

        We override this so that we can unset the foot menu, and then call up
        to the super.

        If in `S_CALIB` `_state`. we ignore this long press.
        """
        # Ignore this if we're busy calibrating
        if self._state == self.S_CALIB:
            logging.error(
                "Screen %s: Ignoring long press while calibrating.", self.name
            )
            return

        self._foot_menu = None
        super().actLong()

    def footMenuCB(self, opt: str):
        """
        Footer menu callback function.

        This is a callback set for any dynamic `FootMenu` instances we set up
        (see `_foot_menu`) for any running state.

        When called, `_foot_menu` will be set to ``None`` to effectively
        disable the footer menu since an option has now been selected.

        If the ``opt`` is ``"Exit"``, then we exit the current Screen by doing
        a call to `actShort()`, effectively simulating a short press to exit
        the screen.

        For all other options we call the appropriate handler, sometimes also
        based on the state. See the code for more details.

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
            return

        # We deal with opt value differently depending on the state we're in
        if self._state == self.S_SEL_BC:
            # The opt value is an index into self._bcms, but is a string.
            # Convert to int and set pointer to local BC being used
            self._bc = self._bcms[int(opt)]
            logging.info(
                "Screen %s: Going to calibrate BC: %s",
                self.name,
                self._bc.name,
            )

            self._setupSelectCalibrate()
            return

        # We're in the calibration selection state, with one of the calibration
        # options selected.
        self._cal_opt = self.C_CH if opt == "Ch" else self.C_DCH
        self._setupCalibration()


def updateConfig(
    conf_name, screen, conf_mod, const_name=None, f_type="num", reboot=False, *args
):
    """
    Function that will be called from he `NET_CONF` and `RUNTIME_CONF` menu
    entries to set some local config value.

    When called, we will use the ``conf_mod`` name as the config module in
    which the ``conf_name`` (or ``const_name``) needs to be set. We will check
    if the config constant exists in the correct module, get the current config
    value and then dynamically create a `FieldEdit` instance to update the
    value.

    If any of these checks fails, an error will be logged, and the user will
    not see anything happening on the screen.

    Due to the screen constrains, some of the config menu names are too long to
    fit, so they will be truncated.

    We will ask the ``screen`` (the `Menu` instance we were called from) to
    pass focus to the new `FieldEdit` instance, and arrange for focus to go
    back to the ``screen`` instance when the field editor exits.

    Once the field has been updated and the user selects **OK** to save it, we
    use the `sitelocal_conf` framework built into the `config` and `net_conf`
    modules to save the constant in a local runtime config file on the device.

    .. warning::

        When updating an attribute directly in a module, any other objects that
        have imported that module by name will see the update.

        If however, the attribute was imported directly from the module, then
        updating it in the module will not update the directly imported value.

        This may cause a number of strange situations depending on how
        different modules access imported config values. Best would be a
        restart after updating config values.

        We may use the ``reboot`` option for that later.

    Args:
        conf_name: This will be the menu name for this config option. If the
            ``const_name`` arg is None, then this is used as the config constant
            name in the config module to set.
        screen: This is the `Screen` or rather `Menu` instance that we were
            called from. We will create our own `FieldEdit` `Screen`, and then
            as our called screen to pass focus to the new `FieldEdit` screen.
            Also arranging for this ``screen`` to receive focus again when the
            `FieldEdit` screen exits.
        conf_mod: The Python module in which the config option resides. This
            can only be one one of `config` or `net_conf` for now. This means
            that any config constant in these modules can be updated
            dynamically from a menu entry.
        const_name: If the ``conf_name``, i.e the menu entry string, is not the
            name of the config constant in the ``conf_mod`` module to update,
            then pass the actual constant name in this arg.
        f_type: Any of the `FieldEdit.F_TYPES` names to use for the field type.
        reboot: Not used currently, but may be used to indicate that a reboot
            is needed for the change to take effect. May be implemented later.
        args: This is a catchall since the `menu` callback function can allow
            any number of args to be added. Not used in this case.


    """  # pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument,keyword-arg-before-vararg
    if conf_mod == "config":
        rt_conf = config
    elif conf_mod == "net_conf":
        rt_conf = net_conf
    else:
        logging.error("updateConfig: Not a valid config module name: %s", conf_mod)
        return

    if const_name:
        conf_name = const_name

    logging.info("updateConfig: Config update request for config: '%s'", conf_name)

    # Make sure the config option is an attribute of config.
    if not hasattr(rt_conf, conf_name):
        logging.error(
            "updateConfig: No config constant named '%s' in module '%s' "
            "to update the value for.",
            conf_name,
            conf_mod,
        )
        return

    def setConfigVal(val: bytearray, _):
        """
        Saves the new value.

        Args:
            val: The updated value. This is a ``bytearray``, and for now we
                expect all values to be integers, so we need to convert it to int.
            _: This is the ignored field ID from the menu.
        """
        if f_type == "num":
            try:
                val = int(val)
            except Exception as ex:
                logging.error(
                    "updateConfig: Error converting %s to int for setting the "
                    "`%s.%s' config value. Error: %s",
                    val,
                    conf_mod,
                    conf_name,
                    ex,
                )
                return

        logging.info(
            "updateConfig: Setting site local config: %s.%s=%s",
            conf_mod,
            conf_name,
            val,
        )

        # Update in the module - NOTE this does not update any directly
        # imported attributes!
        setattr(rt_conf, conf_name, val)

        # Now save it as a site local
        updateLocal(conf_name, rt_conf)

    # Create a new FieldEdit screen to update the setting
    conf_editor = FieldEdit(
        conf_name,
        screen.px_w,
        screen.px_h,
        val=getattr(rt_conf, conf_name),
        f_type=f_type,
        setter=setConfigVal,
    )
    # Pass focus to the field editor
    # pylint: disable=protected-access
    screen._passFocus(conf_editor, return_to_me=True)


# Network config menu structure
NET_CONF = (
    ("WiFi SSID", updateConfig, "net_conf", "SSID", "Alnum"),
    ("WiFi Passwd", updateConfig, "net_conf", "PASS", "Alnum"),
    ("MQTT Host", updateConfig, "net_conf", "MQTT_HOST", "Alnum"),
    ("MQTT Port", updateConfig, "net_conf", "MQTT_PORT"),
    ("DHCP Hostname", updateConfig, "net_conf", "HOSTNAME", "alpha"),
    ("Back", None),
)

# All config options we allow updating at runtime and setting locally.
RUNTIME_CONF = (
    ("C_VOLTAGE_TH", updateConfig, "config"),
    ("D_VOLTAGE_TH", updateConfig, "config"),
    ("D_V_RECOVER_TH", updateConfig, "config"),
    ("D_RECOVER_MAX_TM", updateConfig, "config"),
    ("D_RECOVER_TEMP", updateConfig, "config"),
    ("D_RECOVER_MIN_TM", updateConfig, "config"),
    ("TELEMETRY_EMIT_FREQ", updateConfig, "config"),
    ("SOC_REST_TIME", updateConfig, "config"),
    ("SOC_NUM_CYCLES", updateConfig, "config"),
    ("Back", None),
)


class BCMView(Screen):
    """
    Views and controls Battery Capacity Meter modules.

    This screen will be used to monitor and control all available
    `BatteryController` instances.

    One instance is active at any time and a **long press** is used to cycling
    between the available instances.

    The screen will update as the underlying `BCStateMachine.state` changes.
    For example when no battery is inserted, the screen will show a message to
    this effect, then when the battery is inserted it will update to ask for
    the battery ID to be entered, and after that it will allow the battery to be
    tested, charged, discharged, etc. via a footer menu.

    Cycling between `BatteryController` instances leaves the non-visible
    controllers to continue where they were when they were active. On
    activating a controller it will just continue where it left off, or more
    precisely, display the current controller state.

    The screen can be exited by the ``Exit`` option on any footer menu, or by a
    single click if no footer menu is available.

    Some sample screens:

    .. image:: ../../Firmware/ScreenDesign/OLED128x64_BatIns_State_larger.gif

    Animated footer menu with a battery inserted in the controller with the name
    **BC0**

    .. image:: ../../Firmware/ScreenDesign/OLED128x64_Charge_State_large.gif

    Animation of the charge in progress screen.

    .. image:: ../../Firmware/ScreenDesign/OLED128x64_Disharge_Complete_larger.png

    The screen when charging is complete.

    Attributes:

        AUTO_REFRESH: Overrides the base `Screen.AUTO_REFRESH` for delay
            between screen updated for this `Screen`

        _bcms: List of `BatteryController` instances to manage. This is from
            the ``bcms`` arg to `__init__`

        _active_bcm: Index into `_bcms` of the active BCM being viewed.

        _bc: The current active `BatteryController` being managed.

            This is a convenience access to ``self._bcms[self._active_bcm]``
            and is set by calls to `_activateBCM()`

        _foot_menu: Will be a `FootMenu` instance or None.

            The footer menu is dynamically defined depending on the screen
            we're on. It allows actions and navigation per screen.

        _last_state: Holds the last `BCStateMachine.state` for `_bc`.

            This is used in the `update` method to detect if there was a state
            change from the last to the current screen update.

    """

    # The auto refresh rate
    AUTO_REFRESH = 500

    def __init__(self, name: str, px_w: int, px_h: int, bcms: list[BatteryController]):
        """
        Overrides base init.

        Args:
            name, px_w, px_h:  See `Screen` base class documentation.
            bcms: List of `BatteryController` instance to control and monitor.
        """
        super().__init__(name, px_w, px_h)
        self._bcms: list[BatteryController] = bcms
        self._active_bcm: int | None = None
        self._bc: BatteryController | None = None
        self._foot_menu: FootMenu | None = None
        self._last_state: int = -1

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
        Shows the current `BCStateMachine.name` as a header at the top of
        the screen and the battery ID if available.

        This header is shown inverted.
        """
        # We are at time called to update the heade without having cleared the
        # screen. In this case, if we do not always clear the header first, the
        # invert further down is going to mess thngs up. So always clear the
        # header line
        self._display.fill_rect(0, 0, self.px_w, self.FONT_H, 0)

        header = f"{self._bc.name:^{self._max_cols}}"
        self._display.text(header, 0, 0, 1)
        self._invertText(0, 0)

        # Show the battery ID if we have one
        if self._bc.bat_id:
            label = "B_ID:"
            id_w = self._max_cols - len(label)
            self._display.text(
                f"{label}{self._bc.bat_id:>{id_w}.{id_w}}", 0, 1 * self.FONT_H, 1
            )

        # If we are in a SoC measure state, add some SoC info
        if self._bc.soc_m and self._bc.soc_m.in_progress:
            self.text("#", x=0, y=0, color=0)
            cyc = f"{self._bc.soc_m.cycle}/{self._bc.soc_m.cycles}"
            self.text(cyc, x=self._max_cols - len(cyc), y=0, color=0)

    def _activateBCM(self, idx: int | str):
        """
        Called to change the view to a new BCM in the list of `_bcms` we manage.

        Args:
            idx: An index into `_bcms` for the one to select and make active.
                To make it easier cycle through the available BCMs, this can
                also be the characters '>' or '<' to mean select next or
                previous BCM respectively.
        """
        # Validate idx
        if idx in ("<", ">"):
            idx = self._active_bcm + (-1 if idx == "<" else 1)
            # Wrap around?
            if idx < 0:
                idx = len(self._bcms) - 1
            elif idx >= len(self._bcms):
                idx = 0

        if not isinstance(idx, int):
            logging.error("Screen %s: invalid bcm index to set: %s", self.name, idx)
            return

        # Make it active
        self._active_bcm = idx
        self._bc = self._bcms[self._active_bcm]

        # Set up the screen.
        self._clear()
        self._showHeader()

        self._show()

    def setup(self):
        """
        Override `Screen.setup` so we can do some local setup first.
        """
        # Only activate the first BCM if we do not already have one that is
        # active. This is needed when we return from subscreens or from the
        # parent menu.
        if self._active_bcm is None:
            self._activateBCM(0)
        else:
            self._clear()
            self._showHeader()

        # Call our base to setup the auto refresher task
        super().setup()

        self._show()

    def _stDisabled(self):
        """
        Handles updating the screen for the `BCStateMachine.S_DISABLED` state.

        We only display a message to indicate that we are disabled.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        # The .text method does not handle newlines for an open line before
        # the last line, so we improvise.
        msg = ["Controller", "disabled.", "", "Press=Exit", "LongPress=Next"]
        for l, m in enumerate(msg, 2):
            self._display.text(f"{m:^{self._max_cols}s}", 0, l * self.FONT_H, 1)
        self._show()

    def _stNoBat(self):
        """
        Handles updating the screen for the `BCStateMachine.S_NOBAT` state.

        We only display a message to indicate that we are waiting for a battery
        to be inserted.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        self.text("Waiting for battery to be inserted...", fmt="w^", y=2)
        self.text("Press=Exit", fmt="w^", y=6)
        self.text("LongPress=Next", fmt="w^", y=7)
        self._show()

    def _setBatID(self, val: bytearray, _):
        """
        Callback for the `FieldEdit` screen set up in `_stGetID` to enter
        or update the battery ID.

        Args:
            val: The final ID value
            _: Ignored field ID received from caller.
        """
        if self._bc.setID(val.decode("ascii")):
            logging.info(
                "Screen %s: Battery ID was set to: %s", self.name, self._bc.bat_id
            )
        else:
            logging.error(
                "Screen %s: Error setting battery ID.", self.name, self._bc.bat_id
            )

    def _stGetID(self):
        """
        Handles updating the screen for the `BCStateMachine.S_GET_ID` state.

        When we get here, the `BatteryController` has already created a default
        ID for the newly inserted battery, and this state is there to either
        confirm or change this default ID.

        We dynamically create a `FieldEdit` screen here, passing in the default
        battery ID for editing.

        The callback for this `FieldEdit` instance is the `_setBatID` method
        which will then call `BatteryController.setID()` (via `_bc`) method to
        set the ID and advance to the next state.
        """
        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=1)

        # Create a new FieldEdit screen to enter the battery ID, generating
        # a new battery ID as the default
        bat_id_input = FieldEdit(
            "Bat ID",
            self.px_w,
            self.px_h,
            max_len=10,
            # The BatteryController would already have generated the new
            # battery ID as soon as it transitioned to S_GET_ID.
            val=self._bc.bat_id,
            f_type="ALnum",
            setter=self._setBatID,
        )
        # Pass focus to the battery ID input screen
        self._passFocus(bat_id_input, return_to_me=True)

    def _stBatID(self):
        """
        Handles updating the screen for the `BCStateMachine.S_BAT_ID` state.

        This state only maintains an updated battery voltage, and a footer menu
        to allow for charging, discharging, etc.
        """
        # We should have a battery ID displayed already, we clear only the
        # active bit of the screen, leaving the header, battery ID, and footer
        # menu if it is already there.
        self._clear(header_lns=2, footer_lns=2)

        # Have we created the footer menu yet?
        if self._foot_menu is None:
            logging.info("Creating and showing footer menu for S_BAT_ID state.")
            # Create the footer menu, and draw it
            self._foot_menu = FootMenu(
                self,
                [
                    ("SoC", "Measure SoC"),
                    ("Ch", "Start Charge"),
                    ("Dch", "Start Discharge"),
                    ("Ret", "Exit Screen"),
                    (">", "Next BC"),
                ],
                self.footMenuCB,
            )
            self._foot_menu.drawMenu()

        # Show the current battery voltage
        bv = f"BV: {self._bc.bat_v:>{self._max_cols-6}d}mV"
        self.text(bv, fmt="", y=3)

        self._show()

    def _stChargeDisCharge(self):
        """
        Handles updating the screen while battery is being charge, discharge or
        in a charge/discharge paused state.

        We will be called for any of these states:

        * `BCStateMachine.S_CHARGE`
        * `BCStateMachine.S_DISCHARGE`
        * `BCStateMachine.S_CHARGE_PAUSE`
        * `BCStateMachine.S_DISCHARGE_PAUSE`

        Here we will display the current battery voltage, charge/discharge
        current and charge time. For discharge the current and mAh values are
        shown as negative values - note this is only for display and to help
        distinguish between charge/discharge views. The actual values are still
        positive at the lower level.

        When not paused, a `FootMenu` will be available to allow pausing the
        charge/discharge, or exit the screen.

        When paused, the `FootMenu` will allow resuming, stopping or screen
        exit.
        """
        # Determine if we charging or discharging, or in a charge or discharge
        # paused state
        if self._bc.state in (
            BatteryController.S_CHARGE_PAUSE,
            BatteryController.S_DISCHARGE_PAUSE,
        ):
            paused = True
            # We need to set charging based on the type of pause we're in
            charging = self._bc.state == BatteryController.S_CHARGE_PAUSE
        else:
            paused = False
            # Set charging based of if we charging or dischaging
            charging = self._bc.state == BatteryController.S_CHARGE

        # We clear only the active bit of the screen, leaving the header,
        # battery ID, and footer menu if it is already there.
        self._clear(header_lns=2, footer_lns=2)

        # Have we created the footer menu yet?
        if self._foot_menu is None:
            logging.debug(
                "Creating and showing footer menu for S_CHARGE/S_DISCHARGE state."
            )
            # The footer menu depends on whether we are busy with a SoC
            # measurement, paused or just charging
            if self._bc.soc_m.in_progress:
                # We are busy with a SoC measurement
                opts = [
                    ("Cancel", "SoC Measure"),
                    ("Exit", "Exit Screen"),
                    (">", "Next BC"),
                ]
            elif not paused:
                opts = [
                    ("Pause", f"Pause {'Charge' if charging else 'Discharge'}"),
                    ("Exit", "Exit Screen"),
                    (">", "Next BC"),
                ]
            else:
                opts = [
                    ("Cont", f"Resume {'Charge' if charging else 'Discharge'}"),
                    ("Stop", f"Stop {'Charging' if charging else 'Discharging'}"),
                    ("Exit", "Exit Screen"),
                    (">", "Next BC"),
                ]
            # Create and show the footer menu
            self._foot_menu = FootMenu(self, opts, self.footMenuCB)
            self._foot_menu.drawMenu()

        # Get the current status
        vals = self._bc.charge_vals if charging else self._bc.discharge_vals

        # We show discharging with negative values and charging with positive
        # values. This is only to make it easier to distinguish between the
        # charge and discharge views.
        multiplier = 1 if charging else -1

        # Show the current battery voltage
        ln = f"BV: {self._bc.bat_v:>{self._max_cols-6}d}mV"
        self.text(ln, fmt="", y=2)

        # The current is the 3rd element in the vals tuple
        val = vals[2] * multiplier
        ln = f"A: {val:>{self._max_cols-5}d}mA"
        self.text(ln, fmt="", y=3)

        # The mAh is the 5th element in the vals tuple
        val = vals[4] * multiplier
        ln = f"CH: {val:>{self._max_cols-7}d}mAh"
        self.text(ln, fmt="", y=4)

        # The time is the last element in vals
        mins, secs = divmod(vals[-1], 60)
        hrs, mins = divmod(mins, 60)
        val = f"{hrs:02d}H{mins:02d}:{secs:02d}"
        ln = f"T: {val:>{self._max_cols-3}}"
        self.text(ln, fmt="", y=5)

        self._show()

    def _stComplete(self):
        """
        Handles updating the screen when the battery has been fully charged or
        discharged.

        The display will indicate the charge/discharge is completed, and will
        show the total **mAh** charge for the cycle, as will as the time it
        took to reach this state.

        A `FootMenu` will be available to allow resetting the controller and
        metrics, or cancelling an active SoC measure operation, or exit the
        screen.
        """
        # Determine if we are charged or discharged
        # Set charging based of if we charging or discharging
        charged = self._bc.state == BatteryController.S_CHARGED

        # We clear only the active bit of the screen, leaving the header,
        # battery ID, and footer menu if it is already there.
        self._clear(header_lns=2, footer_lns=2)

        # Have we created the footer menu yet, or have the SoC measure
        # cycle completed?
        if (
            self._foot_menu is None
            or self._bc.soc_m.state == self._bc.soc_m.ST_COMPLETE
        ):
            logging.debug(
                "Creating and showing footer menu for S_CHARGED/S_DISCHARGED state."
            )
            # The footer menu is slightly different depending on this being a
            # SoC measurement still in progress or a normal dis/charge complete
            if (
                self._bc.soc_m.in_progress
                and self._bc.soc_m.state != self._bc.soc_m.ST_COMPLETE
            ):
                opts = [
                    ("Cancel", "SoC Measure"),
                    ("Exit", "Exit Screen"),
                ]
            else:
                opts = [
                    ("Reset", "Reset Metrics"),
                    ("Exit", "Exit Screen"),
                ]

            # Create the footer menu, and draw it
            self._foot_menu = FootMenu(
                self,
                opts,
                self.footMenuCB,
            )

            self._foot_menu.drawMenu()

        # Complete message
        self.text(f"{'Charge' if charged else 'Discharge'} Done", "^", x=0, y=2)
        self._invertText(0, 2)

        # Get the current status
        vals = self._bc.charge_vals if charged else self._bc.discharge_vals

        # The mAh is the 5th element in the vals tuple
        mah = vals[4]
        # The time is the last element in vals
        mins, secs = divmod(vals[-1], 60)
        hrs, mins = divmod(mins, 60)
        tm = f"{hrs:02d}H{mins:02d}:{secs:02d}"

        # Show the total charge and time
        self.text(f"{mah}mAh/{tm}", fmt="^", y=4)

        # Show the current battery voltage
        ln = f"BV: {self._bc.bat_v:>{self._max_cols-6}d}mV"
        self.text(ln, fmt="", y=5)

        self._show()

    def _stYanked(self):
        """
        Handles updating the screen for the `BCStateMachine.S_YANKED` state.

        It will show a message to indicate that the battery was removed anda
        `FootMenu` to allow resetting the controller or exiting the screen.
        """
        # Clear the screen, leaving the header and footer menu in tact.
        self._clear(header_lns=1, footer_lns=2)

        # Have we created the footer menu yet?
        if self._foot_menu is None:
            logging.info("Creating and showing footer menu for S_YANKED state.")
            # Create the footer menu, and draw it
            self._foot_menu = FootMenu(
                self,
                [
                    ("Reset", "Reset Controller"),
                    ("Exit", "Exit Screen"),
                ],
                self.footMenuCB,
            )
            self._foot_menu.drawMenu()

        self.text("Battery removed.", fmt="w^", y=3)
        self._show()

    def update(self):
        """
        Display update handler.

        Called after every `AUTO_REFRESH` delay to update the screen.

        This method will simply determine the current battery state, whether
        there was a state change from the previous to current call, and then
        call the correct handler to manage the display for the given state.
        """
        # We have a lot of flow here, so
        # @pylint: disable=too-many-return-statements,too-many-branches

        # If we do not have an active BCM set yet, we just return
        if self._active_bcm is None:
            return

        # Get the current status
        state = self._bc.state
        # Very weird syntax, but this sets state_changed True is the new state
        # is not the same as the last state, i.o.w. a state changed happened
        # since our last call, and then if there was a state change we update
        # self._last_state to the current state.
        if state_changed := state != self._last_state:
            self._last_state = state
            # If we are now in SoC measure progress, also update the header
            if self._bc.soc_m and self._bc.soc_m.in_progress:
                self._showHeader()

        # Disabled?
        if state == BatteryController.S_DISABLED:
            self._stDisabled()
            return

        # Are we waiting for a battery to be inserted?
        if state == BatteryController.S_NOBAT:
            self._stNoBat()
            return

        if state == BatteryController.S_GET_ID:
            self._stGetID()
            return

        # If we get here, we should have a battery ID already, and it would
        # have been displayed by our setup after receiving focus back from the
        # battery ID input FieldEdit screen.

        if state == BatteryController.S_BAT_ID:
            self._stBatID()
            return

        if state in (
            BatteryController.S_CHARGE,
            BatteryController.S_DISCHARGE,
            BatteryController.S_CHARGE_PAUSE,
            BatteryController.S_DISCHARGE_PAUSE,
        ):
            if state_changed:
                self._foot_menu = None
            self._stChargeDisCharge()
            return

        if state in (BatteryController.S_CHARGED, BatteryController.S_DISCHARGED):
            if state_changed:
                self._foot_menu = None
            self._stComplete()
            return

        if state == BatteryController.S_YANKED:
            if state_changed:
                self._foot_menu = None
            self._stYanked()
            return

        # Clear the screen, leaving the header in tact.
        self._clear(header_lns=2)
        self.text(f"Don't know how to handle sate: {state}", fmt="w^", y=3)
        self._show()

    def menuText(self):
        """
        Allows for dynamically updating the menu screen entry for this BCM to
        also show current active BCM.

        Our parent `Menu` will call here to allow us to dynamically supply the
        name to be shown for this screen on the parent menu.

        The name we show is the screen `Screen.name`, and if we have an active
        BCM already (`_active_bcm` is not ``None``), the name of that BCM in
        brackets after our screen name.

        Returns:
            A string with this `Menu` entry name out parent menu should use.
        """
        # The menu entry will be our name
        res = f"{self.name}"

        # If we already have an active BCM, we append the name for that BCM to
        # the menu name to make it clear which one is currently active.
        if self._active_bcm is not None:
            res = f"{res} [{self._bc.name}]"

        return res

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

    def actLong(self):
        """
        Overrides the base long press event.

        We override this so that we can activate the next BCM in the list of
        available BCMs.

        This will call `_activateBCM()` passing the ID to activate as ``">"`` to
        activate the next BCM in `_bcms`.
        """
        logging.info("Screen %s: Activating next BCM.", self.name)
        self._foot_menu = None
        self._activateBCM(">")

    def footMenuCB(self, opt: str):
        """
        Footer menu callback function.

        This is a callback set for any dynamic `FootMenu` instances we set up
        (see `_foot_menu`) for any running state.

        When called, `_foot_menu` will be set to ``None`` to effectively
        disable the footer menu since an option has now been selected.

        If the ``opt`` is ``"Exit"``, then we exit the current Screen by doing
        a call to `actShort()`, effectively simulating a short press to exit
        the screen.

        For all other options we call the appropriate handler, sometimes also
        based on the state. See the code for moredetails.

        Args:
            opt: The foot menu option string that was active when the option
                was selected.
        """

        # First thing to do is unset the current footer menu
        self._foot_menu = None

        # Are we exiting?
        if opt in ["Exit", "Ret"]:
            # Simulate the exit by calling the shortpress now that _foot_menu
            # is None.
            self.actShort()

        # Go to next BC?
        if opt == ">":
            # Simulate switching to the next BC by simulating the longpress now
            # that _foot_menu is None.
            self.actLong()

        if opt in ("SoC", "Cancel"):
            # These are to start or cancel a SoC measurement. For either we use
            # the convenient toggle
            self._bc.socMeasureToggle()
        elif opt == "Ch":
            # Switch charging on
            self._bc.charge()
        elif opt == "Dch":
            # Switch discharging on
            self._bc.discharge()
        elif opt == "Pause":
            # Pause charge/dischar
            self._bc.pause()
        elif opt == "Cont":
            # Resume after pause
            self._bc.resume()
        elif opt == "Stop":
            # Stop charging/dischargin
            self._bc.resetMetrics()
        elif opt == "Reset":
            if self._bc.state == self._bc.S_YANKED:
                self._bc.reset()
            else:
                self._bc.resetMetrics()

        else:
            logging.info("Received invalid option from footer menu: %s", opt)


def uiSetup(bcms: list):
    """
    Sets up the UI.

    This function will set the rotary encoder up from the ``ENC_??`` constants
    from `config`.

    It then sets up the following screens and menus:

    * A `BCMView` screen to show the `BatteryController` instances in the
      ``bcms`` list.
    * The main `Menu` which consists of:
        * The `BCMView` entry
        * A ``Config`` option for future config and setup from the UI
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

    # Now we can dynamically create the main menu def
    main_menu_def = (
        ("BCMs View", BCMView("BCMView", OLED_W, OLED_H, bcms)),
        (
            "Config",
            (
                ("Calibration", Calibration("Calibration", OLED_W, OLED_H, bcms)),
                ("Network Config", NET_CONF),
                ("Runtime Config", RUNTIME_CONF),
                ("Back", None),
            ),
        ),
        ("Memory usage", MemoryUsage("Memory Usage", OLED_W, OLED_H)),
    )
    main_menu = Menu("MainMenu", OLED_W, OLED_H, main_menu_def, True)

    # Set up the boot screen and give it focus it
    bootscreen = Boot(f"BCM v{VERSION}", OLED_W, OLED_H, len(bcms))
    logging.info("  Passing focus to boot screen.")
    bootscreen.focus(oled, input_evt, focus_on_exit=main_menu)
