import asyncio
import logging
import functools
import threading

LOGGER = logging.getLogger(__name__)


_znp_loop = None
_worker_loop = None

_worker_loop_thread = None


def try_get_running_loop_as_worker_loop():
    global _worker_loop
    if _worker_loop is None:
        try:
            _worker_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass


try_get_running_loop_as_worker_loop()


def get_worker_loop():
    global _worker_loop
    if _worker_loop is None:
        try:
            _worker_loop = asyncio.get_running_loop()
            LOGGER.info("used asyncio's running loop")
        except RuntimeError:
            create_new_worker_loop(True)
    return _worker_loop


def get_znp_loop():
    return _znp_loop


def start_worker_loop_in_thread():
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
    global _worker_loop
    LOGGER.info("creating new event loop as worker loop")
    _worker_loop = asyncio.new_event_loop()
    if start_thread:
        start_worker_loop_in_thread()


def init_znp_loop():
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


if _znp_loop is None:
    init_znp_loop()


def delegate_to_worker_thread(coro, wait: bool = True):
    future = asyncio.run_coroutine_threadsafe(coro, get_worker_loop())
    return future.result() if wait else None


def run_in_loop(
    function, loop=None, loop_getter=None, wait_for_result: bool = True, *args, **kwargs
):
    if loop is None and loop_getter is None:
        raise RuntimeError("either loop or loop_getter must be passed to run_in_loop")

    if asyncio.iscoroutine(function):
        # called as a function call
        _loop = loop if loop is not None else loop_getter()
        future = asyncio.run_coroutine_threadsafe(function, _loop)
        return future.result() if wait_for_result else None
    else:
        # probably a decorator

        @functools.wraps(function)
        def new_sync(*args, **kwargs):
            loop if loop is not None else loop_getter()
            return run_in_loop(
                function(*args, **kwargs),
                loop=loop,
                loop_getter=loop_getter,
                wait_for_result=wait_for_result,
            )

        async def new_async(*args, **kwargs):
            return new_sync(*args, **kwargs)

        if asyncio.iscoroutinefunction(function):
            return new_async
        else:
            return new_sync


def run_in_znp_loop(*args, **kwargs):
    kwargs["loop_getter"] = get_znp_loop
    return run_in_loop(*args, **kwargs)


def run_in_worker_loop(*args, **kwargs):
    kwargs["loop_getter"] = get_worker_loop
    return run_in_loop(*args, **kwargs)
