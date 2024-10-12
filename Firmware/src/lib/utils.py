"""
Various utilities and functions.
"""


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
