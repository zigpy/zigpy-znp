import asyncio

import pytest
import zigpy.zdo
import zigpy.types as zigpy_t
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c

from tests.conftest import FormedLaunchpadCC26X2R1


@pytest.mark.parametrize(
    "broadcast,nwk_update_id,change_channel",
    [
        (False, 1, False),
        (False, 1, True),
        (True, 1, False),
        (False, 200, True),
    ],
)
@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_mgmt_nwk_update_req(
    device, broadcast, nwk_update_id, change_channel, make_application, mocker
):
    mocker.patch("zigpy_znp.zigbee.device.NWK_UPDATE_LOOP_DELAY", 0.1)

    app, znp_server = await make_application(server_cls=device)

    if change_channel:
        new_channel = 11 + (26 - znp_server.nib.nwkLogicalChannel)
    else:
        new_channel = znp_server.nib.nwkLogicalChannel

    async def update_channel(req):
        # Wait a bit before updating
        await asyncio.sleep(0.5)

        znp_server.nib = znp_server.nib.replace(
            nwkUpdateId=znp_server.nib.nwkUpdateId + 1,
            nwkLogicalChannel=list(req.Channels)[0],
            channelList=req.Channels,
        )

        yield

    znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            DstEndpoint=0,
            ClusterId=zdo_t.ZDOCmd.Mgmt_NWK_Update_req,
            partial=True,
        ),
        responses=[c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS)],
    )

    nwk_update_req = znp_server.reply_once_to(
        request=c.ZDO.MgmtNWKUpdateReq.Req(
            Dst=0x0000,
            DstAddrMode=t.AddrMode.NWK,
            Channels=t.Channels.from_channel_list([new_channel]),
            ScanDuration=254,
            # Missing fields in the request cannot be `None` in the Z-Stack command
            ScanCount=0,
            NwkManagerAddr=0x0000,
        ),
        responses=[
            c.ZDO.MgmtNWKUpdateReq.Rsp(Status=t.Status.SUCCESS),
            update_channel,
        ],
    )

    await app.startup(auto_form=False)

    update = zdo_t.NwkUpdate(
        ScanChannels=t.Channels.from_channel_list([new_channel]),
        ScanDuration=zdo_t.NwkUpdate.CHANNEL_CHANGE_REQ,
        nwkUpdateId=nwk_update_id,
    )

    if broadcast:
        await zigpy.zdo.broadcast(
            app,
            zdo_t.ZDOCmd.Mgmt_NWK_Update_req,
            0x0000,  # group id (ignore)
            0,  # radius
            update,
            broadcast_address=zigpy_t.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
        )
    else:
        await app.zigpy_device.zdo.Mgmt_NWK_Update_req(update)

    if change_channel:
        await nwk_update_req
    else:
        assert not nwk_update_req.done()

    assert znp_server.nib.nwkLogicalChannel == list(update.ScanChannels)[0]

    await app.shutdown()
