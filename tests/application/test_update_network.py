import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c

from ..conftest import FORMED_DEVICES, CoroutineMock


pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_update_network_channel_noop(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.spy(app._znp, "request")

    assert app._znp.request.call_count == 0
    await app.update_network_channel(app.channel)
    assert app._znp.request.call_count == 0

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_update_network_channel_change(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    new_channel = app.channel + 1

    mocker.spy(app._znp, "request")
    mocker.patch(
        "zigpy_znp.zigbee.application.asyncio.sleep", new_callable=CoroutineMock
    )

    await app.update_network_channel(new_channel)

    assert app._znp.request.mock_calls[0][2]["request"] == c.ZDO.MgmtNWKUpdateReq.Req(
        Dst=0x0000,
        DstAddrMode=t.AddrMode.NWK,
        Channels=t.Channels.from_channel_list([new_channel]),
        ScanDuration=0xFE,
        ScanCount=0,
        NwkManagerAddr=0x0000,
    )

    assert app.channel == new_channel

    await app.shutdown()
