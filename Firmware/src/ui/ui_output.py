"""
UI Output bases functionality
"""

import uasyncio as asyncio
from ssd1306 import SSD1306_I2C
from lib import ulogging as logging
from .ui_input import (
    EV_ROTATE,
    EV_BUTTON,
    DIR_CW,
    DIR_CCW,
    SHORT_PRESS,
    LONG_PRESS,
)


class Screen:
    """
    Generic OLED screen class.

    All UI screens should be inherited from this class.
    The main methods to override are:

    * `setup()` and `update()`:
        * These are the two output methods. `setup()` is called when initially
          receiving focus to do any initial display output setup.
        * The `update()` method could be called whenever the display needs to
          be updated.
        * Access to the display is via the `_display` attribute, which is
          in essence a FrameBuffer_ instance and uses the standard FB protocol.
        * After doing whatever updates to the FB is needed, the
          ._display.show()` method should be called to do the actual
          screen update.
        * NOTE: When this instance does NOT have focus, ._display` will be
          None, so if any weird errors happen, make sure this is not the
          reason.
    * The four ``act???()`` methods, or only those that will be needed.
        * These method are called asynchronously when user input is detected.
        * The current input types and methods called for these are:
            * `actCW()` : Rotary encoder turned one step clockwise
            * `actCCW()` : Rotary encoder turned one step counter clockwise
            * `actShort()`: The encoder button received a short press
            * `actLong()`: The encoder button received a long press
        * Any of these that are not needed do not need to be overridden.
        * These methods should normally do some screen updates and could call
          `update()`, or else just update the display directly.
        * These functions run inside an asyncio task, so should do whatever it
          needs to do quickly and then exit.
        * The `actShort()` will automatically pass focus to any Screen that was
          specified to "focus_on_exit" when this screen received focus. This
          removes the need to also override `actShort()` for every screen if a
          good chaining hierarchy is defined when passing focus.

    **Receiving Focus**

    When receiving focus via an external call to our `focus()` method, we get
    control of the display output and the user input.

    We also start a new asyncio task (`_inputMonitor`) to monitor for input and
    then call the appropriate action method. This monitor task will exit again
    when we loose focus.

    The caller that has passed focus to us, may also "suggest" another Screen
    instance that should get focus when this screen needs to exit. This can
    often be used by a Screen needing to show a  child screen. When passing
    focus to the child Screen, the parent will "suggest" to the child to return
    focus to itself when done.

    This is an easy way to create a dynamic hierarchical screen flow. A child
    may even pass focus to another child and then "suggest" to this child to
    pass focus back to this child's parent. All this without having to hardcode
    hierarchies in Screen instances.

    Attributes:
        name: Set from the ``name`` arg by `__init__`
        px_w: Set from the ``px_w`` arg by `__init__`
        px_h: Set from the ``px_h`` arg by `__init__`
        _max_cols: The max number of columns in character widths that will fit
            on the screen. Based on the display width (``px_w``) and the font
            width (``FONT_W``)
        _max_rows: The max number of rows in character heights that will fit on
            the screen. Based on the display height (``px_h``) and the font
            height (``FONT_H``)
        AUTO_REFRESH: Can be overridden by a derived class to get auto screen
            refresh functionality that calls the `update()` method every this
            many milliseconds.  See the `_refresh()` and `setup()` methods for
            more info.
        FONT_H: Default font heigh for the default framebuffer font
        FONT_W: Default font width for the default framebuffer font

    .. _FrameBuffer: https://docs.micropython.org/en/latest/library/framebuf.html
    """

    # We are happy with the number of these @pylint:disable=too-many-instance-attributes

    # See class docstring Attributes definition for more info
    FONT_H = 8
    FONT_W = 8

    # See class docstring Attributes definition for more info
    AUTO_REFRESH = 0

    def __init__(self, name: str, px_w: int, px_h: int):
        """
        Instance init.

        Args:
            name: A name for the screen. This can be used in the `setup` or
                `update` methods, or in log messages to identify which screen
                is doing what.
            px_w: The screen width in pixels
            px_h: Screen height in pixels
        """
        # Save the instance name and screen size
        self.name = name
        self.px_w = px_w
        self.px_h = px_h
        self._max_cols: int = px_w // self.FONT_W
        self._max_rows: int = px_h // self.FONT_H

        # Will be true if this instance currently has focus, false otherwise
        self._has_focus = False
        # Reference to the display object (an SSD1306 OLED currently) if we
        # have focus
        self._display = None
        # Will be set to an asyncio.Event instance on receiving focus. This
        # will be monitored for new input events.
        self._event_in = None

        # Can be set by `focus()` as the screen to pass focus to when this
        # screen exists. See `focus()` and `_passFocus()`
        self._focus_on_exit = None
        """Optional `Screen` instance to receive focus when this screen exists.
        Set via `focus()` and used in `_passFocus()` when exiting this
        screen."""

        # Will be used to save the _focus_on_exit screen (if set) and we call
        # the `_passFocus` method. The reason is that if we pass focus somewhere
        # and we ask that Screen to pass focus back to us on exit, when that
        # screen passesfocus, it is probably going to set the `_focus_on_exit`
        # arg to our `focus` method to be None. In this case, the `focus`
        # method will then overwrite our caller's `_focus_on_exit` value, and
        # we loose the link back to our caller.
        # The `_passFocus` and `focus` methods will work together to then
        # restore our caller's screen reference if need be.
        self._save_focus_on_exit = None

    def __str__(self):
        """
        Human readable representation of the screen.

        Returns:
            The screen `name` only.
        """
        return self.name

    def _invertText(self, x: int, y: int, w: int = 0):
        """
        Inverts the text that is displayed at column ``x``, row ``y``, for
        ``w`` columns.

        Note:
          These are not pixel coordinates, but character display coordinates,
          with the assumption that text coordinates (0,0) corresponds to pixel
          coordinate (0,0). IOW, text rows and columns will always be multiples
          of `FONT_W` and `FONT_H`.
          Currently only the characters in one row can be inverted.


        Note:
            The inverting mechanism is very simple an relies on the fact that
            the font is 8x8 pixels per character. Should this ever change, the
            inverting mechanism needs to be revisited.

        Args:
            x: Column in character coordinate units of first character to
                invert.
            y: Row in character coordinate units of first character to invert.
            w: How many characters to invert. With the default of 0, all
                characters to the end of the line will be inverted.
        """
        # We invert. by XORing the bytes that make up this text with 0xFF to
        # invert the bits.
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
        offs = self._max_cols * self.FONT_W * y + x * self.FONT_W

        # If w is 0, calculate the number of characters left up to the end of
        # the line.
        if w == 0:
            w = self._max_cols - x

        # NOTE: Same remark for `FONT_W` here as above.
        end = offs + w * self.FONT_W

        for i in range(offs, end):
            # By XORing with 0xFF we invert each bit
            self._display.buffer[i] ^= 0xFF

    def nameAsHeader(self, fmt: str | None = None):
        """
        Shows the current screen name as a header at the top of the screen.

        There are some basic formatting options available which can be set as
        characters in a format string. The formatting characters available are:

        * **Alignment**. If any of these characters appears in ``fmt`` string, they
          will be used to set alignment. If the header is longer than the space
          available, any formatting will be disregarded with the header left
          aligned, and extra text clipped off the end.

            * ``^``: Align center.
            * ``>``: Right align.
            * ``<``: Left align.

        * **Invert**: The character ``i`` in ``fmt`` will invert the full header
            line.
        * **Underline**: The '_' character will cause an line to be drawn on
            the last pixel row of the header line. Note that this will
            intersect with any text drawn on the last pixel row.
        * **Overline**: The '-' character will cause an line to be drawn in the
            first pixel row of the header line. Note that this will intersect
            with any text drawn on the last pixel row.

        Note:
            The order of characters in ``fmt`` does not matter. No validation is
            done either, so any other characters appearing in the string will
            have no effect.

        Examples:

        * ``^i`` or ``i^`` will center and invert the header
        * ``>_`` will right align and draw an underline
        * ``_^-`` will center and draw and underline and overline.

        Args:
            fmt: See above.
        """
        # This will be the max number of characters we have in the line
        width = self._max_cols
        # Any alignment? We default to no alignment
        align = ""
        for a in ("^", "<", ">"):
            if a in fmt:
                align = a
                break

        # Set up the header with alignment and width
        header = f"{self.name:{align}{width}.{width}s}"
        self._display.text(header, 0, 0, 1)
        # If we invert, we do not even look at the under/over line options
        if "i" in fmt:
            self._invertText(0, 0)
            return

        # Overline and underline
        if "_" in fmt:
            # Draw a line below the title
            self._display.hline(0, self.FONT_H - 1, self.px_w, 1)
        if "-" in fmt:
            # Draw a line above the title
            self._display.hline(0, 0, self.px_w, 1)

    def _show(self):
        """
        Convenience function to show any screen screen changes made to the
        buffer.

        Just calls ._display.show()` making it slightly easier to read the
        code.
        """
        self._display.show()

    def _clear(self, color: int = 0, show: bool = False):
        """
        Convenience function to clear the screen.

        Args:
            color: The color to clear the screen to. Defaults to black (0).
            show: If True, then the display will be updated to show the change.
                If False, the default, then the caller will have to do so.
        """
        self._display.fill(color)
        if show:
            self._show()

    def _clearTextLine(self, line_no: int, color: int = 0):
        """
        Clears a text line.

        The current FrameBuffer seems to ignore space characters an does not
        clear the pixels they overwrite - this may be only if it the line
        consists entirely of spaces - need to check.

        Anyway, it is sometimes needed to clear just one line on the display
        where an updated value will be displayed, so this function is a
        convenience function to do so, since writing spaces does not seem to do
        the trick.

        Args:
            line_no: The text line number to clear. This is based on the font
                height (self.FONT_H), assuming that the first line is at y
                pixel 0, and this is line no 0.
            color: The color to clear the line to. Defaults to black (0)
        """
        # We clear the line by drawing a filled rectagle the full width of the
        # display, starting at the pixel indicated by line_no with a font
        # height of self.FONT_H
        self._display.rect(
            0,  # Start x
            line_no * self.FONT_H,  # Start y
            self._display.width,  # Full display width
            self.FONT_H,  # One line height
            color,
            True,  # Fill the rectangle
        )

    async def _inputMonitor(self):
        """
        Run as a coro to manage input events for this screen.

        This will start as a task whenever we get input focus, and will exit
        when we loose focus.

        If we do not have the focus, `_event_in` will be None and we just loop
        waiting for it to be set to an Event sync primitive by an external call
        to .focus()`. While `_event_in` then is an event primitive, we monitor
        it for input events.

        Once we receive any event, we determine the event type and call one of
        the action methods to handle the input. This continues until we loose
        focus again.
        """
        # pylint: disable=too-many-branches
        logging.debug("Starting asyncio input monitor for screen %s", self.name)

        while self._display is not None:
            # We wait for input
            await self._event_in.wait()

            # NOTE: It is possible that while we were waiting for an input
            #       event, this screen has lost focus due some other external
            #       event (a timer or something else in this screen expired and
            #       it passed focus somewhere else.
            #       When this happens, it seems we will still be stuck in the
            #       await above, self._event_in will now have been set to None
            #       on losing focus.
            #       As soon as an input event then occurs, the await above ends
            #       and we get here... but.... self._event is now None, and we
            #       should not act on any events anymore.
            #       For this reason we need to check if self._event is None
            #       when we get out of the await above. If it is, we simply go
            #       back to the top of the loop, and this will probably then
            #       let us exit since self._display should now also be None.
            if self._event_in is None:
                continue

            logging.debug(
                "Input event: %s - %s", self._event_in.e_type, self._event_in.e_val
            )

            # These event types are specific to a rotary encoder with button.
            # We get rotation (CW and CCW) events (but not rotation counts),
            # and long and/or short button presses.
            # These are detected a corresponding action method is called to
            # handle the input event.
            if self._event_in.e_type == EV_ROTATE:
                if self._event_in.e_val == DIR_CW:
                    self.actCW()
                elif self._event_in.e_val == DIR_CCW:
                    self.actCCW()
                else:
                    logging.error(
                        "Not a valid rotation direction: %s", self._event_in.e_val
                    )
            elif self._event_in.e_type == EV_BUTTON:
                if self._event_in.e_val == SHORT_PRESS:
                    self.actShort()
                elif self._event_in.e_val == LONG_PRESS:
                    self.actLong()
                else:
                    logging.error(
                        "Not a valid button press value: %s", self._event_in.e_val
                    )
            else:
                logging.error("Invalid event type: %s", self._event_in.e_type)

            # Clear the event, if we still have it at this point
            if self._event_in is not None:
                self._event_in.clear()

        logging.info("Exiting input event monitor for screen %s", self.name)

    async def _refresh(self):
        """
        Coro to keep refreshing the update every `AUTO_REFRESH` milliseconds.

        This method is automatically started as a task from `setup` ONLY IF the
        `AUTO_REFRESH` class attribute is set to a refresh rate of greater than
        0 milliseconds.

        Any derived class should still override the `setup()` method, but for
        convenience, and if you need the auto refresh function, then call the
        super's `setup()` AFTER doing whatever is needed to do the initial
        screen setup.

        The default in this base class is to set `AUTO_REFRESH` to 0, so your
        derived class should explicitly set this to a desired auto refresh
        period if needed, in addition to call to the super's setup() as
        explained above.

        This task will auto terminate when the screen looses focus, but will
        again be started when getting focus later.
        """
        logging.info("Starting auto refresh task for screen %s", self.name)

        while self._display is not None:
            self.update()
            await asyncio.sleep_ms(self.AUTO_REFRESH)

        logging.info("Exiting auto refresh task for screen %s", self.name)

    def focus(
        self, display: SSD1306_I2C, event: asyncio.Event, focus_on_exit: "Screen" = None
    ):
        """
        Called to pass focus to this screen instance.

        Sets up the display and input event signal and then calls `setup()` to
        show the screen.

        Args:
            display: The display we can send output to.
            event: The Input event synchronisation primitive
            focus_on_exit: The screen passing us the focus, may also set a
                screen to pass focus to when this screen exits. This is
                optional, but if passed and the ``screen`` arg when calling
                `_passFocus()` from this screen is None, then this screen will be
                focused on.
        """
        self._has_focus = True
        self._display = display
        self._event_in = event
        self._focus_on_exit = focus_on_exit

        # Create a coro to monitor input events
        asyncio.get_event_loop().create_task(self._inputMonitor())

        # If we did not get a screen to pass focus to when we exit, but we have
        # a saved our callers screen ref if we perhaps passed focus to a sub
        # screen before, we then restore `_focus_on_exit` to our caller's
        # reference so we do not loose that reference.
        if self._focus_on_exit is None and self._save_focus_on_exit is not None:
            self._focus_on_exit = self._save_focus_on_exit
            # To keep things in sync, we also reset our save ref
            self._save_focus_on_exit = None

        self.setup()

    def _passFocus(self, screen: "Screen" | None, return_to_me: bool = False):
        """
        Passes focus on to another screen.

        Any function in this screen can pass the focus to another Screen
        instance via a call to this method.
        Passing the focus to another screen means that we stop monitoring for
        input events (see .run()`) and that we also do not have a display
        to send output to anymore.

        When this screen received focus via the `focus()` method, the caller
        may have "suggested" which Screen instance, it thinks, should receive
        focus when this instance exits or needs to pass focus back/forward.
        This "suggested" Screen instance would then be available in
        `_focus_on_exit`. These "suggestions" makes it easy to dynamically
        chain a hierarchical screen flow together.
        It is called a "suggestion" since it is up to the current screen to
        decide if it will use this suggestion, or pass focus to some other
        screen it would rather use, like a child of it's own, perhaps.

        Regardless, in order to pass focus to this "suggested" screen, you can
        either pass `_focus_on_exit` as the ``screen`` arg (if it is not
        None), or else just pass None for ``screen``.
        If the ``screen`` arg is None, we will assume that the
        `_focus_on_exit` attribute contains a valid screen, and use that
        as the screen to pass focus to here.

        If the assumption is wrong and the screen to receive focus turns out to
        be None, things will break and the developer will end with both pieces :-)

        Args:
            screen: Screen instance to pass focus to, or None to use
                `_focus_on_exit` as the screen to pass focus to. See above.
            return_to_me: If True, we will "suggest" to the screen we are
                passing focus to, to return focus back to us when it exists.
                All this does is pass ``self`` to the `focus()` call we are
                making to ``screen``.
        """
        # Always preserver our callers screen reference, just in case we get
        # focus back to us from a sub screen, and we need to later pass focus
        # back to our caller again.
        self._save_focus_on_exit = self._focus_on_exit

        # If screen is None, we use self._focus_on_exit as the destination
        # screen to pass focus to. We deliberately do not do validation here
        # since we do not know what to do if self._focus_on_exit is invalid.
        # Rather let the app break and the user chase the dev to fix the bug,
        # than hide the bug and make it more difficult to find.
        if screen is None:
            screen = self._focus_on_exit

        logging.info("Passing focus to screen %s", screen.name)

        # Before passing the event, lets just clear it
        self._event_in.clear()

        # Pass the focus on by giving the other screen our display and input
        # event
        screen.focus(self._display, self._event_in, self if return_to_me else None)
        # Now we set our display and input event to None
        self._display = None
        self._event_in = None

    def setup(self):
        """
        Called the first time we get focus.

        Use this to clear and draw the initial screen if needed.

        The base class does nothing other than add a convenient way to add an
        auto refresh task to regularly call `update()` if needed.
        See `_refresh()` and the `AUTO_REFRESH` comment for more info.

        If the refresh functionality is needed, best would be that your derived
        class still overrides this setup method, and then AT THE END of your
        setup, call this setup via ``super().setup()``.

        Also note that you have to set `AUTO_REFRESH` to a positive refresh rate
        for this to work.
        """
        # Create the refresh task on the current asyncio loop if we have a
        # positive AUTO_REFRESH rate
        if self.AUTO_REFRESH > 0:
            asyncio.get_event_loop().create_task(self._refresh())

    def update(self):
        """
        General update method.

        This method can be used to do regular screen updates while running .
        Useful for screens that are updated on receiving external signals or
        time based.
        Use the `setup()` (or override `__init__`) to set up any task or hooks
        that will call this method to make screen updates.

        The base class does nothing for this, and it should be overwritten in
        subclasses.
        """

    def actCCW(self):
        """
        Received the UP action event.

        The derived class should override this if needed.
        """
        logging.info("Screen %s ignoring the UP action.", self.name)

    def actCW(self):
        """
        Received the DOWN action event.

        The derived class should override this if needed.
        """
        logging.info("Screen %s ignoring the DOWN action.", self.name)

    def actShort(self):
        """
        Received the SHORT PRESS action event.

        As a convenience, this is a default "return focus" function if we
        received a screen to return focus to on exit in the `focus()` call to
        us.

        If `_focus_on_exit` is not None, this method will call
        `_passFocus()` to return focus to the "on exit" `Screen`.

        The derived class could override this if needed.
        """
        logging.info("Screen %s received the SHORT PRESS action.", self.name)
        if self._focus_on_exit is not None:
            logging.info("Screen %s auto returning focus on short click", self.name)
            self._passFocus(None)
        else:
            logging.info("Screen %s ignoring the SHORT PRESS action.", self.name)

    def actLong(self):
        """
        Received the LONG PRESS action event.

        The derived class should override this if needed.
        """
        logging.info("Screen %s ignoring the LONG PRESS action.", self.name)
