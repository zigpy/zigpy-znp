def test_no_trace_logger():
    from zigpy_znp.utils import TraceLogger, TRACE
    import logging

    assert logging.getLoggerClass() is TraceLogger

    LOGGER = logging.getLogger("test")
    LOGGER.setLevel(TRACE)
    LOGGER.debug("test")
    LOGGER.trace("test")


def test_existing_trace_logger():
    import logging

    class MyTraceLogger(logging.getLoggerClass()):
        def trace(self):
            pass

    logging.setLoggerClass(MyTraceLogger)

    from zigpy_znp.utils import TraceLogger

    assert logging.getLoggerClass() is not TraceLogger
    assert logging.getLoggerClass() is MyTraceLogger
