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
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    app.handle_relays = MagicMock()
    znp_server.send(c.ZDO.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD]))

    await asyncio.sleep(0.1)

    app.handle_relays.assert_called_once_with(nwk=0x1234, relays=[0x5678, 0xABCD])

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

    mocker.patch.object(app, "packet_received")
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

    app.packet_received.assert_called_once_with(
        zigpy_t.ZigbeePacket(
            profile_id=260,
            cluster_id=0x0002,
            src_ep=4,
            dst_ep=1,
            data=t.SerializableBytes(b"test"),
            src=zigpy_t.AddrModeAddress(
                addr_mode=zigpy_t.AddrMode.NWK,
                address=device.nwk,
            ),
            dst=zigpy_t.AddrModeAddress(
                addr_mode=t.AddrMode.NWK,
                address=app.state.node_info.nwk,
            ),
            lqi=19,
            rssi=None,
            radius=1,
        )
    )

    app.packet_received.reset_mock()

    # ZLL message
    znp_server.send(af_message.replace(DstEndpoint=2))
    await asyncio.sleep(0.1)

    app.packet_received.assert_called_once_with(
        zigpy_t.ZigbeePacket(
            profile_id=49246,  # Profile ID is missing but inferred from registered EP
            cluster_id=0x0002,
            src_ep=4,
            dst_ep=2,
            data=t.SerializableBytes(b"test"),
            src=zigpy_t.AddrModeAddress(
                addr_mode=zigpy_t.AddrMode.NWK,
                address=device.nwk,
            ),
            dst=zigpy_t.AddrModeAddress(
                addr_mode=t.AddrMode.NWK,
                address=app.state.node_info.nwk,
            ),
            lqi=19,
            rssi=None,
            radius=1,
        )
    )

    app.packet_received.reset_mock()

    # Message on an unknown endpoint (is this possible?)
    znp_server.send(af_message.replace(DstEndpoint=3))
    await asyncio.sleep(0.1)

    app.packet_received.assert_called_once_with(
        zigpy_t.ZigbeePacket(
            profile_id=260,
            cluster_id=0x0002,
            src_ep=4,
            dst_ep=3,
            data=t.SerializableBytes(b"test"),
            src=zigpy_t.AddrModeAddress(
                addr_mode=zigpy_t.AddrMode.NWK,
                address=device.nwk,
            ),
            dst=zigpy_t.AddrModeAddress(
                addr_mode=t.AddrMode.NWK,
                address=app.state.node_info.nwk,
            ),
            lqi=19,
            rssi=None,
            radius=1,
        )
    )

    app.packet_received.reset_mock()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_receive_zdo_broadcast(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "packet_received")

    zdo_callback = c.ZDO.MsgCbIncoming.Callback(
        Src=0x35D9,
        IsBroadcast=t.Bool.true,
        ClusterId=19,
        SecurityUse=0,
        TSN=129,
        MacDst=0xFFFF,
        Data=b"bogus",
    )
    znp_server.send(zdo_callback)
    await asyncio.sleep(0.1)

    assert app.packet_received.call_count == 1
    packet = app.packet_received.mock_calls[0].args[0]
    assert packet.src == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.NWK, address=0x35D9
    )
    assert packet.src_ep == 0x00
    assert packet.dst == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.Broadcast,
        address=zigpy_t.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
    )
    assert packet.dst_ep == 0x00
    assert packet.cluster_id == zdo_callback.ClusterId
    assert packet.tsn == zdo_callback.TSN
    assert packet.data.serialize() == bytes([zdo_callback.TSN]) + zdo_callback.Data

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_receive_af_broadcast(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "packet_received")

    af_callback = c.AF.IncomingMsg.Callback(
        GroupId=0x0000,
        ClusterId=4096,
        SrcAddr=0x1234,
        SrcEndpoint=254,
        DstEndpoint=2,
        WasBroadcast=t.Bool.true,
        LQI=90,
        SecurityUse=t.Bool.false,
        TimeStamp=4442962,
        TSN=0,
        Data=b"\x11\xA6\x00\x74\xB5\x7C\x00\x02\x5F",
        MacSrcAddr=0x0000,
        MsgResultRadius=0,
    )
    znp_server.send(af_callback)
    await asyncio.sleep(0.1)

    assert app.packet_received.call_count == 1
    packet = app.packet_received.mock_calls[0].args[0]
    assert packet.src == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.NWK,
        address=0x1234,
    )
    assert packet.src_ep == af_callback.SrcEndpoint
    assert packet.dst == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.Broadcast,
        address=zigpy_t.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
    )
    assert packet.dst_ep == af_callback.DstEndpoint
    assert packet.cluster_id == af_callback.ClusterId
    assert packet.tsn == af_callback.TSN
    assert packet.lqi == af_callback.LQI
    assert packet.data.serialize() == af_callback.Data

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_receive_af_group(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "packet_received")

    af_callback = c.AF.IncomingMsg.Callback(
        GroupId=0x1234,
        ClusterId=4096,
        SrcAddr=0x1234,
        SrcEndpoint=254,
        DstEndpoint=0,
        WasBroadcast=t.Bool.false,
        LQI=90,
        SecurityUse=t.Bool.false,
        TimeStamp=4442962,
        TSN=0,
        Data=b"\x11\xA6\x00\x74\xB5\x7C\x00\x02\x5F",
        MacSrcAddr=0x0000,
        MsgResultRadius=0,
    )
    znp_server.send(af_callback)
    await asyncio.sleep(0.1)

    assert app.packet_received.call_count == 1
    packet = app.packet_received.mock_calls[0].args[0]
    assert packet.src == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.NWK,
        address=0x1234,
    )
    assert packet.src_ep == af_callback.SrcEndpoint
    assert packet.dst == zigpy_t.AddrModeAddress(
        addr_mode=zigpy_t.AddrMode.Group, address=0x1234
    )
    assert packet.cluster_id == af_callback.ClusterId
    assert packet.tsn == af_callback.TSN
    assert packet.lqi == af_callback.LQI
    assert packet.data.serialize() == af_callback.Data

    await app.shutdown()
