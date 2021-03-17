import asyncio
import logging

import pytest
import async_timeout

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse

pytestmark = [pytest.mark.asyncio]


async def test_callback_rsp(connected_znp, event_loop):
    znp, znp_server = connected_znp

    def send_responses():
        znp_server.send(c.AF.DataRequest.Rsp(Status=t.Status.SUCCESS))
        znp_server.send(
            c.AF.DataConfirm.Callback(Endpoint=56, TSN=1, Status=t.Status.SUCCESS)
        )

    event_loop.call_soon(send_responses)

    # The UART sometimes replies with a SRSP and an AREQ faster than
    # we can register callbacks for both. This method is a workaround.
    response = await znp.request_callback_rsp(
        request=c.AF.DataRequest.Req(
            DstAddr=0x1234,
            DstEndpoint=56,
            SrcEndpoint=78,
            ClusterId=90,
            TSN=1,
            Options=c.af.TransmitOptions.SUPPRESS_ROUTE_DISC_NETWORK,
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


async def test_cleanup_timeout_internal(connected_znp):
    znp, znp_server = connected_znp
    znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT] = 0.1
    znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 0.1

    assert not znp._listeners

    with pytest.raises(asyncio.TimeoutError):
        await znp.request(c.Util.TimeAlive.Req())

    # We should be cleaned up
    assert not znp._listeners


async def test_cleanup_timeout_external(connected_znp):
    znp, znp_server = connected_znp

    assert not znp._listeners

    # This request will timeout because we didn't send anything back
    with pytest.raises(asyncio.TimeoutError):
        async with async_timeout.timeout(0.1):
            await znp.request(c.Util.TimeAlive.Req())

    # We should be cleaned up
    assert not znp._listeners


async def test_callback_rsp_cleanup_timeout_external(connected_znp):
    znp, znp_server = connected_znp

    assert not znp._listeners

    # This request will timeout because we didn't send anything back
    with pytest.raises(asyncio.TimeoutError):
        async with async_timeout.timeout(0.1):
            await znp.request_callback_rsp(
                request=c.Util.TimeAlive.Req(),
                callback=c.SYS.ResetInd.Callback(partial=True),
            )

    # We should be cleaned up
    assert not znp._listeners


async def test_callback_rsp_cleanup_timeout_internal(connected_znp):
    znp, znp_server = connected_znp
    znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT] = 0.1
    znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 0.1

    assert not znp._listeners

    # This request will timeout because we didn't send anything back
    with pytest.raises(asyncio.TimeoutError):
        await znp.request_callback_rsp(
            request=c.Util.TimeAlive.Req(),
            callback=c.SYS.ResetInd.Callback(partial=True),
        )

    # We should be cleaned up
    assert not znp._listeners


async def test_callback_rsp_cleanup_concurrent(connected_znp, event_loop, mocker):
    znp, znp_server = connected_znp

    mocker.spy(znp, "_unhandled_command")

    assert not znp._listeners

    def send_responses():
        znp_server.send(c.Util.TimeAlive.Rsp(Seconds=123))
        znp_server.send(c.Util.TimeAlive.Rsp(Seconds=456))
        znp_server.send(c.SYS.OSALTimerExpired.Callback(Id=0xAB))
        znp_server.send(c.SYS.OSALTimerExpired.Callback(Id=0xCD))

    event_loop.call_soon(send_responses)

    callback_rsp = await znp.request_callback_rsp(
        request=c.Util.TimeAlive.Req(),
        callback=c.SYS.OSALTimerExpired.Callback(partial=True),
    )

    # We should be cleaned up
    assert not znp._listeners

    assert callback_rsp == c.SYS.OSALTimerExpired.Callback(Id=0xAB)

    # Even though all four requests were sent in the same tick, they should be handled
    # correctly by request_callback_rsp and in the correct order
    assert znp._unhandled_command.mock_calls == [
        mocker.call(c.Util.TimeAlive.Rsp(Seconds=456)),
        mocker.call(c.SYS.OSALTimerExpired.Callback(Id=0xCD)),
    ]


async def test_znp_request_kwargs(connected_znp, event_loop):
    znp, znp_server = connected_znp

    # Invalid format
    with pytest.raises(KeyError):
        await znp.request(c.SYS.Ping.Req(), foo=0x01)

    # Valid format, invalid name
    with pytest.raises(KeyError):
        await znp.request(c.SYS.Ping.Req(), RspFoo=0x01)

    # Valid format, valid name
    ping_rsp = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    event_loop.call_soon(znp_server.send, ping_rsp)
    assert (
        await znp.request(c.SYS.Ping.Req(), RspCapabilities=t.MTCapabilities.SYS)
    ) == ping_rsp

    # Commands with no response (not an empty response!) can still be sent
    reset_req = c.SYS.ResetReq.Req(Type=t.ResetType.Soft)
    reset_req_received = znp_server.wait_for_response(reset_req)
    reset_rsp = await znp.request(reset_req)

    assert (await reset_req_received) == reset_req
    assert reset_rsp is None

    # You cannot send anything but requests
    with pytest.raises(ValueError):
        await znp.request(c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS))

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


async def test_znp_request_not_recognized(connected_znp, event_loop):
    znp, _ = connected_znp

    # An error is raise when a bad request is sent
    request = c.SYS.Ping.Req()
    unknown_rsp = c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=request.header
    )

    with pytest.raises(CommandNotRecognized):
        event_loop.call_soon(znp.frame_received, unknown_rsp.to_frame())
        await znp.request(request)


async def test_znp_request_wrong_params(connected_znp, event_loop):
    znp, _ = connected_znp

    # You cannot specify response kwargs for responses with no response
    with pytest.raises(ValueError):
        await znp.request(c.SYS.ResetReq.Req(Type=t.ResetType.Soft), foo=0x01)

    # An error is raised when a response with bad params is received
    with pytest.raises(InvalidCommandResponse):
        event_loop.call_soon(
            znp.frame_received,
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS).to_frame(),
        )
        await znp.request(c.SYS.Ping.Req(), RspCapabilities=t.MTCapabilities.APP)


async def test_znp_sreq_srsp(connected_znp, event_loop):
    znp, _ = connected_znp

    # Each SREQ must have a corresponding SRSP, so this will fail
    with pytest.raises(asyncio.TimeoutError):
        with async_timeout.timeout(0.5):
            await znp.request(c.SYS.Ping.Req())

    # This will work
    ping_rsp = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    event_loop.call_soon(znp.frame_received, ping_rsp.to_frame())

    await znp.request(c.SYS.Ping.Req())


async def test_znp_unknown_frame(connected_znp, caplog):
    znp, _ = connected_znp

    frame = GeneralFrame(
        header=t.CommandHeader(0xFFFF),
        data=b"Frame Data",
    )

    caplog.set_level(logging.ERROR)
    znp.frame_received(frame)

    # Unknown frames are logged in their entirety but an error is not thrown
    assert repr(frame) in caplog.text
