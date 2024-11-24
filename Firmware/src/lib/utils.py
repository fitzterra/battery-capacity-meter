"""
Various utilities and functions.
"""

import time


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


def genBatteryID(last_id: int = 0):
    """
    Generates a new Battery ID.

    The Battery ID is used to identify individual batteries in order to track
    their capacity over time.

    This function will generate a new ID for a battery that does not have one
    already. The Battery ID can be any string, but to make things easier, we
    standardise on an ID of:

        yyyymmddnnn

    where:

        * ``yyyymmdd`` is the local year, month and date
        * ``nnn`` will be ``last_id + 1``. The idea being that the last day ID
            used is tracked somewhere else and this will be increased for each
            new battery tested for that day.

    Note:
        The local date and time will be set to 2000-01-01 00:00:00 on power up.
        To get an accurate battery ID, it is important to make sure `syncTime()`
        was run and has been successful. If not, then the default date/time
        will be used.

    Args:
        last_id: The last ID used today. It will be incremented and returned as
            the second element of the returned tuple. The caller should then
            use this value to update wherever it stores the last ID used for
            the day. This will then be the input again on the next call here.

    Returns:
        A two tuple:
            (battery ID string as above, new ``last_id`` value)
    """
    new_id = last_id + 1
    # We are only interested in the 1st three parts, year, month, day from
    # localtime.
    # We set the formatting here to 2 digits with leading zero. This will make
    # 1 digit day and month values leading zero 2 digits, but since year is
    # already 4 digits, it will not be truncated or changed.
    date = "".join(f"{p:02d}" for p in time.localtime()[:3])

    return (f"{date}{new_id:03d}", new_id)
