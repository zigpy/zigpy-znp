import pytest

import zigpy_znp.commands as c
import zigpy_znp.types as t
from zigpy_znp.api import ZNP


@pytest.fixture
def znp():
    return ZNP()


@pytest.mark.asyncio
async def test_znp_responses(znp):
    # Can't wait for non-response types
    with pytest.raises(ValueError):
        await znp.wait_for_response(c.SysCommands.Ping.Req())

    future = znp.wait_for_response(c.SysCommands.Ping.Rsp(partial=True))

    response = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    znp.frame_received(response.to_frame())

    assert (await future) == response


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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

    # This future will never resolve because there was no listener matching this request
    assert not future.done()
