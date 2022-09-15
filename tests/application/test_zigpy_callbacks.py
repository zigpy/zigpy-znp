import asyncio
from unittest.mock import MagicMock

import pytest
import zigpy.types as zigpy_t
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c

from ..conftest import FORMED_DEVICES, serialize_zdo_command


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_relays_message_callback(device, make_application, mocker):
    app, znp_server = await make_application(server_cls=device)
    await app.startup(auto_form=False)

    app.handle_relays = MagicMock()
    znp_server.send(c.ZDO.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD]))

    await asyncio.sleep(0.1)

    app.handle_relays.assert_called_once_with(nwk=0x1234, relays=[0x5678, 0xABCD])

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_announce_nwk_change(device, make_application, mocker):
    app, znp_server = await make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.spy(app, "handle_join")
    mocker.patch.object(app, "handle_message")

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)
    new_nwk = device.nwk + 1

    # Assume its NWK changed and we're just finding out
    znp_server.send(
        c.ZDO.MsgCbIncoming.Callback(
            Src=0x0001,
            IsBroadcast=t.Bool.false,
            ClusterId=zdo_t.ZDOCmd.Device_annce,
            SecurityUse=0,
            TSN=123,
            MacDst=0x0000,
            Data=serialize_zdo_command(
                command_id=zdo_t.ZDOCmd.Device_annce,
                NWKAddr=new_nwk,
                IEEEAddr=device.ieee,
                Capability=c.zdo.MACCapabilities.Router,
                Status=t.ZDOStatus.SUCCESS,
            ),
        )
    )

    znp_server.send(
        c.ZDO.EndDeviceAnnceInd.Callback(
            Src=0x0001,
            NWK=new_nwk,
            IEEE=device.ieee,
            Capabilities=c.zdo.MACCapabilities.Router,
        )
    )

    await asyncio.sleep(0.1)

    app.handle_join.assert_called_once_with(
        nwk=new_nwk, ieee=device.ieee, parent_nwk=None
    )

    # The device's NWK has been updated
    assert device.nwk == new_nwk

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_leave_callback(device, make_application, mocker):
    app, znp_server = await make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_leave")

    nwk = 0x1234
    ieee = t.EUI64(range(8))

    znp_server.send(
        c.ZDO.LeaveInd.Callback(
            NWK=nwk, IEEE=ieee, Request=False, Remove=False, Rejoin=False
        )
    )
    app.handle_leave.assert_called_once_with(nwk=nwk, ieee=ieee)

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_af_message_callback(device, make_application, mocker):
    app, znp_server = await make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_message")
    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    af_message = c.AF.IncomingMsg.Callback(
        GroupId=0x0000,
        ClusterId=2,
        SrcAddr=device.nwk,
        SrcEndpoint=4,
        DstEndpoint=1,  # ZHA endpoint
        WasBroadcast=False,
        LQI=19,
        SecurityUse=False,
        TimeStamp=0,
        TSN=0,
        Data=b"test",
        MacSrcAddr=0x0000,
        MsgResultRadius=1,
    )

    # Normal message
    znp_server.send(af_message)
    await asyncio.sleep(0.1)

    app.handle_message.assert_called_once_with(
        sender=device,
        profile=260,
        cluster=2,
        src_ep=4,
        dst_ep=1,
        message=b"test",
        dst_addressing=zigpy_t.AddrMode.NWK,
    )

    app.handle_message.reset_mock()

    # ZLL message
    znp_server.send(af_message.replace(DstEndpoint=2))
    await asyncio.sleep(0.1)

    app.handle_message.assert_called_once_with(
        sender=device,
        profile=49246,
        cluster=2,
        src_ep=4,
        dst_ep=2,
        message=b"test",
        dst_addressing=zigpy_t.AddrMode.NWK,
    )

    app.handle_message.reset_mock()

    # Message on an unknown endpoint (is this possible?)
    znp_server.send(af_message.replace(DstEndpoint=3))
    await asyncio.sleep(0.1)

    app.handle_message.assert_called_once_with(
        sender=device,
        profile=260,
        cluster=2,
        src_ep=4,
        dst_ep=3,
        message=b"test",
        dst_addressing=zigpy_t.AddrMode.NWK,
    )

    app.handle_message.reset_mock()
