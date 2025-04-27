"""
Shamelessly stolen from:

    https://github.com/pfalcon/pycopy-lib/tree/master/ulogging

and broken out into a local module, with some mods.

Attributes:
    CRITICAL: Constant for CRITICAL logolevel.
    ERROR: Constant for ERROR logolevel.
    WARNING: Constant for WARNING logolevel.
    INFO: Constant for INFO logolevel.
    DEBUG: Constant for DEBUG logolevel.
    NOTSET: Constant for NOTSET logolevel.
    _level_dict: Mapping of log level constants to strings.
    _stream: The file type object to write log messages to.
    telemetry_logs: A FIFO list for log messages to be emitted as telemetry
        logs.

        This FIFO will be monitored by `telemetry.broadcast` for any new
        entries and if found, will publish them as telemetry logs, and then
        remove them from this list.

        To prevent runaway memory usage in case the telemetry logger is offline
        or have any issues, `Logger.telemetry_log` will keep this list to not
        grow beyond 20 messages, removing older messages if needed.
    _level: The global log level. Can be changed via `basicConfig`
    _level_telemertry: The level for logging as telelmetry logs. Can be changed
        via `setTelemetryLevel`
    _loggers: Cached name `Logger` instances.

        The `getLogger` function will cache an instance of the named logger in
        this dict every time it is called and the named logger does not already
        exist in the cache. If it is in the cache, it is returned as the
        logger, thus saving the cycles of instantiating a new logger for every
        name.
"""

# pylint: disable=invalid-name

import sys as usys

CRITICAL = 50
ERROR = 40
WARNING = 30
INFO = 20
DEBUG = 10
NOTSET = 0

_level_dict = {
    CRITICAL: "CRIT",
    ERROR: "ERROR",
    WARNING: "WARN",
    INFO: "INFO",
    DEBUG: "DEBUG",
}

_stream = usys.stderr

# Used for publishing log messages as telemetry log
# Each entry will be a tuple as: (level, msg)
telemetry_logs = []

_level = INFO
_level_telemertry = ERROR
_loggers = {}


class Logger:
    """
    Main logger class.
    """

    # Default level
    level = NOTSET

    def __init__(self, name: str):
        self.name = name
        self.name_out = "" if not name else f"{name}"

    def _level_str(self, level: int):
        l = _level_dict.get(level)
        if l is not None:
            return l
        return f"LVL{level}"

    def setLevel(self, level: int):
        """
        Sets the log level

        Args:
            level: The level to set.
        """
        self.level = level

    def isEnabledFor(self, level: int):
        """
        Checks if logging is enabled for the given level by comparing it
        against the current log level.

        Args:
            level: Level to test
        """
        return level >= (self.level or _level)

    def telemetry_log(self, level: int, msg: str, *args):
        """
        Like `log` but for pushing log messages onto `telemetry_log` to be
        picked up by `telemetry.broadcast` and published via MQTT.

        We are called from `log` after doing the stream logging.

        .. note::

            The level for telemetry logging is only determined by
            `_level_telemertry` which can be changed from the default ``ERROR``
            to any any other level by calling `setTelemetryLevel`.

        .. note::
            To protect against `telemetry_logs` growing uncontrollably if the
            network is down for example, we will remove the oldest message
            where if the log is longer than 20 messages.
        """
        if level >= _level_telemertry:
            # Protect against runaway logs
            if len(telemetry_logs) >= 20:
                telemetry_logs.pop(0)

            log_msg = ""
            if self.name_out:
                log_msg = f"{self.name_out}: "

            # Append a tuple of (level, msg) to the telemetry_logs list
            telemetry_logs.append(
                (
                    self._level_str(level),
                    log_msg + (msg % args),
                )
            )

    def log(self, level: int, msg: str, *args):
        """
        Generates a log message.

        Args:
            level: The level to log the message at.
            msg: The message to log. May contain '%' format specifiers for
                string interpolation.
            *args: Any value(s) to interpolate into msg if needed.
        """
        if level >= (self.level or _level):
            _stream.write(f"{self._level_str(level)}{self.name_out}:")
            if not args:
                print(msg, file=_stream)
            else:
                print(msg % args, file=_stream)

        # Chain to telemetry logger
        self.telemetry_log(level, msg, *args)

    def debug(self, msg: str, *args):
        """
        Wrapper for self.log to log at the DEBUG level.
        """
        self.log(DEBUG, msg, *args)

    def info(self, msg: str, *args):
        """
        Wrapper for self.log to log at the INFO level.
        """
        self.log(INFO, msg, *args)

    def warning(self, msg: str, *args):
        """
        Wrapper for self.log to log at the WARNING level.
        """
        self.log(WARNING, msg, *args)

    def error(self, msg: str, *args):
        """
        Wrapper for self.log to log at the ERROR level.
        """
        self.log(ERROR, msg, *args)

    def critical(self, msg: str, *args):
        """
        Wrapper for self.log to log at the CRITICAL level.
        """
        self.log(CRITICAL, msg, *args)

    def exc(self, e, msg: str, *args):
        """
        Wrapper for self.log to log at the ERROR level, and also log any
        excection traceback messages.
        """
        self.log(ERROR, msg, *args)
        usys.print_exception(e, _stream)

    def exception(self, msg: str, *args):
        """
        Alternate for self.exc()
        """
        self.exc(usys.exc_info()[1], msg, *args)


def getLogger(name: str = None):
    """
    Returns the named logger, creating it if it does not exist yet.
    """
    if name in _loggers:
        return _loggers[name]
    l = Logger(name)
    _loggers[name] = l
    return l


def info(msg: str, *args):
    """
    Quick helper function to log an info message.
    """
    getLogger(None).info(msg, *args)


def error(msg: str, *args):
    """
    Quick helper function to log an error message.
    """
    getLogger(None).error(msg, *args)


def debug(msg: str, *args):
    """
    Quick helper function to log a debug message.
    """
    getLogger(None).debug(msg, *args)


def setTelemetryLevel(level: int = ERROR):
    """
    Sets the level at which to send logs as telemetry logs.
    """
    global _level_telem
    _level_telem = level


def basicConfig(
    level: int = INFO, filename: str = None, stream: object = None, format: None = None
):
    """
    Does basic config for logging.

    Args:
        level: The level to log at. Default is INFO.
        filename: For compatibility. Must be None
        stream: An IO Stream type instance to send log output to. Defaults to
            the global ``_stream`` variable which is normally ``sys.stderr``.
        format: For compatibility. Must be None
    """
    # Shut up about 'format' arg and global usage @pylint: disable=redefined-builtin,global-statement
    global _level, _stream
    _level = level
    if stream:
        _stream = stream
    if filename is not None:
        print("logging.basicConfig: filename arg is not supported")
    if format is not None:
        print("logging.basicConfig: format arg is not supported")
