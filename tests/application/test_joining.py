import asyncio
import contextlib
from unittest import mock

import pytest
import zigpy.util
import zigpy.types
import zigpy.device
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c

from ..conftest import (
    FORMED_DEVICES,
    FORMED_ZSTACK3_DEVICES,
    CoroutineMock,
    FormedLaunchpadCC26X2R1,
    zdo_request_matcher,
    serialize_zdo_command,
)


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_permit_join(device, mocker, make_application):
    app, znp_server = make_application(server_cls=device)

    permit_join_coordinator = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.NWK, Dst=0x0000, Duration=10, partial=True
        ),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    # Handle the ZDO broadcast sent by Zigpy
    permit_join_broadcast_raw = znp_server.reply_once_to(
        request=zdo_request_matcher(
            dst_addr=t.AddrModeAddress(t.AddrMode.Broadcast, 0xFFFC),
            command_id=zdo_t.ZDOCmd.Mgmt_Permit_Joining_req,
            TSN=2,
            zdo_PermitDuration=10,
            zdo_TC_Significant=0,
        ),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    # And the duplicate one using the MT command
    permit_join_broadcast = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.Broadcast, Dst=0xFFFC, Duration=10, partial=True
        ),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    await app.startup(auto_form=False)
    await app.permit(time_s=10)

    await permit_join_broadcast
    await permit_join_broadcast_raw

    if device.code_revision >= 20210708:
        assert not permit_join_coordinator.done()
    else:
        assert permit_join_coordinator.done()

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_join_coordinator(device, make_application):
    app, znp_server = make_application(server_cls=device)

    # Handle us opening joins on the coordinator
    permit_join_coordinator = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.NWK, Dst=0x0000, Duration=60, partial=True
        ),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    await app.startup(auto_form=False)
    await app.permit(node=app.state.node_info.ieee)

    await permit_join_coordinator

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_join_device(device, make_application):
    ieee = t.EUI64.convert("EC:1B:BD:FF:FE:54:4F:40")
    nwk = 0x1234

    app, znp_server = make_application(server_cls=device)
    device = app.add_initialized_device(ieee=ieee, nwk=nwk)

    permit_join = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.NWK, Dst=nwk, Duration=60, partial=True
        ),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=nwk, Status=t.ZDOStatus.SUCCESS),
            c.ZDO.MsgCbIncoming.Callback(
                Src=nwk,
                IsBroadcast=t.Bool.false,
                ClusterId=32822,
                SecurityUse=0,
                TSN=1,
                MacDst=0x0000,
                Data=b"\x00",
            ),
        ],
    )

    await app.startup(auto_form=False)
    await app.permit(node=ieee)

    await permit_join

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_ZSTACK3_DEVICES)
@pytest.mark.parametrize("permit_result", [None, asyncio.TimeoutError()])
async def test_permit_join_with_key(device, permit_result, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    # Consciot bulb
    ieee = t.EUI64.convert("EC:1B:BD:FF:FE:54:4F:40")
    code = bytes.fromhex("17D1856872570CEB7ACB53030C5D6DA368B1")
    link_key = t.KeyData(zigpy.util.convert_install_code(code))

    bdb_add_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBAddInstallCode.Req(
            InstallCodeFormat=c.app_config.InstallCodeFormat.KeyDerivedFromInstallCode,
            IEEE=ieee,
            InstallCode=t.Bytes(link_key),
        ),
        responses=[c.AppConfig.BDBAddInstallCode.Rsp(Status=t.Status.SUCCESS)],
    )

    join_enable_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(BdbJoinUsesInstallCodeKey=True),
        responses=[
            c.AppConfig.BDBSetJoinUsesInstallCodeKey.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    join_disable_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(BdbJoinUsesInstallCodeKey=False),
        responses=[
            c.AppConfig.BDBSetJoinUsesInstallCodeKey.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    await app.startup(auto_form=False)

    mocker.patch.object(app, "permit", new=CoroutineMock(side_effect=permit_result))

    with contextlib.nullcontext() if permit_result is None else pytest.raises(
        asyncio.TimeoutError
    ):
        await app.permit_with_link_key(node=ieee, link_key=link_key, time_s=1)

    await bdb_add_install_code
    await join_enable_install_code
    assert app.permit.call_count == 1

    # The install code policy is reset right after
    await join_disable_install_code

    await app.shutdown()


@mock.patch(
    "zigpy.device.Device._initialize",
    new=zigpy.device.Device._initialize.__wrapped__,  # to disable retries
)
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join", wraps=app.handle_join)
    mocker.patch("zigpy_znp.zigbee.application.DEVICE_JOIN_MAX_DELAY", new=0)

    nwk = 0x1234
    ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))

    await asyncio.sleep(0.1)

    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)

    await app.shutdown()


@mock.patch(
    "zigpy.device.Device._initialize",
    new=zigpy.device.Device._initialize.__wrapped__,  # to disable retries
)
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join_and_announce_fast(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join", wraps=app.handle_join)
    mocker.patch("zigpy_znp.zigbee.application.DEVICE_JOIN_MAX_DELAY", new=0.5)

    nwk = 0x1234
    ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")

    assert not app._join_announce_tasks

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))

    # We're waiting for the device to announce itself
    assert app.handle_join.call_count == 0

    await asyncio.sleep(0.1)

    znp_server.send(
        c.ZDO.MsgCbIncoming.Callback(
            Src=nwk,
            IsBroadcast=t.Bool.false,
            ClusterId=zdo_t.ZDOCmd.Device_annce,
            SecurityUse=0,
            TSN=123,
            MacDst=0x0000,
            Data=serialize_zdo_command(
                command_id=zdo_t.ZDOCmd.Device_annce,
                NWKAddr=nwk,
                IEEEAddr=ieee,
                Capability=c.zdo.MACCapabilities.AllocateShortAddrDuringAssocNeeded,
                Status=t.ZDOStatus.SUCCESS,
            ),
        )
    )

    znp_server.send(
        c.ZDO.EndDeviceAnnceInd.Callback(
            Src=nwk,
            NWK=nwk,
            IEEE=ieee,
            Capabilities=c.zdo.MACCapabilities.AllocateShortAddrDuringAssocNeeded,
        )
    )

    await asyncio.sleep(0.1)

    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=None)

    # Everything is cleaned up
    assert not app._join_announce_tasks

    app.get_device(ieee=ieee).cancel_initialization()
    await app.shutdown()

    with pytest.raises(asyncio.CancelledError):
        await app.get_device(ieee=ieee)._initialize_task


@mock.patch("zigpy_znp.zigbee.application.DEVICE_JOIN_MAX_DELAY", new=0.1)
@mock.patch(
    "zigpy.device.Device._initialize",
    new=zigpy.device.Device._initialize.__wrapped__,  # to disable retries
)
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join_and_announce_slow(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    mocker.patch.object(app, "handle_join", wraps=app.handle_join)

    nwk = 0x1234
    ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")

    assert not app._join_announce_tasks

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))

    # We're waiting for the device to announce itself
    assert app.handle_join.call_count == 0

    # Wait for the trust center join timeout to elapse
    while app.handle_join.call_count == 0:
        await asyncio.sleep(0.1)

    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)

    # Finally, send the device announcement
    znp_server.send(
        c.ZDO.MsgCbIncoming.Callback(
            Src=nwk,
            IsBroadcast=t.Bool.false,
            ClusterId=zdo_t.ZDOCmd.Device_annce,
            SecurityUse=0,
            TSN=123,
            MacDst=0x0000,
            Data=serialize_zdo_command(
                command_id=zdo_t.ZDOCmd.Device_annce,
                NWKAddr=nwk,
                IEEEAddr=ieee,
                Capability=c.zdo.MACCapabilities.AllocateShortAddrDuringAssocNeeded,
                Status=t.ZDOStatus.SUCCESS,
            ),
        )
    )

    znp_server.send(
        c.ZDO.EndDeviceAnnceInd.Callback(
            Src=nwk,
            NWK=nwk,
            IEEE=ieee,
            Capabilities=c.zdo.MACCapabilities.AllocateShortAddrDuringAssocNeeded,
        )
    )

    await asyncio.sleep(0.5)

    # The announcement will trigger another join indication
    assert app.handle_join.call_count == 2

    app.get_device(ieee=ieee).cancel_initialization()
    await app.shutdown()

    with pytest.raises(asyncio.CancelledError):
        await app.get_device(ieee=ieee)._initialize_task
