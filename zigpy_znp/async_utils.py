import typing
import asyncio
import logging
import threading

LOGGER = logging.getLogger(__name__)


znp_loop = None
hass_loop = None


def init():
	global znp_loop, hass_loop
    if hass_loop is None:
        hass_loop = asyncio.get_running_loop()

    if znp_loop is None:
        znp_loop = asyncio.new_event_loop()

        def run_znp_loop():
            znp_loop.run_forever()

        znp_thread = threading.Thread(target=run_znp_loop, daemon=True, name="ZigpyThread")
        znp_thread.start()
    future = asyncio.run_coroutine_threadsafe(connect2(config, api), znp_loop)
    return future.result()

if znp_loop is None:
	init()

def run_in_loop(function: typing.CoroutineFunction, loop, wait_for_result:bool=True) -> typing.CoroutineFunction | None:
	@functools.wraps(function)
	async def new_func(*args, **kwargs):
	    future = asyncio.run_coroutine_threadsafe(function(*args, **kwargs), loop)
		return future.result() if wait_for_result else None
	return new_func

def run_in_znp_loop(function: typing.CoroutineFunction, wait_for_result:bool=True) -> typing.CoroutineFunction | None:
	global znp_loop
	return run_in_loop(function, znp_loop, wait_for_result)
	
def run_in_hass_loop(function: typing.CoroutineFunction, wait_for_result:bool=True) -> typing.CoroutineFunction | None:
	global hass_loop
	return run_in_loop(function, hass_loop, wait_for_result)
	
