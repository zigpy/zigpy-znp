import logging

_TRACE = 5


def _find_trace_level() -> int:
    if logging.getLevelName(_TRACE) != f"Level {_TRACE}":
        # If a level 5 exists, use it
        return _TRACE
    elif hasattr(logging, "TRACE") and logging.NOTSET < logging.TRACE < logging.DEBUG:
        # If a valid TRACE level exists that is between 0 and 10, use it
        return logging.TRACE
    else:
        # Otherwise fall back to logging everything as DEBUG
        return logging.DEBUG


TRACE = _find_trace_level()
