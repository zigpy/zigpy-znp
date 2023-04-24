import asyncio

import pytest
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c

from tests.conftest import FormedLaunchpadCC26X2R1


@pytest.mark.parametrize(
    "nwk_update_id,change_channel",
    [
        (1, False),
        (1, True),
        (1, False),
        (200, True),
    ],
)
@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_mgmt_nwk_update_req(
    device, nwk_update_id, change_channel, make_application, mocker
):
    mocker.patch("zigpy.application.CHANNEL_CHANGE_SETTINGS_RELOAD_DELAY_S", 0.1)

    app, znp_server = make_application(server_cls=device)

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

    await app.move_network_to_channel(new_channel=new_channel)

    if change_channel:
        await nwk_update_req
    else:
        assert not nwk_update_req.done()

    assert znp_server.nib.nwkLogicalChannel == new_channel

    await app.shutdown()
