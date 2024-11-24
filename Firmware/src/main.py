"""
Main application entry point.
"""

import sys
import select
import utime as time
import uasyncio as asyncio
from config import i2c, B0, B1, B2, B3
from lib import ulogging as logger
from lib.charge_controller import BatteryController
from screens import uiSetup
from net_conn import disconnect, connect, monitor


async def showState(ch_ctl: BatteryController):
    """
    Shows the current charge controller state on standard out.

    Args:
        ch_ctrl: Charge controller instance
    """
    # {
    #     'ch_s': bool,  # True if currently charging, False otherwise
    #     'dch_s': bool, # True if currently discharging, False otherwise
    #     'bat': bool,   # True if not dis/charging and a battery is present
    #     'bat_v': float,# Battery or output voltage value in mV
    #     'v_jump': bool,# True if a large battery voltage jump was detected
    #     'ch': float    # Last charge value measured in mAh
    #     'ch_t': int    # Last charge period in seconds
    #     'ch_c': int    # Last charge current in mA
    #     'dch': float   # Last discharge value measured in mAh
    #     'dch_t': int   # Last discharge period in seconds
    #     'dch_c': int   # Last discharge current in mA
    # }

    # Set up a keyboard poller and register stdin for input events
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)

    header = (
        "| State | Ch | DCh | Bat V | VJump | Ch C | CJump "
        "| Dch C | DcJump | MonT | ID         |"
    )
    show_header = 10

    while True:

        # Wait for key input without blocking asyncio
        start_at = time.ticks_ms()
        while True:
            await asyncio.sleep_ms(1)
            if time.ticks_diff(time.ticks_ms(), start_at) >= 2000:
                break
            # Check if there is any input
            res = poller.poll(0)
            if res:
                break

        # If res is empty, then we timed out and nothing is available.
        if res:
            # We can read the input
            ch = sys.stdin.read(1)
            if ch == "c":
                print("Toggling Charge Control...")
                st = ch_ctl.charge("t")
                if not st and st is not None:
                    ch_ctl.reset(["ch_mon"])
            elif ch == "d":
                print("Toggling Discharge Control...")
                st = ch_ctl.discharge("t")
                if not st and st is not None:
                    ch_ctl.reset(["dch_mon"])
            elif ch == "r":
                print("Resetting all monitors...")
                ch_ctl.reset()
            else:
                print("ERROR: Invalid input.")

        state = ch_ctl.status()
        if show_header == 10:
            print(header)
            show_header = 0

        print(
            f"| {int(state['state']):>5} "
            + f"| {state['ch_s']}  "
            + f"| {state['dch_s']}   "
            + f"|{int(state['bat_v']):>5}mV"
            + f"| {state['v_jump']:6}"
            + f"|{int(state['ch_c']):>4}mA"
            + f"| {state['c_jump']:6}"
            + f"|{int(state['dch_c']):>5}mA"
            + f"| {state['dc_jump']:7}"
            + f"| {state['mon_t']:5}"
            + f"| {str(state['bat_id']):>11}"
            + "|"
        )
        show_header += 1


# Disconnect and then reconnect the network
try:
    disconnect()
    time.sleep_ms(500)
    connect()
except Exception as exc:
    logger.error("Error connecting to network: %s", exc)

# Set up the charge controller and screens
ch_ctls = [BatteryController(i2c, bat_cfg) for bat_cfg in (B0, B1, B2, B3)]
uiSetup(ch_ctls)

# get the asyncio loop and run forever
loop = asyncio.get_event_loop()
loop.create_task(showState(ch_ctls[0]))
loop.create_task(monitor())
loop.run_forever()
