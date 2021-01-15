import logging

LOGGER = logging.getLogger(__name__)
_TRACE = 5


def _find_trace_level() -> int:
    if logging.getLevelName(_TRACE) != f"Level {_TRACE}":
        # If a level 5 exists, use it
        return _TRACE
    elif hasattr(logging, "TRACE") and logging.NOTSET < logging.TRACE < logging.DEBUG:
        # If a valid TRACE level exists that is between 0 and 10, use it
        return logging.TRACE
    elif LOGGER.level == logging.DEBUG:
        # If `zigpy_znp.logger` is explicitly passed `DEBUG` as a log level, enable
        # `TRACE` logging under the `DEBUG` level
        return logging.DEBUG
    else:
        # Otherwise, do not log
        return logging.NOTSET


TRACE = _find_trace_level()
