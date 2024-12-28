"""
Various utilities and functions.

Attributes:
    BAT_CNT: Universal auto updated counter for every new battery ID generated
        by `genBatteryID()`

        This is to ensure that every `BatteryController` will get a unique ID.
        If we left the `BatteryController` instance to manage this ID counter,
        only batteries in that controller will get unique IDs, but there will
        almost certainly be duplicates between multip-le controllers as they
        each match other's counters.
"""

import sys
import select
import utime as time
import uasyncio as asyncio

BAT_CNT: int = 0


class NullLogger:
    """
    Class instance that can be used to set up a null logger.

    In fact, it can fake an instance of most objects since it will accept any
    attributes set on the instance, and any methods that will be called will
    simply be ignored and a None will be returned.

    This makes in useful for creating a logger that does nothing, but allows
    the code in scope to still make logger calls as if this is a proper logger
    instance. Example:

    .. python::

        def usefulFunction(arg1, logger=None):
            ```
            Useful function that takes an optional logger instance
            ```
            _logger = logger if logger else NullLogger()

            # Do stuff...
            tasks = 7

            # .. then log something
            _logger.info("Completed %s tasks", tasks)

            # which will be logged if a looger was provided or ignored if no
            # logger was passed without having to cchange the code flow based
            # on whether a logger is available.

    """

    # pylint: disable=too-few-public-methods

    def __getattr__(self, name):
        """
        Sets up a getter that will return a method that accepts positional as
        well as keyword args, but does nothing when called.

        This allows you to call any method on an instance of this class with any
        number of args without it erroring out, but also not doing anything.
        """

        # pylint: disable=unused-argument
        def method(*args, **kwargs):
            """
            This is the do-nothing method....
            """

        # we return the do-nothing method on any call for getting instance
        # attributes.
        return method


def genBatteryID():
    """
    Generates a new Battery ID.

    The Battery ID is used to identify individual batteries in order to track
    their capacity over time.

    This function will generate a new ID for a battery that does not have one
    already. The Battery ID can be any string, but to make things easier, we
    standardise on an ID of:

        yyyymmddHH

    where:

        * ``yyyymmdd`` is the local year, month and date
        * ``HH`` will be the hex value of the battery counter `BAT_CNT` that
            will be used to get unique battery IDS on each generation call.

    Note:
        The local date and time will be set to 2000-01-01 00:00:00 on power up.
        To get an accurate battery ID, it is important to make sure `syncTime()`
        was run and has been successful. If not, then the default date/time
        will be used.

    Returns:
        The newly generated ID as a string as mention above.
    """
    global BAT_CNT  # It's OK @pylint: disable=global-statement

    # Increment the unique counter.
    BAT_CNT += 1

    # Check for overflow.
    # NOTE: This could potentially mean that we can duplicate a Battery ID,
    # this will only happen if we change more the 254 batteries in one day -
    # highly unlikely.
    if BAT_CNT > 0xFF:
        BAT_CNT = 1

    # We are only interested in the 1st three parts, year, month, day from
    # localtime.
    # We set the formatting here to 2 digits with leading zero. This will make
    # 1 digit day and month values leading zero 2 digits, but since year is
    # already 4 digits, it will not be truncated or changed.
    date = "".join(f"{p:02d}" for p in time.localtime()[:3])

    return f"{date}{BAT_CNT:02X}"


def ewAverage(alpha: float, new: float | int, avg: float | int) -> float:
    """
    Function to calculate an Exponentially Weighted Average of a series of data
    points.

    This is useful to smooth out ADC readings over time or sample window, but
    without having to store all intermediate window values.

    See Wikipedia_ for in-depth details, but this idea was taken from here_ and
    adapted. The source code also contains more in-depth details.

    In order to use this function, ``alpha`` should be calculated and stored
    locally by the caller to be the sample window over which we will be
    averaging. This is basically the inverse of window size:

        alpha = 1 / samples

    Args:
        alpha: See above
        new: The new sample just read
        avg: The current running average.

            In order to ensure accurate data from the first call, if ``avg`` is
            None, then ``new`` will be returned directly as the new filtered
            average.

            This means that the average variable can be initialized to ``None``
            and the caller does not have to check on every call if we have a
            starting average yet, and if so, pass the new value in both ``new``
            and ``avg`` so as to not have a skewed starting average.

    Returns:
        The new filtered average float value

    .. _WikiPedia: https://en.wikipedia.org/wiki/Exponential_smoothing
    .. _here: https://forums.raspberrypi.com/viewtopic.php?t=69797#p508217
    """
    # In case the more simple description in the link above gets lost, here it
    # is with some changes to fit this situation:
    #
    # An exponentially weighted average is an average of all the previous data
    # points, but weighted so that the most recent values contribute the most,
    # and the contributions of older and older data values decay exponentially.
    #
    # Consider the simplest case where alpha = 1/2. Then the current average is
    # 1/2 of the most recent reading, plus 1/4 of the previous reading, plus
    # 1/8 of the reading before that, plus 1/16 of the reading before that, all
    # the way back to the start. (Notice this adds to 1, so it is a true
    # average.)
    #
    # One of the advantages is that we do not need to retain the individual
    # values. If we multiply the current average by 1/2, we have automatically
    # shifted all the contributions back one place, and then we can add 1/2 of
    # the next reading.
    #
    # This works just as well with other alpha values. (For alpha=1/30, the
    # contribution of the kth term is (1/30)*(29/30)**k, so multiply by 29/30
    # moves them down and we add 1/30 of the next reading.)
    #
    # I do not think it is necessary or beneficial to change the rules at the
    # beginning, except that we may want to use the first reading as a guess at
    # the long-term average if there is no better guess available. If the
    # initial averages are displaced as a result, then just drop the first few
    # outputs.
    #
    # In Python:
    #
    #     N = 30
    #     alpha = 1.0/N  # or: 2.0/(N+1)
    #     average = wind_tally() # or: guess_at_long_term_average()
    #     while True:
    #         count = wind_tally()
    #         average = alpha*count + (1-alpha)*average
    #         print("current = ", count, ", average = ", average)
    #         time.sleep(1)
    #
    # Compared to a simple average of the last N values, the exponentially
    # weighted average is more affected by the recent readings, but less
    # affected by readings suddenly dropping out of the window. So it is
    # arguably both more smooth and faster to respond to genuine trends.

    # Check for average initialization
    if avg is None:
        return new

    return alpha * new + (1 - alpha) * avg


async def stdinKeyMonitor(
    cb_conf: dict, logger: callable | None = None, sleep_ms: int = 5
):
    """
    An asyncio key press monitor for input on stdin.

    This function can be used as a keyboard keypress handler on the stdin
    stream.

    Start it as an asyncIO task, passing in a callback config dictionary for one
    or more callbacks to call per key press read on stdin.

    It will then monitor for input on stdin, and call any corresponding
    callbacks from the callback config.
    The callback config dict looks like this::

        {
            key: (callback, (arg, arg,...)),
            ...
        }

    where:
        * ``key`` is the character to check for. A key of ``_default_`` is the
          default callback handler.
        * ``(...)`` is a tuple the first element the callable, forllowed by and
          optional list of additional arguments to pass to the callback.

    The callback should receive the key character as the first arg, and
    optionally any additional args specified.

    Warning:
        This is meant for simple one charter key strokes - any exotic inputs
        like control keys or anything doing multiple characters per keystroke
        is going to cause some interesting results - you have been warned
        |cowboy|

    Args:
        cb_conf: See above.
        logger: If supplied it must a logger type instance for output info or
            errors. will call ``logger.info()`` for info messages, and
            ``logger.error()`` for error messages.
        sleep_ms: The time in milliseconds to sleep between polling for any
            input on stdin. This is an asyncio sleep, so other asyncIO tasks
            will be scheduled in this time.

    .. |cowboy| unicode:: U+1F920
    """
    # Set up a keyboard poller and register stdin for input events
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)

    # This will be the default callback if defined.
    default_cb = cb_conf.get("_default_", None)

    msg = "Starting stdinKeyMonitor..."
    if logger:
        logger.info(msg)
    else:
        print(msg)

    while True:
        # Check if there is any input without blocking
        res = poller.poll(0)
        if not res:
            # No input, so let some other task get some time before we poll
            # again.
            await asyncio.sleep_ms(sleep_ms)
            continue

        # Read one character from stdin.
        ch = sys.stdin.read(1)
        # Do we have a callback for this key?
        cb = cb_conf.get(ch, default_cb)
        if not cb:
            msg = "stdinKeyMonitor: No callback for `%s`"
            if logger:
                logger.info(msg, ch)
            else:
                print(msg % ch)
            continue

        try:
            # Call it passing the character and optional additional args
            cb[0](ch, *cb[1:])
        except Exception as exc:
            msg = "stdinKeyMonitor: Error calling callback for '%s': %s"
            if logger:
                logger.error(msg, ch, exc)
            else:
                print(msg % (ch, exc))
