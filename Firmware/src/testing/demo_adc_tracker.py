"""
Quick demo to see if the ADC Tracker works for Battery 0.
"""

import sys
import gc
import select
import uasyncio as asyncio
from machine import Pin
from lib import ulogging
from lib.adc_tracker import ADCTracker

from config import (
    B0_CH_CTL,
    B0_DCH_CTL,
    B0_CH_C,
    B0_DCH_C,
    B0_OB_V,
)

ADC_CFG = [
    B0_CH_C,
    B0_DCH_C,
    B0_OB_V,
]


quiet = False


async def control(tracker):
    """
    Coro to monitor the keyboard for control commands....
    """
    global quiet

    # Set up the control pins
    ch_ctrl = Pin(B0_CH_CTL, Pin.OUT, value=0)
    dch_ctrl = Pin(B0_DCH_CTL, Pin.OUT, value=0)

    # Set up a keyboard poller and register stdin for input events
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)

    while True:
        # We always sleep a bit to allow other coros to run between keyboard
        # reads or polls.
        await asyncio.sleep(0.1)

        # Check if there is any input - we set timeout to 0 so we return
        # immediately if nothing on input
        res = poller.poll(0)

        # If res is empty, then we timed out and nothing is available.
        if not res:
            continue

        # If there is input or some error, we will only have one element in res
        # which will be a tuple as (stream, event). We do not care about the
        # stream, because we know it's stdin, but we need to deal with errors
        # that may be indicated in the event
        _, event = res[0]

        # On any error, we unregister the stream from the poller and exit
        if event & (select.POLLHUP | select.POLLERR):
            ulogging.error("Poll error on stdin. Event: %s", f"b{event:08b}")
            return

        # We can read the input
        ch = sys.stdin.read(1)

        if ch == "?":
            print(
                """
                \rAvailable keys:
                \r* ? : Show this help
                \r* s : Show the current control state
                \r* c : Toggle charge control
                \r* d : Toggle discharge control
                \r* R : Reset all charge monitor values
                \r* q : Toggle Charge/Discharge display update
                \r* m : Show current memory state
                """
            )
        elif ch == "s":
            print(
                f"""
                \rCharge Control:    {'On' if ch_ctrl() else 'Off'}
                \rDischarge Control: {'On' if dch_ctrl() else 'Off'}
                """
            )
        elif ch in ("c", "C"):
            ch_ctrl.value(not ch_ctrl.value())
            print(f"Charge control set to: {'On' if ch_ctrl() else 'Off'}")
        elif ch in ("d", "D"):
            dch_ctrl.value(not dch_ctrl.value())
            print(f"Discharge control set to: {'On' if dch_ctrl() else 'Off'}")
        elif ch == "R":
            tracker.reset(-1)
            print("Charge/Discharge track values have been reset.")
        elif ch == "q":
            quiet = not quiet
            print(f"Charge/Discharge value display: {'Off' if quiet else 'On'}")
        elif ch == "m":
            print(
                f"Memory: Alloc={gc.mem_alloc()}, Free={gc.mem_free()}, Threshold: {gc.threshold()}"
            )
        else:
            print("Invalid key. Try ?")


async def showValues(tracker):
    """
    Coro to continually show the tracked ADC values
    """

    global quiet

    while True:
        await asyncio.sleep(2)

        if quiet:
            continue

        ch = tracker.getVal(0, unit=True, intermediate=True)
        dch = tracker.getVal(1, unit=True, intermediate=True)
        b_v = tracker.getVal(2, unit=True)
        out = f"CH: {ch[0]:>11s} ({ch[1]:>11s}, {ch[2]:>11s}) | "
        out += f"DCH: {dch[0]:>11s} ({dch[1]:>11s}, {dch[2]:>11s}) | "
        out += f"BatV: {b_v:>11s}"
        print(out)


def demoBatMon(i2c):
    """
    Monitors the battery defined by ADC_CFG.
    """
    # We will use the asyncio event loop to created the various tasks for this
    # demo
    eloop = asyncio.get_event_loop()

    # Create the ADCTracker instance and start an asyncio task to track the
    # channels
    tracker = ADCTracker(i2c, ADC_CFG, logger=ulogging)
    eloop.create_task(tracker.track())

    # Create a task to display the values every few seconds
    eloop.create_task(showValues(tracker))

    # Monitor for keyboard input
    eloop.create_task(control(tracker))
