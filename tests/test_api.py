import pytest
import logging
import asyncio
import warnings
import functools
import async_timeout

from unittest.mock import Mock, call

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c

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

with warnings.catch_warnings():
    warnings.filterwarnings(
        action="ignore",
        module="serial_asyncio",
        message='"@coroutine" decorator is deprecated',
        category=DeprecationWarning,
    )
    import serial_asyncio


def config_for_port_path(path):
    return conf.CONFIG_SCHEMA({conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: path}})


TEST_APP_CONFIG = config_for_port_path("/dev/ttyWorkingUSB1")


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
    api = ZNP(TEST_APP_CONFIG)
    transport = mocker.Mock()
    transport.close = lambda: api._uart.connection_lost(exc=None)

    api._uart = ZnpMtProtocol(api)
    api._uart.send = mocker.Mock(wraps=api._uart.send)
    api._uart.connection_made(transport)

    return api


@pytest.fixture
def pingable_serial_port(mocker):
    port_name = "/dev/ttyWorkingUSB1"
    old_serial_connect = serial_asyncio.create_serial_connection

    def dummy_serial_close():
        dummy_serial_conn.mock_transport._connected = False

    def dummy_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        # Only our virtual port is handled differently
        if url != port_name:
            return old_serial_connect(loop, protocol_factory, url, *args, **kwargs)

        fut = loop.create_future()
        assert url == port_name

        dummy_serial_conn.protocol = protocol_factory()
        dummy_serial_conn.protocol.connection_made(dummy_serial_conn.mock_transport)

        fut.set_result((dummy_serial_conn.mock_transport, dummy_serial_conn.protocol))

        assert not dummy_serial_conn.mock_transport._connected
        dummy_serial_conn.mock_transport._connected = True

        return fut

    def ping_responder(data):
        # XXX: this assumes that our UART will send packets perfectly framed
        if data == bytes.fromhex("FE  00  21 01  20"):
            # Ping
            dummy_serial_conn.protocol.data_received(b"\xFE\x02\x61\x01\x59\x06\x3D")

    dummy_serial_conn.mock_transport = mocker.Mock()
    dummy_serial_conn.mock_transport._connected = False
    dummy_serial_conn.mock_transport.write = mocker.Mock(side_effect=ping_responder)
    dummy_serial_conn.mock_transport.close = mocker.Mock(side_effect=dummy_serial_close)

    mocker.patch("serial_asyncio.create_serial_connection", new=dummy_serial_conn)

    return port_name


@pytest_mark_asyncio_timeout()
async def test_znp_connect(mocker, event_loop, pingable_serial_port):
    api = ZNP(TEST_APP_CONFIG)
    await api.connect()


@pytest_mark_asyncio_timeout()
async def test_znp_connect_without_test(mocker, event_loop, pingable_serial_port):
    api = ZNP(TEST_APP_CONFIG)
    api.request = mocker.Mock(wraps=api.request)

    await api.connect(test_port=False)

    # Nothing should have been sent
    assert api.request.call_count == 0


@pytest_mark_asyncio_timeout()
@pytest.mark.parametrize("check_version", [True, False])
async def test_znp_connect_old_version(
    check_version, caplog, mocker, event_loop, pingable_serial_port
):
    old_write = serial_asyncio.create_serial_connection.mock_transport.write

    def ping_responder(data):
        # XXX: this assumes that our UART will send packets perfectly framed
        if data == bytes.fromhex("FE  00  21 01  20"):
            # Ping response from the CC2531 running old Z-Stack
            serial_asyncio.create_serial_connection.protocol.data_received(
                b"\xFE\x02\x61\x01\x79\x01\x1A"
            )
        else:
            old_write(data)

    mocker.patch(
        "serial_asyncio.create_serial_connection.mock_transport.write",
        new=ping_responder,
    )

    api = ZNP(TEST_APP_CONFIG)

    if check_version:
        with pytest.raises(RuntimeError):
            await api.connect(check_version=True)
    else:
        with caplog.at_level(logging.WARNING):
            await api.connect(check_version=False)

        assert "old version" in caplog.text


@pytest_mark_asyncio_timeout()
async def test_znp_responses(znp):
    assert not znp._listeners

    future = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))

    assert znp._listeners

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    znp.frame_received(response.to_frame())

    assert (await future) == response

    # Our listener will have been cleaned up after a step
    await asyncio.sleep(0)
    assert not znp._listeners


@pytest_mark_asyncio_timeout()
async def test_znp_responses_iterator(znp):
    responses = [
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_MAC),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_NWK),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_AF),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_ZDO),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_APP),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_GP),
    ]

    async def sender():
        await asyncio.sleep(0.1)

        for response in responses:
            znp.frame_received(response.to_frame())

    # We can't use `zip` for this
    count = 0
    responses_iter = iter(responses)
    assert not znp._listeners

    # Send them in the background
    asyncio.create_task(sender())

    async for frame in znp.iterator_for_responses([c.SYS.Ping.Rsp(partial=True)]):
        assert frame == next(responses_iter)
        count += 1

        if count == len(responses):
            break

    # Once we stop iterating, the callback should be cleaned up eventually
    await asyncio.sleep(0.1)
    assert not znp._listeners


@pytest_mark_asyncio_timeout()
async def test_znp_responses_multiple(znp):
    assert not znp._listeners

    future1 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
    future2 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
    future3 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    znp.frame_received(response.to_frame())

    await future1
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not future2.done()
    assert not future3.done()

    assert znp._listeners


@pytest_mark_asyncio_timeout()
async def test_znp_response_timeouts(znp):
    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)

    async def send_soon(delay):
        await asyncio.sleep(delay)
        znp.frame_received(response.to_frame())

    asyncio.create_task(send_soon(0.1))

    async with async_timeout.timeout(0.5):
        assert (await znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))) == response

    # The response was successfully received so we should have no outstanding listeners
    await asyncio.sleep(0)
    assert not znp._listeners

    asyncio.create_task(send_soon(0.6))

    with pytest.raises(asyncio.TimeoutError):
        async with async_timeout.timeout(0.5):
            assert (
                await znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
            ) == response

    # Our future still completed, albeit unsuccesfully.
    # We should have no leaked listeners here.
    await asyncio.sleep(0)
    assert not znp._listeners


@pytest_mark_asyncio_timeout()
async def test_znp_response_matching_partial(znp):
    future = znp.wait_for_response(
        c.SYS.ResetInd.Callback(
            partial=True, Reason=t.ResetReason.PowerUp, MaintRel=0x04
        )
    )

    response1 = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    response2 = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
    )
    response3 = c.SYS.ResetInd.Callback(
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
    response1 = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    response2 = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x12,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x04,
    )
    response3 = c.SYS.ResetInd.Callback(
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
    response = c.SYS.ResetInd.Callback(
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

    good_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.FAILURE)
    bad_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)

    znp.callback_for_response(good_response, sync_callback)

    znp.frame_received(bad_response.to_frame())
    assert sync_callback.call_count == 0

    znp.frame_received(good_response.to_frame())
    sync_callback.assert_called_once_with(good_response)


def test_command_deduplication_simple():
    c1 = c.SYS.Ping.Rsp(partial=True)
    c2 = c.Util.TimeAlive.Rsp(Seconds=12)

    assert _deduplicate_commands([]) == ()
    assert _deduplicate_commands([c1]) == (c1,)
    assert _deduplicate_commands([c1, c1]) == (c1,)
    assert _deduplicate_commands([c1, c2]) == (c1, c2)
    assert _deduplicate_commands([c2, c1, c2]) == (c2, c1)


def test_command_deduplication_complex():
    result = _deduplicate_commands(
        [
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
            # Duplicating matching commands shouldn't do anything
            c.SYS.Ping.Rsp(partial=True),
            c.SYS.Ping.Rsp(partial=True),
            # Matching against different command types should also work
            c.Util.TimeAlive.Rsp(Seconds=12),
            c.Util.TimeAlive.Rsp(Seconds=10),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True, Status=c.app_config.BDBCommissioningStatus.InProgress
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                Status=c.app_config.BDBCommissioningStatus.InProgress,
                Mode=c.app_config.BDBCommissioningMode.NwkFormation,
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                Status=c.app_config.BDBCommissioningStatus.InProgress,
                Mode=c.app_config.BDBCommissioningMode.NwkFormation,
                RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
            ),
        ]
    )

    assert set(result) == {
        c.SYS.Ping.Rsp(partial=True),
        c.Util.TimeAlive.Rsp(Seconds=12),
        c.Util.TimeAlive.Rsp(Seconds=10),
        c.AppConfig.BDBCommissioningNotification.Callback(
            partial=True, Status=c.app_config.BDBCommissioningStatus.InProgress
        ),
        c.AppConfig.BDBCommissioningNotification.Callback(
            partial=True,
            RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
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

    good_response1 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    good_response2 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_APP)
    good_response3 = c.Util.TimeAlive.Rsp(Seconds=12)
    bad_response1 = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)
    bad_response2 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    responses = [
        # Duplicating matching responses shouldn't do anything
        c.SYS.Ping.Rsp(partial=True),
        c.SYS.Ping.Rsp(partial=True),
        # Matching against different response types should also work
        c.Util.TimeAlive.Rsp(Seconds=12),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
        c.Util.TimeAlive.Rsp(Seconds=10),
    ]

    assert set(_deduplicate_commands(responses)) == {
        c.SYS.Ping.Rsp(partial=True),
        c.Util.TimeAlive.Rsp(Seconds=12),
        c.Util.TimeAlive.Rsp(Seconds=10),
    }

    # We shouldn't see any effects from receiving a frame early
    znp.frame_received(good_response1.to_frame())

    for callback in [bad_sync_callback, async_callback, sync_callback]:
        znp.callback_for_responses(responses, callback)

    znp.frame_received(good_response1.to_frame())
    znp.frame_received(bad_response1.to_frame())
    znp.frame_received(good_response2.to_frame())
    znp.frame_received(bad_response2.to_frame())
    znp.frame_received(good_response3.to_frame())

    await asyncio.sleep(0)

    assert sync_callback.call_count == 3
    assert bad_sync_callback.call_count == 3

    await asyncio.sleep(0.1)
    # assert async_callback.call_count == 3  # XXX: this always returns zero
    assert len(async_callback_responses) == 3


@pytest_mark_asyncio_timeout()
async def test_znp_wait_for_responses(znp, event_loop):
    response1 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    response2 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_APP)
    response3 = c.Util.TimeAlive.Rsp(Seconds=12)
    response4 = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)
    response5 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    # We shouldn't see any effects from receiving a frame early
    znp.frame_received(response1.to_frame())

    # Will match the first response1 and detach
    future1 = znp.wait_for_responses(
        [c.SYS.Ping.Rsp(partial=True), c.SYS.Ping.Rsp(partial=True)]
    )

    # Will match the first response3 and detach
    future2 = znp.wait_for_responses(
        [
            c.Util.TimeAlive.Rsp(Seconds=12),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_UTIL),
        ]
    )

    # Will not match anything
    future3 = znp.wait_for_responses([c.Util.TimeAlive.Rsp(Seconds=10)])

    # Will match response1 the second time around
    future4 = znp.wait_for_responses(
        [
            # Matching against different response types should also work
            c.Util.TimeAlive.Rsp(Seconds=12),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
            c.Util.TimeAlive.Rsp(Seconds=10),
        ]
    )

    znp.frame_received(response1.to_frame())
    znp.frame_received(response2.to_frame())
    znp.frame_received(response3.to_frame())
    znp.frame_received(response4.to_frame())
    znp.frame_received(response5.to_frame())

    assert future1.done()
    assert future2.done()
    assert not future3.done()
    assert not future4.done()

    await asyncio.sleep(0)

    znp.frame_received(response1.to_frame())
    znp.frame_received(response2.to_frame())
    znp.frame_received(response3.to_frame())
    znp.frame_received(response4.to_frame())
    znp.frame_received(response5.to_frame())

    assert future1.done()
    assert future2.done()
    assert not future3.done()
    assert future4.done()

    assert (await future1) == response1
    assert (await future2) == response3
    assert (await future4) == response1

    await asyncio.sleep(0)

    znp.frame_received(c.Util.TimeAlive.Rsp(Seconds=10).to_frame())
    assert future3.done()
    assert (await future3) == c.Util.TimeAlive.Rsp(Seconds=10)


@pytest_mark_asyncio_timeout()
async def test_znp_request_kwargs(znp, event_loop):
    # Invalid format
    with pytest.raises(KeyError):
        await znp.request(c.SYS.Ping.Req(), foo=0x01)

    # Valid format, invalid name
    with pytest.raises(KeyError):
        await znp.request(c.SYS.Ping.Req(), RspFoo=0x01)

    # Valid format, valid name
    event_loop.call_soon(
        znp.frame_received,
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS).to_frame(),
    )
    await znp.request(c.SYS.Ping.Req(), RspCapabilities=t.MTCapabilities.CAP_SYS)
    znp._uart.send.reset_mock()

    # Commands with no response (not an empty response!) can still be sent
    response = await znp.request(c.SYS.ResetReq.Req(Type=t.ResetType.Soft))

    znp._uart.send.assert_called_once_with(
        c.SYS.ResetReq.Req(Type=t.ResetType.Soft).to_frame()
    )

    assert response is None

    # You cannot send anything but requests
    with pytest.raises(ValueError):
        await znp.request(c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS))

    # You cannot send callbacks
    with pytest.raises(ValueError):
        await znp.request(
            c.SYS.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=0x00,
                ProductId=0x12,
                MajorRel=0x01,
                MinorRel=0x02,
                MaintRel=0x03,
            )
        )


@pytest_mark_asyncio_timeout()
async def test_znp_request_not_recognized(znp, event_loop):
    # An error is raise when a bad request is sent
    request = c.SYS.Ping.Req()
    unknown_rsp = c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=request.header
    )

    with pytest.raises(CommandNotRecognized):
        event_loop.call_soon(znp.frame_received, unknown_rsp.to_frame())
        await znp.request(request)


@pytest_mark_asyncio_timeout()
async def test_znp_request_wrong_params(znp, event_loop):
    # You cannot specify response kwargs for responses with no response
    with pytest.raises(ValueError):
        await znp.request(c.SYS.ResetReq.Req(Type=t.ResetType.Soft), foo=0x01)

    # An error is raised when a response with bad params is received
    with pytest.raises(InvalidCommandResponse):
        event_loop.call_soon(
            znp.frame_received,
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS).to_frame(),
        )
        await znp.request(c.SYS.Ping.Req(), RspCapabilities=t.MTCapabilities.CAP_APP)


@pytest_mark_asyncio_timeout()
async def test_znp_uart(znp, event_loop):
    ping_rsp = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)

    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())
    response = await znp.request(c.SYS.Ping.Req())

    assert ping_rsp == response

    frame, _ = TransportFrame.deserialize(bytes.fromhex("FE   00   21 01   20"))

    znp._uart.send.assert_called_once_with(frame.payload)


@pytest_mark_asyncio_timeout()
async def test_znp_sreq_srsp(znp, event_loop):

    # Each SREQ must have a corresponding SRSP, so this will fail
    with pytest.raises(asyncio.TimeoutError):
        with async_timeout.timeout(0.5):
            await znp.request(c.SYS.Ping.Req())

    # This will work
    ping_rsp = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())

    await znp.request(c.SYS.Ping.Req())


@pytest_mark_asyncio_timeout()
async def test_znp_nvram_wrong_order(znp, event_loop):
    class TestNvIds(nvids.BaseNvIds):
        SECOND = 0x0002
        FIRST = 0x0001
        LAST = 0x0004
        THIRD = 0x0003

    # Writing too big of a value should fail, regardless of the definition order
    with pytest.raises(ValueError):
        await znp.nvram_write(TestNvIds.THIRD, t.uint16_t(0xAABB))


@pytest_mark_asyncio_timeout()
async def test_znp_nvram_writes(znp, event_loop):
    # Passing numerical addresses is disallowed because we can't check for overflows
    with pytest.raises(ValueError):
        await znp.nvram_write(0x0003, t.uint8_t(0xAB))

    # Neither is passing in untyped integers
    with pytest.raises(TypeError):
        await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, 0xAB)

    # This, however, should work
    assert nvids.NwkNvIds.STARTUP_OPTION == 0x0003

    event_loop.call_soon(
        znp.frame_received, c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint8_t(0xAB))
    znp._uart.send.assert_called_once_with(
        c.SYS.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # As should explicitly serializing the value to bytes
    event_loop.call_soon(
        znp.frame_received, c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint8_t(0xAB).serialize())
    znp._uart.send.assert_called_once_with(
        c.SYS.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # And passing in bytes directly
    event_loop.call_soon(
        znp.frame_received, c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS).to_frame(),
    )
    await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, b"\xAB")
    znp._uart.send.assert_called_once_with(
        c.SYS.OSALNVWrite.Req(
            Id=nvids.NwkNvIds.STARTUP_OPTION, Offset=0x00, Value=t.ShortBytes(b"\xAB")
        ).to_frame()
    )

    znp._uart.send.reset_mock()

    # The SYS_OSAL_NV_WRITE response status should be checked
    event_loop.call_soon(
        znp.frame_received, c.SYS.OSALNVWrite.Rsp(Status=t.Status.FAILURE).to_frame(),
    )

    with pytest.raises(InvalidCommandResponse):
        await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, t.uint8_t(0xAB))


@pytest_mark_asyncio_timeout()
async def test_znp_nvram_read_success(znp, event_loop):
    event_loop.call_soon(
        znp.frame_received,
        c.SYS.OSALNVRead.Rsp(Status=t.Status.SUCCESS, Value=b"test",).to_frame(),
    )
    result = await znp.nvram_read(nvids.NwkNvIds.STARTUP_OPTION)

    assert result == b"test"


@pytest_mark_asyncio_timeout()
async def test_znp_nvram_read_failure(znp, event_loop):
    event_loop.call_soon(
        znp.frame_received,
        c.SYS.OSALNVRead.Rsp(Status=t.Status.FAILURE, Value=b"test",).to_frame(),
    )

    with pytest.raises(InvalidCommandResponse):
        await znp.nvram_read(nvids.NwkNvIds.STARTUP_OPTION)


@pytest_mark_asyncio_timeout()
async def test_listeners_resolve(event_loop):
    callback = Mock()
    callback_listener = CallbackResponseListener(
        [c.SYS.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
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
    assert not callback_listener.cancel()

    # Cancelling a one-shot listener does not throw any errors
    assert one_shot_listener.cancel()
    assert one_shot_listener.cancel()
    assert one_shot_listener.cancel()


@pytest_mark_asyncio_timeout()
async def test_listener_cancel(event_loop):
    # Cancelling a one-shot listener prevents it from being fired
    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)
    one_shot_listener.cancel()

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    assert not one_shot_listener.resolve(match)

    with pytest.raises(asyncio.CancelledError):
        await future


@pytest_mark_asyncio_timeout()
async def test_listeners_cancel(event_loop):
    callback = Mock()
    callback_listener = CallbackResponseListener(
        [c.SYS.Ping.Rsp(partial=True)], callback
    )

    future = event_loop.create_future()
    one_shot_listener = OneShotResponseListener([c.SYS.Ping.Rsp(partial=True)], future)

    match = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    no_match = c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)

    assert callback_listener.resolve(match)
    assert not callback_listener.resolve(no_match)

    assert one_shot_listener.resolve(match)
    assert not one_shot_listener.resolve(no_match)

    callback.assert_called_once_with(match)
    assert (await future) == match


@pytest_mark_asyncio_timeout()
async def test_api_cancel_listeners(znp, event_loop):
    callback = Mock()

    znp.callback_for_response(
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS), callback
    )
    future = znp.wait_for_responses(
        [
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS),
            c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS),
        ]
    )

    assert not future.done()
    znp.close()

    with pytest.raises(asyncio.CancelledError):
        await future

    # add_done_callback won't be executed immediately
    await asyncio.sleep(0.1)

    assert len(znp._listeners) == 0


async def wait_for_spy(spy):
    while True:
        if spy.called:
            return

        await asyncio.sleep(0.01)


@pytest_mark_asyncio_timeout()
async def test_api_close(znp, event_loop, mocker):
    mocker.spy(znp, "connection_lost")
    znp.close()

    await wait_for_spy(znp.connection_lost)

    # connection_lost with no exc indicates the port was closed
    znp.connection_lost.assert_called_once_with(None)

    # Make sure our UART was actually closed
    assert znp._uart is None
    assert znp._app is None

    # ZNP.close should not throw any errors if called multiple times
    znp.close()
    znp.close()

    def dict_minus(d, minus):
        return {k: v for k, v in d.items() if k not in minus}

    # Closing ZNP should reset it completely to that of a fresh object
    # We have to ignore our mocked method and the lock
    znp2 = ZNP(TEST_APP_CONFIG)
    assert znp2._sync_request_lock.locked() == znp._sync_request_lock.locked()
    assert dict_minus(
        znp.__dict__, ["_sync_request_lock", "connection_lost"]
    ) == dict_minus(znp2.__dict__, ["_sync_request_lock", "connection_lost"])

    znp2.close()
    znp2.close()

    assert dict_minus(
        znp.__dict__, ["_sync_request_lock", "connection_lost"]
    ) == dict_minus(znp2.__dict__, ["_sync_request_lock", "connection_lost"])


@pytest_mark_asyncio_timeout()
async def test_request_callback_rsp(pingable_serial_port, event_loop):
    api = ZNP(TEST_APP_CONFIG)
    await api.connect()

    def send_responses():
        api._uart.data_received(
            TransportFrame(
                c.AF.DataRequest.Rsp(Status=t.Status.SUCCESS).to_frame()
            ).serialize()
            + TransportFrame(
                c.AF.DataConfirm.Callback(
                    Endpoint=56, TSN=1, Status=t.Status.SUCCESS
                ).to_frame()
            ).serialize()
        )

    event_loop.call_later(0.1, send_responses)

    # The UART sometimes replies with a SRSP and an AREQ faster than
    # we can register callbacks for both. This method is a workaround.
    response = await api.request_callback_rsp(
        request=c.AF.DataRequest.Req(
            DstAddr=0x1234,
            DstEndpoint=56,
            SrcEndpoint=78,
            ClusterId=90,
            TSN=1,
            Options=c.af.TransmitOptions.RouteDiscovery,
            Radius=30,
            Data=b"hello",
        ),
        RspStatus=t.Status.SUCCESS,
        callback=c.AF.DataConfirm.Callback(partial=True, Endpoint=56, TSN=1),
    )

    # Our response is the callback, not the confirmation response
    assert response == c.AF.DataConfirm.Callback(
        Endpoint=56, TSN=1, Status=t.Status.SUCCESS
    )


@pytest_mark_asyncio_timeout()
async def test_request_callback_rsp_timeouts(pingable_serial_port, event_loop):
    config = conf.CONFIG_SCHEMA(TEST_APP_CONFIG)
    config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT] = 0.1
    config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 0.1

    api = ZNP(config)
    await api.connect()

    # Missing callbacks should not lock anything up
    with pytest.raises(asyncio.TimeoutError):
        await api.request_callback_rsp(
            request=c.SYS.Ping.Req(), callback=c.SYS.ResetInd.Callback(partial=True),
        )

    # But they should still work normally
    rsp = api.request_callback_rsp(
        request=c.SYS.Ping.Req(), callback=c.SYS.ResetInd.Callback(partial=True),
    )

    async def responder():
        api.frame_received(
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS).to_frame()
        )
        api.frame_received(
            c.SYS.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=0x00,
                ProductId=0x12,
                MajorRel=0x01,
                MinorRel=0x02,
                MaintRel=0x03,
            ).to_frame()
        )

    asyncio.create_task(responder())
    await rsp
