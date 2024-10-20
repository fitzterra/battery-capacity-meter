"""
All screen and UI related definitions.
"""

import gc
from micropython import const
from ssd1306 import SSD1306_I2C
from lib import ulogging as logging
from ui import Screen, setupEncoder, input_evt

# from ui.ui_menu import Screen, Menu
# from ui.ui_field_edit import FieldEdit
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

        See `Screen.__init__` for `name`, `px_w` and `px_h` arguments.

        Args:
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


def uiSetup(bat_ctrls: list) -> list:
    """
    Sets up the UI.

    This function will set the rotary encoder up from the `ENC_??` constants
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

    # Set up the boot screen and give it focus it
    bootscreen = Boot("Boot", OLED_W, OLED_H, len(bat_ctrls))
    logging.info("  Passing focus to boot screen.")
    bootscreen.focus(oled, input_evt)


# # Constants for identifying fields that are being edited via the FieldEdit
# # screens for the config sub-menu in the BCMCView screen
# F_BAT_ID = const(0)
# F_LOAD_R = const(1)
# F_PROG_R = const(2)


# class BCMCView(Screen):
#     """
#     Views and controls a BCMC via the MetricTracker.
#     """

#     # We will auto refresh the every this many many millis
#     AUTO_REFRESH = 2000

#     def __init__(self, name: str, m_t: MetricTracker):
#         """
#         Overrides the base class init so we can get the MetricTracker instance.

#         Args:
#             name: See base class
#             m_track: An instance of MetricTracker
#         """
#         super().__init__(name, OLED_W, OLED_H)

#         self._m_track = m_t

#         # This is the index into the list of BCMCs in
#         # MetricTracker._intf.bcmcs, defaulting to the first one
#         self.bcmc_idx = 0

#         # A local counter of the number of BCMCs available
#         self._bcmc_cnt = self._m_track.bcmc_cnt

#     def setup(self):
#         """
#         Called when we get focus.
#         """
#         # Clear the screen
#         self._clear()

#         # Make sure we have any BCMCs available
#         if self._bcmc_cnt == 0:
#             # Make it stand out with inverted output
#             self._clear(1)
#             self._display.text("No BCMCs found.", 0, 3 * 8, 0)
#             self._show()
#             return

#         # Update the display
#         self.update()

#         # Call our base to setup the auto refresher task
#         super().setup()

#     def update(self):
#         """
#         Called whenever the current display needs updating.
#         """
#         # Start with a clear screen
#         self._clear()

#         # Set up the header
#         head = f"BCMC 0x{self._m_track.bcmcAddr(self.bcmc_idx):02x}"
#         self._clearTextLine(0, 1)  # Going display inverted
#         self._display.text(f"{head:^16}", 0, 0, 0)

#         # Get the metrics
#         mt = self._m_track.metrics[self.bcmc_idx]

#         # Are we actively charging or discharging?
#         active = self._m_track.isActive(mt)

#         # The battery ID - stripping trailing spaces
#         bat_id = self._m_track.bat_id[self.bcmc_idx].rstrip()
#         # First the label
#         self._display.text("ID:", 0, 2 * 8)
#         # If we are active. but the ID is empty, we need to highlight it.
#         if active and not bat_id:
#             bat_id = "  NO ID"
#             # Draw a filled rectangle on the ID line (2) from the 4th character
#             # for 9 characters an 1 char high
#             self._display.rect(4 * 8, 2 * 8, 9 * 8, 1 * 8, 1, True)
#             # The text color needs to be black on the light rectagle
#             c = 0
#         else:
#             c = 1
#         # Now the bat ID
#         self._display.text(f"{bat_id}", 4 * 8, 2 * 8, c)

#         # Charging:
#         if mt["charging"]:
#             self._display.text("ST: Charging", 0, 3 * 8)
#             self._display.text(f"cI: {mt['chargeI']}mA", 0, 4 * 8)
#             self._display.text(f"cT: {mt['chargeT']}mAh", 0, 5 * 8)
#         else:
#             self._display.text("ST: Discharging", 0, 3 * 8)
#             self._display.text(f"dI: {mt['dchargeI']}mA", 0, 4 * 8)
#             self._display.text(f"dT: {mt['dchargeT']}mAh", 0, 5 * 8)
#         self._display.text(f"bV: {mt['batV']}mV", 0, 6 * 8)

#         # Show a little indicator next to the state display if we are active.
#         # We draw a circle with radius half the font width less 2 pixels, right
#         # at center of the last character position in the State Indicator line
#         # (line 3)
#         if active:
#             x = self.px_w - self.FONT_W // 2
#             y = 3 * 8 + self.FONT_H // 2
#             r = self.FONT_H // 2 - 2
#             self._display.ellipse(x, y, r, r, 1, True)

#         # If we have a cTime value in the metrics, we display that on the last
#         # line
#         if mt["cTime"]:
#             self._display.text(f"T:  {mt['cTime']//1000}s", 0, 7 * 8)

#         # The footer
#         foot = f"{self.bcmc_idx+1}/{self._bcmc_cnt}"
#         self._display.text(f"{foot:>15}", 0, 7 * 8)

#         self._show()

#     def actUp(self):
#         """
#         Received the UP action event.

#         Change to the previous BCMC
#         """
#         # Ignore it if we only have one BCMC
#         if self._bcmc_cnt == 0:
#             super().actUp()
#             return

#         logging.info("Screen %s changing to previous BCMC.", self.name)
#         self.bcmc_idx -= 1
#         if self.bcmc_idx < 0:
#             self.bcmc_idx = self._bcmc_cnt - 1

#         self.update()

#     def actDown(self):
#         """
#         Received the DOWN action event.

#         Change to the previous BCMC
#         """
#         # Ignore it if we only have one BCMC
#         if self._bcmc_cnt == 0:
#             super().actDown()
#             return

#         logging.info("Screen %s changing to next BCMC.", self.name)
#         self.bcmc_idx += 1
#         if self.bcmc_idx == self._bcmc_cnt:
#             self.bcmc_idx = 0

#         self.update()

#     def actLong(self):
#         """
#         On a long press we create the BCMC config menu.
#         """
#         # Get the latest metrics and load and prog resistor values
#         mt = self._m_track.metrics[self.bcmc_idx]
#         prog_r = self._m_track.prog_r[self.bcmc_idx]
#         load_r = self._m_track.load_r[self.bcmc_idx]
#         bat_id = self._m_track.bat_id[self.bcmc_idx].rstrip()

#         # Dynamically create the config menu with entry names set up to show
#         # current config, but also to be used to change that config.
#         cfg_menu_def = (
#             # First entry is to return focus back to us from the config submenu
#             # We achieve this by using a lambda as a callable action item, and
#             # then simply return True from the callable. This will make the
#             # underlying Screen pass focus back to us.
#             ("Return to BCMC", lambda m_item, scr: True),
#             # Allow editing the battery ID
#             (
#                 "Set Battery ID",
#                 FieldEdit(
#                     "Battery ID",
#                     OLED_W,
#                     OLED_H,
#                     bat_id,
#                     BAT_ID_LEN,
#                     "ALnum",
#                     self.setField,
#                     F_BAT_ID,
#                 ),
#             ),
#             # Next option is to change the charge/discharge mode. The menu name
#             # will show whether to change to charge or discharge. The action
#             # item will call our changeMode method, which will return True and
#             # cause the config menu to exit back to us.
#             (
#                 f"Set to {'Discharge' if mt['charging'] else 'Charge'}",
#                 self.changeMode,
#                 MODE_DISCHARGING if mt["charging"] else MODE_CHARGING,
#             ),
#             # Options to set the Load and Prog resistors via FieldEdit widget
#             # screens. We dynamically create the menu name to be the current
#             # resistor value.
#             # TODO: Currently because we set the menu name to the current
#             #       resistor value, after editing the value and then returning
#             #       to this menu, the actual value may now have a different
#             #       value than what is show on the menu. Not sure how to fix
#             #       this, other than perhaps not having the value on the menu
#             #       option.
#             (
#                 f"Set LoadR: {load_r}",
#                 FieldEdit(
#                     "LoadR", OLED_W, OLED_H, load_r, 5, "num", self.setField, F_LOAD_R
#                 ),
#             ),
#             (
#                 f"Set ProgR: {prog_r}",
#                 FieldEdit(
#                     "ProgR", OLED_W, OLED_H, prog_r, 5, "num", self.setField, F_LOAD_R
#                 ),
#             ),
#         )

#         self.passFocus(Menu("CfgMenu", OLED_W, OLED_H, cfg_menu_def), True)

#     def changeMode(self, menu_item: str, screen: Screen, mode: int) -> bool:
#         """
#         Called from BCMC Config menu to change the BCMC mode.

#         When this BCMC View instance receives a long press event, we
#         dynamically create a BCMC Config Menu screen, and pass focus to this
#         menu, telling to pass focus back to us on exit.

#         One of the options on this menu is to change the BCMC state to
#         charging or discharging, depending on what the current state is. This
#         is why we generate the menu on the fly, so that we can generate the
#         menu options to reflect the current BCMC state.

#         When this dis/charge option is selected, it will call this method.
#         When we are called, we will change the mode, and then return True.

#         Returning True is an indicator for the Menu to exit the menu and pass
#         focus to it's called (which is this BCMC View screen remember?).

#         Args:
#             menu_item: The text from the menu item that was selected
#             screen: The calling screen in stance. In this it will be this
#                 instance.
#             mode: The new mode to set. This will be one of MODE_DISCHARGING or
#                 MODE_CHARGING

#         Returns:
#             True to let the config menu know to exit and pass focus back to us.
#         """
#         # We do not use the 1st two args, but the Menu callable action item
#         # interface will pass them along, so @pylint: disable=unused-argument

#         logging.info(
#             "Changing mode to: %s",
#             "charging" if mode == MODE_CHARGING else "discharging",
#         )
#         # Do it
#         self._m_track.setMode(self.bcmc_idx, mode)

#         return True

#     def setField(self, val: bytearray, f_id: int):
#         """
#         Callback for the resistor and battery ID field edit screens to set
#         these fields.

#         Args:
#             val: The new field value as a bytearray
#             f_id: One of the F_??? constants defined above to indicate which
#                 field we are setting
#         """
#         if f_id in (F_LOAD_R, F_PROG_R):
#             # The resistor values we can convert to to int directly from the
#             # bytearray value
#             res = int(val)

#             logging.debug(
#                 "Setting %s resitor value to %s",
#                 "load" if f_id == F_LOAD_R else "charge prog",
#                 res,
#             )

#             if f_id == F_LOAD_R:
#                 self._m_track.setLoadR(self.bcmc_idx, int(val))
#             else:
#                 self._m_track.setProgR(self.bcmc_idx, int(val))

#             return

#         if f_id == F_BAT_ID:
#             # Need to decode the bytearray into a string
#             b_id = val.decode("ascii")

#             logging.debug("Setting battery ID to %s", b_id)

#             # We pad the field with spaces and limit to the max len in order to
#             # try use memory more efficiently - not sure if this will even help.
#             self._m_track.bat_id[self.bcmc_idx] = f"{b_id:{BAT_ID_LEN}.{BAT_ID_LEN}}"

#             return

#         logging.error("Unknown field id [%s] in field setter callback.", f_id)


# MENU_DEF = (
#     ("BCMC View", BCMCView("BCMC View", m_track)),
#     ("Memory usage", MemoryUsage("Memory Usage", OLED_W, OLED_H)),
# )


# menu = Menu("MainMenu", OLED_W, OLED_H, MENU_DEF)
