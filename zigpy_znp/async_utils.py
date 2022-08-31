import asyncio
import logging
import functools
import threading

LOGGER = logging.getLogger(__name__)


_znp_loop = None  # the loop in which the serial communication will be handled
_worker_loop = (
    None  # the loop in which the frames are handled (MainThread in home assistant)
)

# if there is a need to create a worker loop this will be the thread it is running in
_worker_loop_thread = None


def try_get_running_loop_as_worker_loop():
    """
    this function will set the worker loop to the currently running loop
    (if there is one).
    """
    global _worker_loop
    if _worker_loop is None:
        try:
            _worker_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass


# this will get the running loop in case of integration in home assistant
# if there is no running loop, a loop will be created later
try_get_running_loop_as_worker_loop()


def get_worker_loop():
    """
    Getter for the worker loop.
    """
    global _worker_loop
    if _worker_loop is None:
        try:
            _worker_loop = asyncio.get_running_loop()
            LOGGER.info("used asyncio's running loop")
        except RuntimeError:
            create_new_worker_loop(True)
    return _worker_loop


def get_znp_loop():
    """
    Getter for the ZNP serial loop.
    """
    return _znp_loop


def start_worker_loop_in_thread():
    """
    Create a thread and run the worker loop.
    """
    global _worker_loop_thread, _worker_loop
    if _worker_loop_thread is None and _worker_loop is not None:

        def run_worker_loop():
            asyncio.set_event_loop(_worker_loop)
            _worker_loop.run_forever()

        _worker_loop_thread = threading.Thread(
            target=run_worker_loop, daemon=True, name="ZigpyWorkerThread"
        )
        _worker_loop_thread.start()


def create_new_worker_loop(start_thread: bool = True):
    """
    Creates a new worker loop, starts a new thread too, if start_thread is True.
    """
    global _worker_loop
    LOGGER.info("creating new event loop as worker loop")
    _worker_loop = asyncio.new_event_loop()
    if start_thread:
        start_worker_loop_in_thread()


def init_znp_loop():
    """
    Create and run ZNP loop.
    """
    global _znp_loop
    if _znp_loop is None:
        _znp_loop = asyncio.new_event_loop()

        def run_znp_loop():
            # asyncio.set_event_loop(_znp_loop)
            _znp_loop.run_forever()

        znp_thread = threading.Thread(
            target=run_znp_loop, daemon=True, name="ZigpySerialThread"
        )
        znp_thread.start()


# will create and start a new ZNP loop on module initialization
if _znp_loop is None:
    init_znp_loop()


def run_in_loop(
    function, loop=None, loop_getter=None, wait_for_result: bool = True, *args, **kwargs
):
    """
    Can be used as decorator or as normal function.
    Will run the function in the specified loop.
    @param function:
    The co-routine that shall be run (function call only)
    @param loop:
    Loop in which the co-routine shall run (either loop or loop_getter must be set)
    @param loop_getter:
    Getter for the loop in which the co-routine shall run
    (either loop or loop_getter must be set)
    @param wait_for_result:
    Will "fire and forget" if false. Otherwise,
    the return value of the coro is returned.
    @param args: args
    @param kwargs: kwargs
    @return:
    None if wait_for_result is false. Otherwise, the return value of the co-routine.
    """
    if loop is None and loop_getter is None:
        raise RuntimeError("either loop or loop_getter must be passed to run_in_loop")

    if asyncio.iscoroutine(function):
        # called as a function call
        _loop = loop if loop is not None else loop_getter()
        future = asyncio.run_coroutine_threadsafe(function, _loop)
        return future.result() if wait_for_result else None
    else:
        # probably a decorator

        # wrap the function in a new function,
        # that will run the co-routine in the loop provided
        @functools.wraps(function)
        def new_sync(*args, **kwargs):
            loop if loop is not None else loop_getter()
            return run_in_loop(
                function(*args, **kwargs),
                loop=loop,
                loop_getter=loop_getter,
                wait_for_result=wait_for_result,
            )

        if not asyncio.iscoroutinefunction(function):
            return new_sync
        else:
            # wrap the function again in an async function, so that it can be awaited
            async def new_async(*args, **kwargs):
                return new_sync(*args, **kwargs)

            return new_async


def run_in_znp_loop(*args, **kwargs):
    """
    Can be used as decorator or as normal function.
    Will run the function in the znp loop.
    @param function:
    The co-routine that shall be run (function call only)
    @param wait_for_result:
    Will "fire and forget" if false.
    Otherwise, the return value of the coro is returned.
    @param args: args
    @param kwargs: kwargs
    @return:
    None if wait_for_result is false.
    Otherwise, the return value of the co-routine.
    """
    kwargs["loop_getter"] = get_znp_loop
    return run_in_loop(*args, **kwargs)


def run_in_worker_loop(*args, **kwargs):
    """
    Can be used as decorator or as normal function.
    Will run the function in the worker loop.
    @param function:
    The co-routine that shall be run (function call only)
    @param wait_for_result:
    Will "fire and forget" if false.
    Otherwise, the return value of the coro is returned.
    @param args: args
    @param kwargs: kwargs
    @return:
    None if wait_for_result is false.
    Otherwise, the return value of the co-routine.
    """
    kwargs["loop_getter"] = get_worker_loop
    return run_in_loop(*args, **kwargs)
