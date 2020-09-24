import asyncio

import pytest
import async_timeout

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import _deduplicate_commands

pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


async def test_responses(connected_znp):
    znp, znp_server = connected_znp

    assert not znp._listeners

    future = znp.wait_for_response(c.SYS.Ping.Rsp(partial=True))

    assert znp._listeners

    response = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    znp_server.send(response)

    assert (await future) == response

    # Our listener will have been cleaned up after a step
    await asyncio.sleep(0)
    assert not znp._listeners


async def test_responses_multiple(connected_znp):
    znp, _ = connected_znp

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


async def test_response_timeouts(connected_znp):
    znp, _ = connected_znp

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
    assert not znp._listeners


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


async def test_response_callback_simple(connected_znp, event_loop, mocker):
    znp, _ = connected_znp

    sync_callback = mocker.Mock()

    good_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.FAILURE)
    bad_response = c.SYS.SetExtAddr.Rsp(Status=t.Status.SUCCESS)

    znp.callback_for_response(good_response, sync_callback)

    znp.frame_received(bad_response.to_frame())
    assert sync_callback.call_count == 0

    znp.frame_received(good_response.to_frame())
    sync_callback.assert_called_once_with(good_response)


# These two tests are not async at all but pytest.mark.asyncio throws an error due to it
# being implicitly marked as "asyncio"
async def test_command_deduplication_simple():
    c1 = c.SYS.Ping.Rsp(partial=True)
    c2 = c.Util.TimeAlive.Rsp(Seconds=12)

    assert _deduplicate_commands([]) == ()
    assert _deduplicate_commands([c1]) == (c1,)
    assert _deduplicate_commands([c1, c1]) == (c1,)
    assert _deduplicate_commands([c1, c2]) == (c1, c2)
    assert _deduplicate_commands([c2, c1, c2]) == (c2, c1)


async def test_command_deduplication_complex():
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


async def test_response_callbacks(connected_znp, event_loop, mocker):
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


async def test_wait_for_responses(connected_znp, event_loop):
    znp, _ = connected_znp

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
