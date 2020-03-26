import pytest
import asyncio
import functools
import async_timeout

from unittest.mock import Mock

try:
    from unittest.mock import AsyncMock  # noqa: F401
except ImportError:
    from asyncmock import AsyncMock  # noqa: F401

import zigpy_znp.commands as c
import zigpy_znp.types as t

from zigpy_znp.api import ZNP
from zigpy_znp.frames import TransportFrame


def pytest_mark_asyncio_timeout(*, seconds=1):
    def decorator(func):
        @pytest.mark.asyncio
        @functools.wraps(func)
        async def replacement(*args, **kwargs):
            async with async_timeout.timeout(seconds):
                return await func(*args, **kwargs)

        return replacement

    return decorator


@pytest.fixture
def znp():
    return ZNP()


@pytest_mark_asyncio_timeout()
async def test_znp_responses(znp):
    assert not znp._response_listeners

    # Can't wait for non-response types
    with pytest.raises(ValueError):
        await znp.wait_for_response(c.SysCommands.Ping.Req())

    assert not znp._response_listeners

    future = znp.wait_for_response(c.SysCommands.Ping.Rsp(partial=True))

    assert znp._response_listeners

    response = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    znp.frame_received(response.to_frame())

    # Our listener should have been cleaned up here
    assert not znp._response_listeners

    assert (await future) == response


@pytest_mark_asyncio_timeout()
async def test_znp_response_matching_partial(znp):
    future = znp.wait_for_response(
        c.SysCommands.ResetInd.Callback(
            partial=True, Reason=t.ResetReason.PowerUp, HwRev=0x04
        )
    )

    response1 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    response2 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x04,
    )
    response3 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.External,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x04,
    )

    znp.frame_received(response1.to_frame())
    znp.frame_received(response2.to_frame())
    znp.frame_received(response3.to_frame())

    assert future.done()
    assert (await future) == response2


@pytest_mark_asyncio_timeout()
async def test_znp_response_matching_exact(znp):
    response1 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    response2 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x04,
    )
    response3 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.External,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x04,
    )

    future = znp.wait_for_response(response2)

    znp.frame_received(response1.to_frame())
    znp.frame_received(response2.to_frame())
    znp.frame_received(response3.to_frame())

    # Future should be immediately resolved
    assert future.done()
    assert (await future) == response2


@pytest_mark_asyncio_timeout()
async def test_znp_response_not_matching_out_of_order(znp):
    response = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    znp.frame_received(response.to_frame())

    future = znp.wait_for_response(response)

    # This future will never resolve because we were not
    # expecting a response and discarded it
    assert not future.done()


@pytest_mark_asyncio_timeout()
async def test_znp_response_callbacks(znp, event_loop):
    sync_callback = Mock()
    bad_sync_callback = Mock(
        side_effect=RuntimeError
    )  # Exceptions should not interfere with other callbacks

    async_callback_responses = []

    # XXX: I can't get AsyncMock().call_count to work, even though
    # the callback is definitely being called
    async def async_callback(response):
        await asyncio.sleep(0, loop=event_loop)
        async_callback_responses.append(response)

    good_command1 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    good_command2 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_APP)
    good_command3 = c.UtilCommands.TimeAlive.Rsp(Seconds=12)
    bad_command1 = c.SysCommands.SetExtAddr.Rsp(Status=t.Status.Success)
    bad_command2 = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    # We shouldn't see any effects from receiving a frame early
    znp.frame_received(good_command1.to_frame())

    for callback in [bad_sync_callback, async_callback, sync_callback]:
        znp.callback_for_responses(
            [
                # Duplicating matching commands shouldn't do anything
                c.SysCommands.Ping.Rsp(partial=True),
                c.SysCommands.Ping.Rsp(partial=True),
                # Matching against different command types should also work
                c.UtilCommands.TimeAlive.Rsp(Seconds=12),
                c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
                c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
                c.UtilCommands.TimeAlive.Rsp(Seconds=10),
            ],
            callback,
        )

    znp.frame_received(good_command1.to_frame())
    znp.frame_received(bad_command1.to_frame())
    znp.frame_received(good_command2.to_frame())
    znp.frame_received(bad_command2.to_frame())
    znp.frame_received(good_command3.to_frame())

    assert sync_callback.call_count == 3
    assert bad_sync_callback.call_count == 3

    await asyncio.sleep(0.1, loop=event_loop)
    # assert async_callback.call_count == 3  # XXX: this always returns zero
    assert len(async_callback_responses) == 3


@pytest_mark_asyncio_timeout()
async def test_znp_wait_for_responses(znp, event_loop):
    command1 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    command2 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_APP)
    command3 = c.UtilCommands.TimeAlive.Rsp(Seconds=12)
    command4 = c.SysCommands.SetExtAddr.Rsp(Status=t.Status.Success)
    command5 = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    # We shouldn't see any effects from receiving a frame early
    znp.frame_received(command1.to_frame())

    future1 = znp.wait_for_responses(
        [c.SysCommands.Ping.Rsp(partial=True), c.SysCommands.Ping.Rsp(partial=True)]
    )

    future2 = znp.wait_for_responses(
        [
            c.UtilCommands.TimeAlive.Rsp(Seconds=12),
            c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_UTIL),
        ]
    )

    future3 = znp.wait_for_responses([c.UtilCommands.TimeAlive.Rsp(Seconds=10)])

    future4 = znp.wait_for_responses(
        [
            # Duplicating matching commands shouldn't do anything
            c.SysCommands.Ping.Rsp(partial=True),
            c.SysCommands.Ping.Rsp(partial=True),
            # Matching against different command types should also work
            c.UtilCommands.TimeAlive.Rsp(Seconds=12),
            c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
            c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
            c.UtilCommands.TimeAlive.Rsp(Seconds=10),
        ]
    )

    znp.frame_received(command1.to_frame())
    znp.frame_received(command2.to_frame())
    znp.frame_received(command3.to_frame())
    znp.frame_received(command4.to_frame())
    znp.frame_received(command5.to_frame())
    znp.frame_received(command1.to_frame())
    znp.frame_received(command2.to_frame())
    znp.frame_received(command3.to_frame())
    znp.frame_received(command4.to_frame())
    znp.frame_received(command5.to_frame())

    assert future1.done()
    assert future2.done()
    assert not future3.done()
    assert future4.done()

    assert (await future1) == command1
    assert (await future2) == command3
    assert (await future4) == command1

    znp.frame_received(c.UtilCommands.TimeAlive.Rsp(Seconds=10).to_frame())
    assert future3.done()
    assert (await future3) == c.UtilCommands.TimeAlive.Rsp(Seconds=10)


@pytest_mark_asyncio_timeout()
async def test_znp_uart(znp, event_loop):
    znp._uart = Mock()

    with pytest.raises(KeyError):
        await znp.command(c.SysCommands.Ping.Req(), foo=0x01)

    ping_rsp = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)

    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())
    response = await znp.command(c.SysCommands.Ping.Req())

    assert ping_rsp == response

    frame, _ = TransportFrame.deserialize(bytes.fromhex("FE   00   21 01   20"))

    znp._uart.send.assert_called_once_with(frame.payload)
