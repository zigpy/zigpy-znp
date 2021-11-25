import asyncio
import logging

import pytest
from zigpy.zdo.types import ZDOCmd

import zigpy_znp.types as t
import zigpy_znp.commands as c

from ..conftest import FORMED_DEVICES, CoroutineMock


def awaitable_mock(return_value):
    mock_called = asyncio.get_running_loop().create_future()

    def side_effect(*args, **kwargs):
        mock_called.set_result((args, kwargs))

        return return_value

    return mock_called, CoroutineMock(side_effect=side_effect)


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_relays_message_callback(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = mocker.Mock()
    discover_called, discover_mock = awaitable_mock(return_value=device)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)

    znp_server.send(c.ZDO.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD]))

    await discover_called
    assert device.relays == [0x5678, 0xABCD]

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_relays_message_callback_unknown(
    device, make_application, mocker, caplog
):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    discover_called, discover_mock = awaitable_mock(return_value=None)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)

    caplog.set_level(logging.WARNING)
    znp_server.send(c.ZDO.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD]))

    await discover_called
    assert "unknown device" in caplog.text

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_announce_nwk_change(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.spy(app, "handle_join")
    mocker.patch.object(app, "handle_message")

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)
    new_nwk = device.nwk + 1

    # Assume its NWK changed and we're just finding out
    znp_server.send(
        c.ZDO.EndDeviceAnnceInd.Callback(
            Src=0x0001,
            NWK=new_nwk,
            IEEE=device.ieee,
            Capabilities=c.zdo.MACCapabilities.Router,
        )
    )

    app.handle_join.assert_called_once_with(
        nwk=new_nwk, ieee=device.ieee, parent_nwk=None
    )
    assert app.handle_message.call_count == 1
    assert app.handle_message.mock_calls[0][2]["cluster"] == ZDOCmd.Device_annce

    # The device's NWK updated
    assert device.nwk == new_nwk

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_leave_callback(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
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
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = mocker.Mock()
    discover_called, discover_mock = awaitable_mock(return_value=device)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)
    mocker.patch.object(app, "handle_message")
    mocker.patch.object(app, "get_device")

    af_message = c.AF.IncomingMsg.Callback(
        GroupId=1,
        ClusterId=2,
        SrcAddr=0xABCD,
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

    await discover_called
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=260, cluster=2, src_ep=4, dst_ep=1, message=b"test"
    )

    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    # ZLL message
    discover_called, discover_mock = awaitable_mock(return_value=device)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)

    znp_server.send(af_message.replace(DstEndpoint=2))

    await discover_called
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=49246, cluster=2, src_ep=4, dst_ep=2, message=b"test"
    )

    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    # Message on an unknown endpoint (is this possible?)
    discover_called, discover_mock = awaitable_mock(return_value=device)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)

    znp_server.send(af_message.replace(DstEndpoint=3))

    await discover_called
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=260, cluster=2, src_ep=4, dst_ep=3, message=b"test"
    )

    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    # Message from an unknown device
    discover_called, discover_mock = awaitable_mock(return_value=None)
    mocker.patch.object(app, "_get_or_discover_device", new=discover_mock)

    znp_server.send(af_message)

    await discover_called
    assert device.radio_details.call_count == 0
    assert app.handle_message.call_count == 0

    await app.shutdown()
