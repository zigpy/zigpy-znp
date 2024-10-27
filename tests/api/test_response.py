import asyncio

import pytest
import async_timeout

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.utils import deduplicate_commands


async def test_responses(connected_znp):
    znp, znp_server = connected_znp

    assert not any(znp._listeners.values())

    future = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))

    assert any(znp._listeners.values())

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    znp_server.send(response)

    assert (await future) == response

    # Our listener will have been cleaned up after a step
    await asyncio.sleep(0)
    assert not any(znp._listeners.values())


async def test_responses_multiple(connected_znp):
    znp, _ = connected_znp

    assert not any(znp._listeners.values())

    future1 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
    future2 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
    future3 = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    znp.frame_received(response.to_frame())

    await future1
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not future2.done()
    assert not future3.done()

    assert any(znp._listeners.values())


async def test_response_timeouts(connected_znp):
    znp, _ = connected_znp

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)

    async def send_soon(delay):
        await asyncio.sleep(delay)
        znp.frame_received(response.to_frame())

    asyncio.create_task(send_soon(0.1))

    async with async_timeout.timeout(0.5):
        assert (await znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))) == response

    # The response was successfully received so we should have no outstanding listeners
    await asyncio.sleep(0)
    assert not any(znp._listeners.values())

    asyncio.create_task(send_soon(0.6))

    with pytest.raises(asyncio.TimeoutError):
        async with async_timeout.timeout(0.5):
            assert (
                await znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))
            ) == response

    # Our future still completed, albeit unsuccessfully.
    # We should have no leaked listeners here.
    assert not any(znp._listeners.values())


async def test_response_matching_partial(connected_znp):
    znp, _ = connected_znp

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


async def test_response_matching_exact(connected_znp):
    znp, _ = connected_znp

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


async def test_response_not_matching_out_of_order(connected_znp):
    znp, _ = connected_znp

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


async def test_wait_responses_empty(connected_znp):
    znp, _ = connected_znp

    # You shouldn't be able to wait for an empty list of responses
    with pytest.raises(ValueError):
        await znp.wait_for_responses([])


async def test_response_callback_simple(connected_znp, mocker):
    znp, _ = connected_znp

    sync_callback = mocker.Mock()

    good_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.FAILURE)
    bad_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)

    znp.callback_for_response(good_response, sync_callback)

    znp.frame_received(bad_response.to_frame())
    assert sync_callback.call_count == 0

    znp.frame_received(good_response.to_frame())
    sync_callback.assert_called_once_with(good_response)


async def test_response_callbacks(connected_znp, mocker):
    znp, _ = connected_znp

    sync_callback = mocker.Mock()
    bad_sync_callback = mocker.Mock(
        side_effect=RuntimeError
    )  # Exceptions should not interfere with other callbacks

    async_callback_responses = []

    # XXX: I can't get AsyncMock().call_count to work, even though
    # the callback is definitely being called
    async def async_callback(response):
        await asyncio.sleep(0)
        async_callback_responses.append(response)

    good_response1 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    good_response2 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.APP)
    good_response3 = c.UTIL.TimeAlive.Rsp(Seconds=12)
    bad_response1 = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)
    bad_response2 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    responses = [
        # Duplicating matching responses shouldn't do anything
        c.SYS.Ping.Rsp(partial=True),
        c.SYS.Ping.Rsp(partial=True),
        # Matching against different response types should also work
        c.UTIL.TimeAlive.Rsp(Seconds=12),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
        c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
        c.UTIL.TimeAlive.Rsp(Seconds=10),
    ]

    assert set(deduplicate_commands(responses)) == {
        c.SYS.Ping.Rsp(partial=True),
        c.UTIL.TimeAlive.Rsp(Seconds=12),
        c.UTIL.TimeAlive.Rsp(Seconds=10),
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


async def test_wait_for_responses(connected_znp):
    znp, _ = connected_znp

    response1 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)
    response2 = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.APP)
    response3 = c.UTIL.TimeAlive.Rsp(Seconds=12)
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
            c.UTIL.TimeAlive.Rsp(Seconds=12),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.UTIL),
        ]
    )

    # Will not match anything
    future3 = znp.wait_for_responses([c.UTIL.TimeAlive.Rsp(Seconds=10)])

    # Will match response1 the second time around
    future4 = znp.wait_for_responses(
        [
            # Matching against different response types should also work
            c.UTIL.TimeAlive.Rsp(Seconds=12),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
            c.UTIL.TimeAlive.Rsp(Seconds=10),
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

    znp.frame_received(c.UTIL.TimeAlive.Rsp(Seconds=10).to_frame())
    assert future3.done()
    assert (await future3) == c.UTIL.TimeAlive.Rsp(Seconds=10)
