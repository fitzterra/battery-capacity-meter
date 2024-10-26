"""
UI Field Editor.
"""

from micropython import const
from lib import ulogging as logging
from .ui_output import Screen

# Cursor controls
C_SHOW = const(0)
C_HIDE = const(1)

# Mode settings
M_CURSOR = const(0)  # Cursor movement
M_EDIT = const(1)  # Edit mode

F_TYPES = {
    "num": bytearray(rb"0123456789", "ascii"),
    "alpha": bytearray(rb"abcdefghijklmnopqrstuvwxyz -+_", "ascii"),
    "ALPHA": bytearray(rb"ABCDEFGHIJKLMNOPQRSTUVWXYZ -+_", "ascii"),
    "alnum": bytearray(rb"abcdefghijklmnopqrstuvwxyz 0123456789-+_", "ascii"),
    "ALnum": bytearray(rb"ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789-+_", "ascii"),
}
"""Possible field types. These are limited ASCII lists of characters that are
allowed for fields of this type. These lists are not overly memory efficient at
the moment. In future a better way to manage this may be explored."""


class FieldEdit(Screen):
    """
    A field editor screen.

    Allows editing an input field by using the encoder and button only.

    The input field definition required is:

    * A field label
    * An optional initial field value
    * The maximum length the field may be
    * The field type - this defines the possible characters that may be
      contained in the field and which the rotary encoder will cycle through
      when changing a character in the field.
    * An optional function to call when the OK is pressed to indicate the field
      update is complete.

    The label will be displayed with the actual field input below that in
    inverse video. This will be the number of characters allowed in the field.

    The default value will also be show in this field.

    Two *buttons*, ``OK`` and ``Cancel`` will be show at the bottom of the
    screen.

    A cursor is shown as lines above and below the current character than is
    selected. Rotating the encoder moves the cursor left and right. Moving past
    the last char in the input field takes the cursor to the buttons. Move off
    the buttons takes the cursor back to the input field.

    A short press on a field character goes into edit mode. In this mode
    rotating the encoder cycles the character at that position. When the
    desired character is reached, pressing enter leaves edit mode, locking the
    change.

    A short press on either of the buttons, activates the button.

    The OK button will call the setter function if supplied, and then exit by
    passing focus to the next screen (usually back to the parent).
    The signature for the callback is:

        def callback(value, field_id)

    NOTES:
        * The ``value`` field will a ``bytearray`` type.
        * The ``field_id`` is the same optional id passed in on `__init__`.

    The Cancel button will just exit by passing focus. A long press is also a
    Cancel operation.
    """

    # We do need all instance attributes, so @pylint: disable=too-many-instance-attributes

    # Lines (Y) where the different elements are placed
    LN_LABEL = 1 * Screen.FONT_H
    LN_FIELD = 3 * Screen.FONT_H
    LN_BTNS = 6 * Screen.FONT_H

    # The button positions
    POS_OK = (3 * Screen.FONT_W, LN_BTNS)
    POS_CANCEL = (8 * Screen.FONT_W, LN_BTNS)

    def __init__(
        self,
        name: str,
        px_w: int,
        px_h: int,
        val: int,
        max_len: int,
        f_type: str,
        setter: callable = None,
        field_id: int = None,
    ):
        """
        Overrides base init to add additional init args.

        Args:
            name: As for base Screen, but will also be used as field label
            px_w, px_h: See Screen.__init__.
            val: The current value, if any for the field
            max_len: The max number of characters
            f_type: The field type. One of the keys in F_TYPES
            setter: A function to call when OK is pressed to set the new value.
                The setter only accepts the new value as argument.
            field_id: Can be used by the callback setter to identify the field
                being set. Helpful when there is one setter callback for
                multiple fields. Will be passed as the last arg to the setter
                callback.
        """
        # We need all these args, so @pylint: disable=too-many-arguments

        # We use the screen Name for the field label
        super().__init__(name, px_w, px_h)

        # Sanity: Max display characters length
        self._max_d_len = px_w // self.FONT_W

        # Limit the field length to the maximum display characters length
        self._max_len = min(max_len, self._max_d_len)
        # Limit the field field value to the max_len
        self._val = bytearray(str(val)[: self._max_len] if not None else "", "ascii")
        self.f_type = f_type
        self._char_list = F_TYPES[f_type]
        self._setter = setter
        self._field_id = field_id

        # We start in cursor mode
        self._mode = M_CURSOR

        # The current cursor position
        self._cursor = 0

    def _setCursor(self, act: C_SHOW | C_HIDE):
        """
        Show or hide the current cursor.

        This will normally we called before moving the cursor to hide it from
        it's current location, and then after it has been moved called again to
        show it at the new positon.

        The cursor position can either be on any of the characters in the
        field, or on one of the buttons.

        The cursor is shown as a line above and below the character or button.

        The `_cursor` value indicates where the cursor is currently:
        * positive it in the field at the position indicated
        * -1 is on the Cancel button
        * -2 is on the OK button
        """
        if self._cursor >= 0:
            # We're inside the edit field
            x = self._cursor * self.FONT_W
            y = self.LN_FIELD - 2
            l = self.FONT_W
        else:
            # On OK or Cancel button
            x, y = self.POS_OK if self._cursor == -2 else self.POS_CANCEL
            l = (2 if self._cursor == -2 else 6) * self.FONT_W
            # Adjust Y to be above
            y -= 2

        # The lines above and below, or adjusted for edit mode
        for y_pos in (y, y + self.FONT_H + 3):
            if y_pos == y and self._mode == M_EDIT:
                y_pos += self.FONT_H + 2
            self._display.hline(x, y_pos, l, 1 if act == C_SHOW else 0)

    def _moveCursor(self, step: int):
        """
        Moves the cursor.

        This should only be called when in cursor mode.
        The step value indicated the direction to move and also the magnitude,
        although the magnitude should probably never be more than 1.

        This will remove the current cursor, update `_cursor` and then
        show the new poition.

        Args:
            step: Should be 1 to move forward, and -1 to move backwards.
        """
        # First hide the current curso
        self._setCursor(C_HIDE)

        # Apply the movement
        self._cursor += step

        # Now adjust for wrapping
        if self._cursor < -2:
            # Wrap from the button to the end of the field
            self._cursor = len(self._val) - 1
        elif self._cursor == min(len(self._val) + 1, self._max_len):
            # Either on the character after the last one in the field, or at
            # the end of the field. We wrap around to the OK button
            self._cursor = -2
            # Going to the buttons we always force exit edit mode
            self._mode = M_CURSOR

        # Show the new cursor
        self._setCursor(C_SHOW)

        self._show()

    def _updateField(self):
        """
        Clears the field on the display (reverse video) and displays the
        current field value.
        """
        # Reverse where we will edit the field
        self._display.rect(
            0, self.LN_FIELD, self._max_len * self.FONT_W, self.FONT_H, 1, True
        )

        # The current value in the edit field in reverse video
        self._display.text(self._val.decode("ascii"), 0, self.LN_FIELD, 0)

    def _changeChar(self, step: int):
        """
        Called when we're in edit mode and a change event for the character
        under the cursor has occurred.

        ToDo:
            Add more detail on what this will do
        """
        # If this adding a new character where the value is shorted than the
        # field, we add the first char in our charlist to the end of the
        # current value and that's it
        if self._cursor == len(self._val) and self._cursor != self._max_len:
            self._val += chr(self._char_list[0]).encode("ascii")
        else:
            # First get the char in self._val where the cursor now points as a byte
            b = chr(self._val[self._cursor]).encode("ascii")
            # Now look that up in our char list based on the field type we are
            # editing, and also apply the step to this index
            b_idx = self._char_list.find(b) + step
            # Handle wrapping
            if b_idx < 0:
                b_idx = len(self._char_list) - 1
            elif b_idx >= len(self._char_list):
                b_idx = 0
            # Update our value
            self._val[self._cursor] = self._char_list[b_idx]

        self._updateField()
        self._show()

    def setup(self):
        """
        Called to set the screen up for editing on receiving focus.
        """
        self._clear()

        # The field label on the second line:
        self._display.text(f"{self.name}:", 0, self.LN_LABEL)

        self._updateField()

        # The OK and Cancel buttons
        self._display.text("OK", *self.POS_OK)
        self._display.text("Cancel", *self.POS_CANCEL)

        # Show cursor
        self._setCursor(C_SHOW)

        self._show()

    def actCCW(self):
        """
        Rotation event: left
        """
        if self._mode == M_CURSOR:
            self._moveCursor(-1)
            return
        self._changeChar(-1)

    def actCW(self):
        """
        Rotation event: right
        """
        if self._mode == M_CURSOR:
            self._moveCursor(1)
            return
        self._changeChar(1)

    def actShort(self):
        """
        Singe click toggles edit mode when the cursor is in the field, or
        actions the button when on a button
        """
        if self._cursor >= 0:
            logging.debug("Toggling edit mode.")
            # Remove cursor
            self._setCursor(C_HIDE)
            # Toggle the mode
            self._mode = M_EDIT if self._mode == M_CURSOR else M_CURSOR
            # Redraw cursor in case we show a different cursor in edit mode.
            self._setCursor(C_SHOW)
            self._show()
            return

        # If OK was clicked and we have a setter, we call it
        if self._cursor == -2 and callable(self._setter):
            self._setter(self._val, self._field_id)
        # Return to the caller
        self.passFocus(None)

    def actLong(self):
        """
        Long press deletes the last char in the field if the cursor is
        currently in the field.
        """
        if self._cursor < 0:
            logging.error("Can only delete end if in field.")
            return
        # If val is empty, we can ignore it
        if len(self._val) == 0:
            logging.error("Value is already empty, ignoring delete.")
            return

        # Hide cursor
        self._setCursor(C_HIDE)

        # If the cursor is at the end of the field, we need to move it back
        if self._cursor >= len(self._val):
            # Don't let the position go less than 0
            self._cursor = max(self._cursor - 1, 0)

        # Now we remove the last char in the value, update the field, show the
        # cursor and update the display
        self._val = self._val[:-1]
        self._updateField()
        self._setCursor(C_SHOW)
        self._show()
