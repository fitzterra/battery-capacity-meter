"""
This file is executed on every boot (including wake-boot from deepsleep)
"""

import os
import machine


def recordResetReason():
    """
    Records the last reset cause to a file a file called 'reset_cause.log' on
    the FS root.

    This is mainly so we can see when a Watchdog reset may have happened, or
    any reboot reason we did not manually perform.

    We keep the last 20 reboot reasons in the file. Unfortunately at this point
    we have no time reference so there is no way to know when the last reboot
    was, but we keep a count of reboots. So, after the 25th reboot, the file
    may look like this (only showing the last 8 entries):

        18    Soft reset
        19    Soft reset
        20    Hard reset
        21    Soft reset
        22    Soft reset
        23    Watchdog reset
        24    Soft reset
        25    Soft reset

    This file can be retrieved via MQTT (see `telemetry.messages`) and can give
    some idea of reboot reasons. The count and reason are tab separated.
    """

    # Map of reset flags to strings
    causes_map = {
        machine.PWRON_RESET: "Power-on",
        machine.HARD_RESET: "Hard reset",
        machine.WDT_RESET: "Watchdog reset",
        machine.DEEPSLEEP_RESET: "Deep sleep wake",
        machine.SOFT_RESET: "Soft reset",
    }

    # The max number of entries to keep
    max_entries = 20

    # The last reset reason can be retrieved like below and then mapped to a
    # string
    last_reason = causes_map.get(machine.reset_cause(), "Unknown")

    # Hardcoded reset log file
    log_f = "/reset_cause.log"

    # Ensure file exists
    if log_f not in os.listdir():
        with open(log_f, "w", encoding="utf-8"):
            pass

    try:
        # Open for reading and writing
        with open(log_f, "r+", encoding="utf-8") as l_file:
            # Read all lines, strip newlines and split on tabs, keeping only
            # the last max_entries
            lines = [l.strip().split("\t") for l in l_file][-max_entries:]

            # Preset the last number o None in case we can not determine it
            # from the file
            last_num = None

            # Try get the last number used from the last line we read in
            if lines:
                last_num = lines[-1][0]
                if last_num.isnumeric():
                    last_num = int(last_num)

            # If we did not get a last number, set it to 0
            if last_num is None:
                last_num = 0
            # ... and then increment the last number
            last_num += 1

            # Append the new number and last reset reason we got above to lines
            # as a 2-tuple
            lines.append((str(last_num), last_reason))

            # We are going to write the whole file again
            l_file.seek(0)

            for line in lines:
                # Use a tab as separator for each number and reason
                l_file.write("\t".join(line) + "\n")
            # Make sure we clear any extra crud if the new content is less than
            # the old in the file
            l_file.truncate()
    except Exception as exc:
        print(f"Error updating last reset reason log ({log_f}): {exc}")


recordResetReason()
