import logging


TRACE = logging.DEBUG - 5


class TraceLogger(logging.getLoggerClass()):
    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)

        logging.addLevelName(TRACE, "TRACE")

    def trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE):
            self._log(TRACE, msg, args, **kwargs)
