"""
Serial UI for the `BatteryController`.

Create a symlink to this module named ``main.py`` and upload to use the serial
UI.
"""

import sys
import uasyncio as asyncio

from lib.utils import stdinKeyMonitor
from lib.bat_controller import BatteryController
from lib import ulogging as logging

from config import HARDWARE_CFG


class BCSerialUI:
    """
    A UI for the `BatteryController` over the serial interface.

    This UI allows monitoring and controlling the `BatteryController` from a
    connected computer of USB or serial interface.

    This type of interface is very limited since full control over the
    connected terminal screen is too complex for what this UI is meant for.

    All we do here (for now) is output the current BC status and allow keyboard
    input to control things like starting, pausing, resuming charging and
    discharging etc.

    The display will be a continuous scrolling display of the current status.
    The ``?`` key will show a menu of available keys.
    """

    def __init__(self, bcs: list(BatteryController)):
        """
        Instance initializer.

        Args:
            bcs: A list of `BatteryController` instances.
        """
        # We need at least one
        if not bcs:
            logging.error(
                "%s: At least one BatteryController needed. Aborting.",
                self.__class__.__name__,
            )
            return

        # List of BCs
        self.bcs = bcs
        # Index into bcs of the current active BC
        self.active_bc = 0
        # A shortcut to self.bcs[self.active_bc] - set by setActive
        self.bc = None

        self.setActive(0)

        # Start the status monitor task
        asyncio.create_task(self.statusMonitor())
        # And the key monitor will key input call back to keyInput
        asyncio.create_task(stdinKeyMonitor({"_default_": (self.keyInput,)}, logging))

    def setActive(self, idx: int):
        """
        Sets the active BC to monitor from index supplied.

        Args:
            idx: Index into `bcs` for the BC to make active.
        """
        if not 0 <= idx < len(self.bcs):
            logging.error(
                "%s : Invalid BC index to make active: %s", self.__class__.__name__, idx
            )
            return

        self.active_bc = idx
        # Set the active BC shortcut
        self.bc = self.bcs[self.active_bc]
        self.output("\nSwitching to BC: %s\n", self.bc)

    def output(self, msg: str, *args: tuple, end="\n"):
        """
        Prints the message and to stdout.

        Args:
            msg: A string with optional % formatting options as for logging.
            args: Arguments for all % formatting options in ``msg``
        """
        print(msg % args, end=end)

    def keyInput(self, ch):
        """
        Callback for any keyboard input.

        Args:
            ch: The key input character
        """

        if ch in ["0", "1", "2", "3"]:
            # Set the active controller
            self.setActive(ord(ch) - ord("0"))
            return

        if ch == "i":
            # Confirm the id
            self.bc.setID()
            return

        if ch == "c":
            # Charge toggle
            self.bc.charge()
            return

        if ch == "d":
            # Discharge toggle
            self.bc.discharge()
            return

        if ch == "p":
            # Pause toggle
            if self.bc.state in (self.bc.S_CHARGE_PAUSE, self.bc.S_DISCHARGE_PAUSE):
                self.bc.resume()
            else:
                self.bc.pause()
            return

        if ch == "r":
            # Full reset if we are in Yanked state, else reset metrics
            if self.bc.state == self.bc.S_YANKED:
                self.bc.reset()
            else:
                self.bc.resetMetrics()
            return

        print(f"Invalid input: {ch}")

    async def statusMonitor(self):
        """
        Asyncio task to output regular BC status information to stdout.

        This task will be started automatically from `__init__` and will start
        producing output as soon as the async loop starts running.
        """
        # We do a lot of access to protected members here, so
        # @pylint: disable=protected-access

        # How long to delay between updates
        update_delay = 500
        # How often to print a header
        header_interval = 10
        # Counter to when next to print a header
        header_cnt = 0

        # Max width for the state name
        st_w = max(len(n) for n in self.bc.STATE_NAME)

        # The header
        # NOTE: Line draw characters are Unicode points from here:
        #       https://en.wikipedia.org/wiki/Box-drawing_characters
        header = (
            f"┃ Name ┃ {'State':<{st_w}} | {'ID':<10} "
            + "┃  V mV | V SampT "
            + "┃ S | P | Ch mA | Ch mAh | Ch Tm | C SampT "
            + "┃ S | P | Dch mA | Dch mAh | Dch Tm | D SampT "
            + "┃"
        )

        # We run all the time
        while True:
            await asyncio.sleep_ms(update_delay)

            if header_cnt == 0:
                self.output("\x1B[4m" + header + "\x1B[0m")
                header_cnt = header_interval

            header_cnt -= 1

            ch_vals = self.bc.charge_vals
            dch_vals = self.bc.discharge_vals

            self.output(
                f"┃ {self.bc._name:4.4s} "
                + f"┃ {self.bc.state_name:<{st_w}} "
                + f"| {self.bc._bat_id:<{10}} "
                + f"┃ {self.bc.bat_v:>5} "
                + f"| {self.bc._v_mon._tm_adc_sample or 0.0:>5.1f}ms "
                + f"┃ {self.bc._pin_ch.value()} "
                + f"| {'Y' if self.bc._ch_mon.paused else 'N'} "
                + f"| {ch_vals[2]:>5} "
                + f"| {ch_vals[4]:>6} "
                + f"| {ch_vals[5]:>5} "
                + f"| {self.bc._ch_mon._tm_adc_sample or 0.0:>5.1f}ms "
                + f"┃ {self.bc._pin_dch.value()} "
                + f"| {'Y' if self.bc._dch_mon.paused else 'N'} "
                + f"| {dch_vals[2]:>6} "
                + f"| {dch_vals[4]:>7} "
                + f"| {dch_vals[5]:>6} "
                + f"| {self.bc._dch_mon._tm_adc_sample or 0.0:>5.1f}ms "
                + "┃",
            )


def asyncIOExeption(loop, context):
    """
    Global Asyncio exception handler.
    """
    print("Global handler")
    sys.print_exception(context["exception"])  # pylint: disable=no-member
    loop.stop()
    sys.exit()  # Drastic - loop.stop() does not work when used this way


def main():
    """
    Main entry
    """
    # Instantiate all configured battery controllers
    bat_ctls = [BatteryController(*c) for c in HARDWARE_CFG]

    # Instantiate the serial UI monitor
    BCSerialUI(bat_ctls)

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(asyncIOExeption)
    loop.run_forever()


main()
