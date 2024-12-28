"""
Tester for the lib.utils.stdinKeyMonitor.

How to:
    * Make sure ``lib/utils.py`` is updated on the destination MCU - run 
      ``make upload`` or copy it directly using ``mpremote``
    * Copy this file as main.py::

        mpremote fs cp testing/test_kb_input.py :main.py

    * Run this test with ``mpremote``::

        mpremote repl

        Connected to MicroPython at /dev/ttyACM0
        Use Ctrl-] or Ctrl-x to exit this shell

    * Now press Ctrl-D to run main. Press some keys to see the callback handler
      being called.
"""

from lib.utils import stdinKeyMonitor, asyncio


def cbDefault(ch):
    """
    Default callback function
    """

    print(f"cbDefault: Received key: '{ch}'")


def main():
    """
    Main runtime entry point
    """

    print("Starting keyboard tester.")

    # Callback config
    cb_conf = {"_default_": (cbDefault,)}

    print("Staring monitor task...")
    asyncio.run(stdinKeyMonitor(cb_conf, sleep_ms=500))


if __name__ == "__main__":
    main()
