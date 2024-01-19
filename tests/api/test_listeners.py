import asyncio
from unittest.mock import call

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import OneShotResponseListener, CallbackResponseListener
from zigpy_znp.exceptions import ShuttingDown


async def test_resolve(event_loop, mocker):
    callback = mocker.Mock()
    callback_listener = CallbackResponseListener(
        [c.SYS.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    no_match = c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)

    assert callback_listener.resolve(match)
    assert not callback_listener.resolve(no_match)
    assert callback_listener.resolve(match)
    assert not callback_listener.resolve(no_match)

    assert one_shot_listener.resolve(match)
    assert not one_shot_listener.resolve(no_match)

    callback.assert_has_calls([call(match), call(match)])
    assert callback.call_count == 2

    assert (await future) == match

    # Cancelling a callback will have no effect
    callback_listener.set_exception(RuntimeError())

    # Cancelling a one-shot listener does not throw any errors
    one_shot_listener.set_exception(RuntimeError())
    one_shot_listener.set_exception(RuntimeError())
    one_shot_listener.set_exception(RuntimeError())


async def test_cancel(event_loop):
    # Cancelling a one-shot listener prevents it from being fired
    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)
    one_shot_listener.set_exception(RuntimeError())

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    assert not one_shot_listener.resolve(match)

    with pytest.raises(RuntimeError):
        await future


async def test_multi_cancel(event_loop, mocker):
    callback = mocker.Mock()
    callback_listener = CallbackResponseListener(
        [c.SYS.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    no_match = c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)

    assert callback_listener.resolve(match)
    assert not callback_listener.resolve(no_match)

    assert one_shot_listener.resolve(match)
    assert not one_shot_listener.resolve(no_match)

    callback.assert_called_once_with(match)
    assert (await future) == match


async def test_api_cancel_listeners(connected_znp, mocker):
    znp, znp_server = connected_znp

    callback = mocker.Mock()

    znp.callback_for_response(
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS), callback
    )
    future = znp.wait_for_responses(
        [
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
            c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS),
        ]
    )

    assert not future.done()
    znp.close()

    with pytest.raises(ShuttingDown):
        await future

    # add_done_callback won't be executed immediately
    await asyncio.sleep(0.1)

    assert len(znp._listeners) == 0
