"""
Menu definition and manager

This module provides a menu function using the Menu class.

NOTE: Currently this is targeted for the SSD1306 type OLED displays, and more
      specifically the 128x64 size. It may work on other screens and sizes with
      some tweaking, but has only been tested on this type of display.
      Furthermore, it currently assume the font size is 8x8 as the standard
      Frame buffer provides.

The menu options and layout is defined using a hierarchical tuple definition
that can look like this:

.. python::

    MENU = (
        ('Item 1', Screen),
        ('Item 2', (
                     ('Sub 2.1', Screen),
                     ('Sub 2.2', Screen),
                     ('Sub 2.3', (
                                   ('Sub-sub 2.3.1', Screen),
                                   ('Sub-sub 2.3.2', Screen),
                                 )
                     ),
                   )
        ),
        ('Item 3', Screen),
        ('Item 4', Screen),
    )

Each entry is a 2-tuple with the first element being the menu entry to display,
and the second element a `ui_output.Screen` instance, or another tuple for a
sub-menu.

Notes and functionality:

* The menu entry name will be clipped to the max width the display can handle.
* Any one menu can be as long as it needs to be, and will scroll up and down it
  it does not fit on the screen.
* If the menu action (second menu definition element) is not a Screen type, it
  is assumed to be a sub-menu, and will have a '>' at the end of line to show
  this is a sub-menu.
* The currently selected item will be highlighted in reverse video.
* Control is currently only by rotary encoder and rotating clockwise will move
  down the menu, while rotating counter-clockwise will move up.
* Going past the top or bottom end will wrap around to the other end.
* Single click on the encoder button will action the currently selected item.
    * If this is a Screen instance, focus will be passed to this screen instance
    * If it is a tuple, it will be assumed to be a sub-menu definition and will
      jump into the sub-menu.
    * For any other type, and error will be logger.
* A long press of the encoder button will return to the parent menu from a
  sub-menu.
"""

from lib import ulogging as logging
from .ui_output import Screen


class Menu(Screen):
    """
    Screen to display and manage the menu.
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, name: str, px_w: int, px_h: int, menu_def: tuple) -> None:
        """
        Class init.

        Args:
            name: See Screen.__init__.
            px_w: See Screen.__init__.
            px_h: See Screen.__init__.
            menu_def: The full menu definition
        """
        # Call our base and set the screen name
        super().__init__(name, px_w, px_h)

        self._menu_def = menu_def
        # This is the current menu or sub-menu we are showing
        self._curr = self._menu_def
        # Which item withing the current menu is selected
        self._selected = 0

        # This is a list of (parent, selected) tuples to keep track of where
        # we are in a sub-menu tree. Every time we enter a sub-menu, we apend the
        # current menu and selected item as a tuple to this list, and every
        # time we leave a submenut, we will pop the current menu details off
        # this list.
        self._parents = []

        # These are max character columns and rows based on the display width
        # and height in pixels and the font width and height (FONT_W and FONT_H)
        self._max_cols = px_w // self.FONT_W
        self._max_rows = px_h // self.FONT_H

        # This the Y position for a view port or view window over a menu list
        # that has more lines than would fit on the screen. In a case like
        # this, we move the view port up and down over the items that would fit
        # in the screen, thus scrolling the menu items up or down to ensure the
        # selected item is on the display.
        self._viewport_y = 0

    def _menuLine(
        self, txt: str, y: int, selected: bool = False, submenu: bool = False
    ):
        """
        Prints a menu item at line y, optionally inverted to indicate the item
        is the currently selected item.

        Each line is FONT_H pixels with line 0 at the top of the display.
        The last line is ``self._max_rows-1``

        The text is printed starting from the leftmost pixel on the display.

        If ``txt`` has more characters than `_max_cols`, it is clipped to
        fit on the display.

        NOTE!: The inverting mechanism is very simple an relies on the fact
        that the font is 8x8 pixels per character. Should this ever change, the
        inverting mechanism needs to be revisited.

        Args:
            txt: The text to display
            y : The line at which to display the text - 0 based, with 0 at the
                top.
            selected: Will invert the text if True
        """
        # Make sure to always clip the text to max width
        txt = txt[: self._max_cols]

        # We add an indicator for a sub-menu
        if submenu:
            # For now we just add > at the end of the line. First pad the line
            # with spaces for the full width minus 1, then add the indicator at
            # the end
            txt = f"{txt:{self._max_cols-1}.{self._max_cols-1}}>"

        # We display it as normal and return if no inverting is needed
        self._display.text(txt, 0, y * self.FONT_H)
        if not selected:
            return

        # To make a sub-menu that may be the full line long more visible, we do
        # not highlight the indicator we add at the end. To make this work,
        # simply drop the last character if this is a sub-menu entry
        if submenu:
            txt = txt[:-1]

        # We need to invert. We do this by XORing the bytes that make up this
        # text with 0xFF to invert the bits.
        # The bytes buffer representing the display bits are arranged such that
        # that each byte in order represents 8 vertical bits consequentially.
        #
        # Here is an example trying to show how this looks:
        #
        #  | byte1 | byte2 | byte3 | byte4
        #  abcdefghABCDEFGHabcdefghABCDEFGH
        #
        #  1234  <-- byte number ^
        #  aAaA \
        #  bBbB  \
        #  cCcC   \
        #  dDdD   | First 4 pixel rows on display
        #  eEeE   |
        #  fFfF   /
        #  gGgG  /
        #  hHhH /
        #
        # NOTE: This is very specific to the SSD1306 I²C OLED display, and only
        # works so simply because the font height is the same the number of
        # bits in a byte!

        # Each text line takes up `self._max_cols` characters, with each pixel
        # line in a character taking up one byte, giving 8 bytes per character.
        # NOTE: We use `FONT_W` here only to be pedantic and not hardcode an 8
        #   eight. If the font width is not 8 pixels, this will probably not
        #   work.
        offs = self._max_cols * self.FONT_W * y
        # We only highlight the actual text, but changing this to:
        # end = offs + self._max_cols * self.FONT_W would highlight the full
        # line, which could also be interesting
        # NOTE: Same remark for `FONT_W` here as above.
        end = offs + len(txt) * self.FONT_W

        for i in range(offs, end):
            # By XORing with 0xFF we invert each bit
            self._display.buffer[i] ^= 0xFF

    def _isSubMenu(self, item) -> bool:
        """
        Returns True if the item is a sub-menu, or False otherwise.

        A sub-menu is defined by the item being a tuple.

        Args:
            item: The action item of (second element) of any menu item.
        """
        return isinstance(item, tuple)

    def setup(self):
        """
        Called when we receive focus.
        """
        # Nothing to set up, so let's get on with it.
        self.update()

    def update(self):
        """
        Updates the display with the current menu and highlights the
        currently selected item.
        """
        # Given the current viewport offset, calculate the "viewport" line
        # number for the selected item
        vp_sel = self._selected - self._viewport_y

        # Adjust the viewport if the select line is outside the display area
        if vp_sel >= self._max_rows:
            # We need to move the viewport Y down by the number of lines
            # `vp_sel` is below the last (0 based) display line.
            self._viewport_y += vp_sel - (self._max_rows - 1)
            # Recalculate the selection line in the viewport
            vp_sel = self._selected - self._viewport_y
        elif vp_sel < 0:
            # Here `vp_sel` will be negative by the exact amount of lines we need
            # to move the viewport Y up with.
            self._viewport_y += vp_sel
            # Reset the selection in the viewport to line 0
            vp_sel = 0

        # We start with a clear display
        self._clear()
        # Cycle through only the items in the viewport from the menu list
        for i, item in enumerate(
            self._curr[self._viewport_y : self._viewport_y + self._max_rows]
        ):
            # Each item is a 2-tuple where the first element is the menu text
            # to show. Display that, and invert the currently selected line.
            self._menuLine(item[0], i, i == vp_sel, self._isSubMenu(item[1]))
        self._show()

    def _moveSelection(self, inc: int, wrap: bool = True):
        """
        Moves the current selection up or down my the given increment.

        If increment is negative, the we move up, positive and we move down.
        The increment should normally only be one, but we allow for larger
        steps.

        If we go past the top or bottom, we wrap around to the other side if
        wrap is True, else we get stuck to the top or bottom item.
        """
        # Adjust the selected item
        self._selected += inc

        # Check wrapping
        if self._selected < 0:
            self._selected = 0 if not wrap else len(self._curr) - 1
        elif self._selected >= len(self._curr):
            self._selected = len(self._curr) - 1 if not wrap else 0

        # Update the display
        self.update()

    def actCCW(self):
        """
        Select the next item up from the current, wrapping round to the bottom
        if we try to go past the top item.

        This is a convenience wrapper for _moveSelection()
        """
        self._moveSelection(-1)

    def actCW(self):
        """
        Select the next item down from the current, wrapping round to the top
        if we try to go past the bottom item.

        This is a convenience wrapper for _moveSelection()
        """
        self._moveSelection(1)

    def actShort(self):
        """
        Actions the currently selected menu item by either passing focus to a
        new screen, or to enter a sub-menu.

        If this is a sub-menu item, the sub-menu will be displayed, else the
        associated function will be called.
        """
        # For the current menu item, get the item name, the action argument,
        # plus any optional arguments to pass to the action item if it is a
        # callable.
        menu_item, act_item, *act_args = self._curr[self._selected]

        # If this is a sub-menu, we enter it
        if self._isSubMenu(act_item):
            # Add the current menu and selection to the parents list
            self._parents.append((self._curr, self._selected))
            # Set up the new menu and go to the first entry
            self._curr = self._curr[self._selected][1]
            self._selected = 0
            self.update()
            return

        if isinstance(act_item, Screen):
            # Pass focus to this screen, hinting that it could return to us on
            # exit.
            self._passFocus(act_item, return_to_me=True)
            return

        if callable(act_item):
            # It's a callable. We expect to be bale to pass the current menu
            # item name, a reference to this Screen/Menu instance, and any
            # additional optional arguments the item definition may have.
            logging.debug(
                "Going call function menu item %s : %s(%s, %s, *%s)",
                menu_item,
                act_item,
                menu_item,
                self,
                act_args,
            )

            # Make the call
            res = act_item(menu_item, self, *act_args)

            # If res is True, and we can pass focus to a parent, we do so.
            if res is True and self._focus_on_exit:
                logging.info("Passing focus to %s", self._focus_on_exit)
                self._passFocus(None)

            return

        logging.error("Invalid menu action %s, for entry '%s'", act_item, menu_item)

    def actLong(self):
        """
        A long press exits a sub-menu back to the parent if we are in a
        sub-menu.

        Log an error if we are not in a sub-menu.
        """
        # Are we at the top level?
        if not self._parents:
            # Do we have a screen to return focus to on exit?
            if self._focus_on_exit:
                # Yes, so we are probably a menu called for another screen, so
                # let's exit back to our caller
                self._passFocus(None)
            else:
                logging.error("Already at the top level menu.")
            return
        # Pop the last parent an selection of the parents tree
        self._curr, self._selected = self._parents.pop()
        # Draw the menu
        self.update()
