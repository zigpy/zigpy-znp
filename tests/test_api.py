import pytest
import asyncio
import functools
import async_timeout

from unittest.mock import Mock, call

import zigpy_znp
import zigpy_znp.commands as c
import zigpy_znp.types as t

from zigpy_znp.types import nvids
from zigpy_znp.uart import ZnpMtProtocol

from zigpy_znp.api import (
    ZNP,
    _deduplicate_commands,
    OneShotResponseListener,
    CallbackResponseListener,
)
from zigpy_znp.frames import TransportFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse


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
def znp(mocker):
    api = ZNP()
    transport = mocker.Mock()

    api._uart = ZnpMtProtocol(api)
    api._uart.send = mocker.Mock(wraps=api._uart.send)
    api._uart.connection_made(transport)

    return api


@pytest_mark_asyncio_timeout()
async def test_znp_connect(mocker, event_loop):
    device = "/dev/ttyUSB1"
    transport = mocker.Mock()

    def dummy_create_serial_connection(loop, protocol_factory, url, *args, **kwargs):
        fut = loop.create_future()
        assert url == device

        protocol = protocol_factory()
        protocol.connection_made(transport)

        fut.set_result((transport, protocol))

        return fut

    mocker.patch(
        "serial_asyncio.create_serial_connection", new=dummy_create_serial_connection
    )
    mocker.patch("zigpy_znp.uart.connect", wraps=zigpy_znp.uart.connect)

    api = ZNP()
    connect_fut = event_loop.create_future()
    connect_task = asyncio.create_task(api.connect(device, baudrate=1234_5678))
    connect_task.add_done_callback(lambda _: connect_fut.set_result(None))

    while transport.write.call_count == 0:
        await asyncio.sleep(0.01)  # XXX: not ideal

    transport.write.assert_called_once_with(bytes.fromhex("FE  00  21 01  20"))

    # Send a ping response
    api._uart.data_received(bytes.fromhex("FE  02  61 01  00 01  63"))

    # Wait to connect
    await connect_fut

    assert api._device == device
    assert api._baudrate == 1234_5678


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

    assert (await future) == response

    # Our listener will have been cleaned up after a step
    await asyncio.sleep(0)
    assert not znp._response_listeners


@pytest_mark_asyncio_timeout()
async def test_znp_response_timeouts(znp):
    response = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)

    async def send_soon(delay):
        await asyncio.sleep(delay)
        znp.frame_received(response.to_frame())

    asyncio.create_task(send_soon(0.1))

    async with async_timeout.timeout(0.5):
        assert (
            await znp.wait_for_response(c.SysCommands.Ping.Rsp(partial=True))
        ) == response

    # The response was successfully received so we should have no outstanding listeners
    await asyncio.sleep(0)
    assert not znp._response_listeners

    asyncio.create_task(send_soon(0.6))

    with pytest.raises(asyncio.TimeoutError):
        async with async_timeout.timeout(0.5):
            assert (
                await znp.wait_for_response(c.SysCommands.Ping.Rsp(partial=True))
            ) == response

    # Our future still completed, albeit unsuccesfully.
    # We should have no leaked listeners here.
    await asyncio.sleep(0)
    assert not znp._response_listeners


@pytest_mark_asyncio_timeout()
async def test_znp_response_matching_partial(znp):
    future = znp.wait_for_response(
        c.SysCommands.ResetInd.Callback(
            partial=True, Reason=t.ResetReason.PowerUp, MaintRel=0x04
        )
    )

    response1 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    response2 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
    )
    response3 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.External,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
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
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    response2 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
    )
    response3 = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.External,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
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
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    znp.frame_received(response.to_frame())

    future = znp.wait_for_response(response)

    # This future will never resolve because we were not
    # expecting a response and discarded it
    assert not future.done()


@pytest_mark_asyncio_timeout()
async def test_znp_wait_responses_empty(znp):
    # You shouldn't be able to wait for an empty list of responses
    with pytest.raises(ValueError):
        await znp.wait_for_responses([])


@pytest_mark_asyncio_timeout()
async def test_znp_response_callback_simple(znp, event_loop):
    sync_callback = Mock()

    good_command = c.SysCommands.SetExtAddr.Rsp(Status=t.Status.Failure)
    bad_command = c.SysCommands.SetExtAddr.Rsp(Status=t.Status.Success)

    znp.callback_for_response(good_command, sync_callback)

    znp.frame_received(bad_command.to_frame())
    assert sync_callback.call_count == 0

    znp.frame_received(good_command.to_frame())
    sync_callback.assert_called_once_with(good_command)


def test_command_deduplication():
    result = _deduplicate_commands(
        [
            c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
            # Duplicating matching commands shouldn't do anything
            c.SysCommands.Ping.Rsp(partial=True),
            c.SysCommands.Ping.Rsp(partial=True),
            # Matching against different command types should also work
            c.UtilCommands.TimeAlive.Rsp(Seconds=12),
            c.UtilCommands.TimeAlive.Rsp(Seconds=10),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                partial=True, Status=0x01
            ),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                partial=True, Status=0x01, Mode=0x02
            ),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                partial=True, Status=0x01, Mode=0x02, RemainingModes=0x1
            ),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                partial=True, RemainingModes=0x1
            ),
        ]
    )

    assert set(result) == {
        c.SysCommands.Ping.Rsp(partial=True),
        c.UtilCommands.TimeAlive.Rsp(Seconds=12),
        c.UtilCommands.TimeAlive.Rsp(Seconds=10),
        c.APPConfigCommands.BDBCommissioningNotification.Callback(
            partial=True, Status=0x01
        ),
        c.APPConfigCommands.BDBCommissioningNotification.Callback(
            partial=True, RemainingModes=0x1
        ),
    }


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
        await asyncio.sleep(0)
        async_callback_responses.append(response)

    good_command1 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    good_command2 = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_APP)
    good_command3 = c.UtilCommands.TimeAlive.Rsp(Seconds=12)
    bad_command1 = c.SysCommands.SetExtAddr.Rsp(Status=t.Status.Success)
    bad_command2 = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    responses = [
        # Duplicating matching commands shouldn't do anything
        c.SysCommands.Ping.Rsp(partial=True),
        c.SysCommands.Ping.Rsp(partial=True),
        # Matching against different command types should also work
        c.UtilCommands.TimeAlive.Rsp(Seconds=12),
        c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
        c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS),
        c.UtilCommands.TimeAlive.Rsp(Seconds=10),
    ]

    assert set(_deduplicate_commands(responses)) == {
        c.SysCommands.Ping.Rsp(partial=True),
        c.UtilCommands.TimeAlive.Rsp(Seconds=12),
        c.UtilCommands.TimeAlive.Rsp(Seconds=10),
    }

    # We shouldn't see any effects from receiving a frame early
    znp.frame_received(good_command1.to_frame())

    for callback in [bad_sync_callback, async_callback, sync_callback]:
        znp.callback_for_responses(responses, callback)

    znp.frame_received(good_command1.to_frame())
    znp.frame_received(bad_command1.to_frame())
    znp.frame_received(good_command2.to_frame())
    znp.frame_received(bad_command2.to_frame())
    znp.frame_received(good_command3.to_frame())

    await asyncio.sleep(0)

    assert sync_callback.call_count == 3
    assert bad_sync_callback.call_count == 3

    await asyncio.sleep(0.1)
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
async def test_znp_command_kwargs(znp):
    with pytest.raises(KeyError):
        await znp.command(c.SysCommands.Ping.Req(), foo=0x01)

    # Commands with no response (not an empty response!) can still be sent
    response = await znp.command(c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft))

    znp._uart.send.assert_called_once_with(
        c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft).to_frame()
    )

    assert response is None

    # You cannot send anything but requests
    with pytest.raises(ValueError):
        await znp.command(
            c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
        )

    # You cannot send callbacks
    with pytest.raises(ValueError):
        await znp.command(
            c.SysCommands.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=0x00,
                ProductId=0x12,
                MajorRel=0x01,
                MinorRel=0x02,
                MaintRel=0x03,
            )
        )


@pytest_mark_asyncio_timeout()
async def test_znp_command_not_recognized(znp, event_loop):
    # An error is raise when a bad command is sent
    command = c.SysCommands.Ping.Req()
    unknown_rsp = c.RPCErrorCommands.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=command.header
    )

    with pytest.raises(CommandNotRecognized):
        event_loop.call_soon(znp.frame_received, unknown_rsp.to_frame())
        await znp.command(command)


@pytest_mark_asyncio_timeout()
async def test_znp_command_wrong_params(znp, event_loop):
    # You cannot specify response kwargs for commands with no response
    with pytest.raises(ValueError):
        await znp.command(c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft), foo=0x01)

    # An error is raised when a command with bad params is received
    with pytest.raises(InvalidCommandResponse):
        event_loop.call_soon(
            znp.frame_received,
            c.SysCommands.Ping.Rsp(
                Capabilities=c.types.MTCapabilities.CAP_SYS
            ).to_frame(),
        )
        await znp.command(
            c.SysCommands.Ping.Req(), Capabilities=c.types.MTCapabilities.CAP_APP
        )


@pytest_mark_asyncio_timeout()
async def test_znp_uart(znp, event_loop):

    ping_rsp = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)

    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())
    response = await znp.command(c.SysCommands.Ping.Req())

    assert ping_rsp == response

    frame, _ = TransportFrame.deserialize(bytes.fromhex("FE   00   21 01   20"))

    znp._uart.send.assert_called_once_with(frame.payload)


@pytest_mark_asyncio_timeout()
async def test_znp_sreq_srsp(znp, event_loop):

    # Each SREQ must have a corresponding SRSP, so this will fail
    with pytest.raises(asyncio.TimeoutError):
        with async_timeout.timeout(0.5):
            await znp.command(c.SysCommands.Ping.Req())

    # This will work
    ping_rsp = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())

    await znp.command(c.SysCommands.Ping.Req())


@pytest_mark_asyncio_timeout()
async def test_znp_nvram_writes(znp, event_loop):
    # Passing numerical addresses is disallowed because we can't check for overflows
    with pytest.raises(ValueError):
        await znp.nvram_write(0x0003, t.uint8_t(0xAB))

    # Neither is passing in untyped integers
    with pytest.raises(AttributeError):
        await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, 0xAB)

    # This, however, should work
    assert nvids.NwkNvIds.STARTUP_OPTION == 0x0003

    event_loop.call_soon(
        znp.frame_received,
        c.SysCommands.OSALNVWrite.Rsp(Status=t.Status.Success).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint8_t(0xAB))
    znp._uart.send.assert_called_once_with(
        c.SysCommands.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # As should explicitly serializing the value to bytes
    event_loop.call_soon(
        znp.frame_received,
        c.SysCommands.OSALNVWrite.Rsp(Status=t.Status.Success).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint8_t(0xAB).serialize())
    znp._uart.send.assert_called_once_with(
        c.SysCommands.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # And passing in bytes directly
    event_loop.call_soon(
        znp.frame_received,
        c.SysCommands.OSALNVWrite.Rsp(Status=t.Status.Success).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, b"\xAB")
    znp._uart.send.assert_called_once_with(
        c.SysCommands.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # Writing too big of a value should fail
    with pytest.raises(ValueError):
        await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint16_t(0xAABB))


@pytest_mark_asyncio_timeout()
async def test_listeners_resolve(event_loop):
    callback = Mock()
    callback_listener = CallbackResponseListener(
        [c.SysCommands.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener(
        [c.SysCommands.Ping.Rsp(partial=True)], future
    )

    match = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    no_match = c.SysCommands.OSALNVWrite.Rsp(Status=t.Status.Success)

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
    assert not callback_listener.cancel()

    # Cancelling a one-shot listener does not throw any errors
    assert one_shot_listener.cancel()
    assert one_shot_listener.cancel()
    assert one_shot_listener.cancel()


@pytest_mark_asyncio_timeout()
async def test_listener_cancel(event_loop):
    # Cancelling a one-shot listener prevents it from being fired
    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener(
        [c.SysCommands.Ping.Rsp(partial=True)], future
    )
    one_shot_listener.cancel()

    match = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    assert not one_shot_listener.resolve(match)

    with pytest.raises(asyncio.CancelledError):
        await future


@pytest_mark_asyncio_timeout()
async def test_listeners_cancel(event_loop):
    callback = Mock()
    callback_listener = CallbackResponseListener(
        [c.SysCommands.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener(
        [c.SysCommands.Ping.Rsp(partial=True)], future
    )

    match = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    no_match = c.SysCommands.OSALNVWrite.Rsp(Status=t.Status.Success)

    assert callback_listener.resolve(match)
    assert not callback_listener.resolve(no_match)

    assert one_shot_listener.resolve(match)
    assert not one_shot_listener.resolve(no_match)

    callback.assert_called_once_with(match)
    assert (await future) == match
