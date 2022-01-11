import asyncio
import contextlib

import pytest
import zigpy.util
import zigpy.types
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


@pytest.mark.parametrize(
    "device,fixed_joining_bug",
    [(d, False) for d in FORMED_DEVICES] + [(FormedLaunchpadCC26X2R1, True)],
)
async def test_permit_join(device, fixed_joining_bug, mocker, make_application):
    if fixed_joining_bug:
        mocker.patch.object(device, "code_revision", 20210708)

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
            TSN=6,
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

    if fixed_joining_bug:
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
    await app.permit(node=app.ieee)

    await permit_join_coordinator

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_ZSTACK3_DEVICES)
@pytest.mark.parametrize("permit_result", [None, asyncio.TimeoutError()])
async def test_permit_join_with_key(device, permit_result, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    # Consciot bulb
    ieee = t.EUI64.convert("EC:1B:BD:FF:FE:54:4F:40")
    code = bytes.fromhex("17D1856872570CEB7ACB53030C5D6DA368B1")

    bdb_add_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBAddInstallCode.Req(
            InstallCodeFormat=c.app_config.InstallCodeFormat.KeyDerivedFromInstallCode,
            IEEE=ieee,
            InstallCode=t.Bytes(zigpy.util.convert_install_code(code)),
        ),
        responses=[c.AppConfig.BDBAddInstallCode.Rsp(Status=t.Status.SUCCESS)],
    )

    join_enable_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(BdbJoinUsesInstallCodeKey=True),
        responses=[
            c.AppConfig.BDBSetJoinUsesInstallCodeKey.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    mocker.patch.object(
        app, "permit", new=CoroutineMock(side_effect=[None, permit_result])
    )

    join_disable_install_code = znp_server.reply_once_to(
        c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(BdbJoinUsesInstallCodeKey=False),
        responses=[
            c.AppConfig.BDBSetJoinUsesInstallCodeKey.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    await app.startup(auto_form=False)

    with contextlib.nullcontext() if permit_result is None else pytest.raises(
        asyncio.TimeoutError
    ):
        await app.permit_with_key(node=ieee, code=code, time_s=1)

    await bdb_add_install_code
    await join_enable_install_code
    assert app.permit.call_count == 2

    # The install code policy is reset right after
    await join_disable_install_code

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_ZSTACK3_DEVICES)
async def test_permit_join_with_invalid_key(device, make_application):
    app, znp_server = make_application(server_cls=device)

    # Consciot bulb
    ieee = t.EUI64.convert("EC:1B:BD:FF:FE:54:4F:40")
    code = bytes.fromhex("17D1856872570CEB7ACB53030C5D6DA368B1")[:-1]  # truncate it

    with pytest.raises(ValueError):
        await app.permit_with_key(node=ieee, code=code, time_s=1)

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join")
    mocker.patch("zigpy_znp.zigbee.application.DEVICE_JOIN_MAX_DELAY", new=0)

    nwk = 0x1234
    ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))

    await asyncio.sleep(0.1)

    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join_and_announce_fast(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join")
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

    await app.pre_shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_on_zdo_device_join_and_announce_slow(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    mocker.patch.object(app, "handle_join")
    mocker.patch("zigpy_znp.zigbee.application.DEVICE_JOIN_MAX_DELAY", new=0.1)

    nwk = 0x1234
    ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")

    assert not app._join_announce_tasks

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))

    # We're waiting for the device to announce itself
    assert app.handle_join.call_count == 0

    await asyncio.sleep(0.3)

    # Too late, it already happened
    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)

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

    # The announcement will trigger another join indication
    assert app.handle_join.call_count == 2

    await app.pre_shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_unknown_device_discovery(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    mocker.spy(app, "handle_join")

    # Existing devices do not need to be discovered
    existing_nwk = 0x1234
    existing_ieee = t.EUI64(range(8))
    device = app.add_initialized_device(ieee=existing_ieee, nwk=existing_nwk)

    assert (await app._get_or_discover_device(nwk=existing_nwk)) is device
    assert app.handle_join.call_count == 0

    # If the device changes its NWK but doesn't tell zigpy, it will be re-discovered
    did_ieee_addr_req1 = znp_server.reply_once_to(
        request=c.ZDO.IEEEAddrReq.Req(
            NWK=existing_nwk + 1,
            RequestType=c.zdo.AddrRequestType.SINGLE,
            StartIndex=0,
        ),
        responses=[
            c.ZDO.IEEEAddrReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.IEEEAddrRsp.Callback(
                Status=t.ZDOStatus.SUCCESS,
                IEEE=existing_ieee,
                NWK=existing_nwk + 1,
                NumAssoc=0,
                Index=0,
                Devices=[],
            ),
        ],
    )

    # The same device is discovered and its NWK was updated. Handles concurrency.
    devices = await asyncio.gather(
        app._get_or_discover_device(nwk=existing_nwk + 1),
        app._get_or_discover_device(nwk=existing_nwk + 1),
        app._get_or_discover_device(nwk=existing_nwk + 1),
        app._get_or_discover_device(nwk=existing_nwk + 1),
        app._get_or_discover_device(nwk=existing_nwk + 1),
    )

    assert devices == [device] * 5

    # Only a single request is sent, since the coroutines are grouped
    await did_ieee_addr_req1
    assert device.nwk == existing_nwk + 1
    assert app.handle_join.call_count == 1

    # If a completely unknown device joins the network, it will be treated as a new join
    new_nwk = 0x5678
    new_ieee = t.EUI64(range(1, 9))

    did_ieee_addr_req2 = znp_server.reply_once_to(
        request=c.ZDO.IEEEAddrReq.Req(
            NWK=new_nwk,
            RequestType=c.zdo.AddrRequestType.SINGLE,
            StartIndex=0,
        ),
        responses=[
            c.ZDO.IEEEAddrReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.IEEEAddrRsp.Callback(
                Status=t.ZDOStatus.SUCCESS,
                IEEE=new_ieee,
                NWK=new_nwk,
                NumAssoc=0,
                Index=0,
                Devices=[],
            ),
        ],
    )

    new_dev = await app._get_or_discover_device(nwk=new_nwk)
    await did_ieee_addr_req2
    assert app.handle_join.call_count == 2
    assert new_dev.nwk == new_nwk
    assert new_dev.ieee == new_ieee

    await app.pre_shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_unknown_device_discovery_failure(device, make_application, mocker):
    mocker.patch("zigpy_znp.zigbee.application.IEEE_ADDR_DISCOVERY_TIMEOUT", new=0.1)

    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    znp_server.reply_once_to(
        request=c.ZDO.IEEEAddrReq.Req(partial=True),
        responses=[
            c.ZDO.IEEEAddrReq.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    # Discovery will throw an exception when the device cannot be found
    with pytest.raises(KeyError):
        await app._get_or_discover_device(nwk=0x3456)

    await app.pre_shutdown()
