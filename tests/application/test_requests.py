import asyncio

import pytest
import zigpy.types as zigpy_t
import zigpy.endpoint
import zigpy.profiles
import zigpy.zdo.types as zdo_t
from zigpy.exceptions import DeliveryError

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.exceptions import InvalidCommandResponse

from ..conftest import (
    FORMED_DEVICES,
    CoroutineMock,
    FormedLaunchpadCC26X2R1,
    zdo_request_matcher,
    serialize_zdo_command,
)


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_chosen_dst_endpoint(device, make_application, mocker):
    app, znp_server = make_application(device)
    await app.startup(auto_form=False)

    build = mocker.patch.object(type(app), "_zstack_build_id", mocker.PropertyMock())
    build.return_value = 20200708

    cluster = mocker.Mock()
    cluster.endpoint.endpoint_id = 2
    cluster.endpoint.profile_id = zigpy.profiles.zll.PROFILE_ID
    cluster.cluster_id = 0x1234

    # ZLL endpoint will be used normally
    assert app.get_dst_address(cluster).endpoint == 2

    build = mocker.patch.object(type(app), "_zstack_build_id", mocker.PropertyMock())
    build.return_value = 20210708

    # More recent builds work with everything on endpoint 1
    assert app.get_dst_address(cluster).endpoint == 1

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_zigpy_request(device, make_application):
    app, znp_server = make_application(device)
    await app.startup(auto_form=False)

    TSN = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    ep = device.add_endpoint(1)
    ep.status = zigpy.endpoint.Status.ZDO_INIT
    ep.profile_id = 260
    ep.add_input_cluster(6)

    # Respond to a light turn on request
    data_req = znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(
                mode=t.AddrMode.NWK, address=device.nwk
            ),
            DstEndpoint=1,
            SrcEndpoint=1,
            ClusterId=6,
            TSN=TSN,
            Data=bytes([0x01, TSN, 0x01]),
            partial=True,
        ),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.SUCCESS,
                Endpoint=1,
                TSN=TSN,
            ),
            c.ZDO.SrcRtgInd.Callback(DstAddr=device.nwk, Relays=[]),
            c.AF.IncomingMsg.Callback(
                GroupId=0x0000,
                ClusterId=6,
                SrcAddr=device.nwk,
                SrcEndpoint=1,
                DstEndpoint=1,
                WasBroadcast=False,
                LQI=63,
                SecurityUse=False,
                TimeStamp=1198515,
                TSN=0,
                Data=bytes([0x08, TSN, 0x0B, 0x00, 0x00]),
                MacSrcAddr=device.nwk,
                MsgResultRadius=29,
            ),
        ],
    )

    # Turn on the light
    await device.endpoints[1].on_off.on()
    await data_req

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_zigpy_request_failure(device, make_application, mocker):
    app, znp_server = make_application(device)
    await app.startup(auto_form=False)

    TSN = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    ep = device.add_endpoint(1)
    ep.profile_id = 260
    ep.add_input_cluster(6)

    # Fail to respond to a light turn on request
    znp_server.reply_to(
        request=c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(
                mode=t.AddrMode.NWK, address=device.nwk
            ),
            DstEndpoint=1,
            SrcEndpoint=1,
            ClusterId=6,
            TSN=TSN,
            Data=bytes([0x01, TSN, 0x01]),
            partial=True,
        ),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.FAILURE,
                Endpoint=1,
                TSN=TSN,
            ),
        ],
    )

    mocker.spy(app, "send_packet")

    # Fail to turn on the light
    with pytest.raises(InvalidCommandResponse):
        await device.endpoints[1].on_off.on()

    assert app.send_packet.call_count == 1
    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.parametrize(
    "addr",
    [
        t.AddrModeAddress(mode=t.AddrMode.IEEE, address=t.EUI64(range(8))),
        t.AddrModeAddress(mode=t.AddrMode.NWK, address=t.NWK(0xAABB)),
    ],
)
async def test_request_addr_mode(device, addr, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    mocker.patch.object(app, "send_packet", new=CoroutineMock())

    await app.request(
        device,
        use_ieee=(addr.mode == t.AddrMode.IEEE),
        profile=1,
        cluster=2,
        src_ep=3,
        dst_ep=4,
        sequence=5,
        data=b"6",
    )

    assert app.send_packet.call_count == 1
    assert app.send_packet.mock_calls[0].args[0].dst == addr.as_zigpy_type()

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_mrequest(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    mocker.patch.object(app, "send_packet", new=CoroutineMock())
    group = app.groups.add_group(0x1234, "test group")

    await group.endpoint.on_off.on()

    assert app.send_packet.call_count == 1
    assert (
        app.send_packet.mock_calls[0].args[0].dst
        == t.AddrModeAddress(mode=t.AddrMode.Group, address=0x1234).as_zigpy_type()
    )
    assert app.send_packet.mock_calls[0].args[0].data.serialize() == b"\x01\x01\x01"

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_mrequest_doesnt_block(device, make_application):
    app, znp_server = make_application(server_cls=device)

    znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(mode=t.AddrMode.Group, address=0x1234),
            ClusterId=0x0006,
            partial=True,
        ),
        responses=[
            # Confirm the request immediately but do not send a callback response until
            # *after* the group request is "done".
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
        ],
    )

    data_confirm_rsp = c.AF.DataConfirm.Callback(
        Status=t.Status.SUCCESS, Endpoint=1, TSN=2
    )

    request_sent = asyncio.get_running_loop().create_future()
    request_sent.add_done_callback(lambda _: znp_server.send(data_confirm_rsp))

    await app.startup(auto_form=False)

    group = app.groups.add_group(0x1234, "test group")
    await group.endpoint.on_off.on()
    request_sent.set_result(True)

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_broadcast(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup()

    znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(
                mode=t.AddrMode.Broadcast, address=0xFFFD
            ),
            DstEndpoint=0xFF,
            DstPanId=0x0000,
            SrcEndpoint=1,
            ClusterId=3,
            TSN=1,
            Radius=3,
            Data=b"???",
            partial=True,
        ),
        responses=[c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS)],
    )

    await app.broadcast(
        profile=260,  # ZHA
        cluster=0x0003,  # Identify
        src_ep=1,
        dst_ep=0xFF,  # Any endpoint
        grpid=0,
        radius=3,
        sequence=1,
        data=b"???",
        broadcast_address=zigpy_t.BroadcastAddress.RX_ON_WHEN_IDLE,
    )

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_concurrency(device, make_application, mocker):
    app, znp_server = make_application(
        server_cls=device,
        client_config={conf.CONF_MAX_CONCURRENT_REQUESTS: 2},
    )

    await app.startup()

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    # Keep track of how many requests we receive at once
    in_flight_requests = 0
    did_lock = False

    def make_response(req):
        async def callback(req):
            nonlocal in_flight_requests
            nonlocal did_lock

            if app._concurrent_requests_semaphore.locked():
                did_lock = True

            in_flight_requests += 1
            assert in_flight_requests <= 2

            await asyncio.sleep(0.1)
            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))
            await asyncio.sleep(0.01)
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS, Endpoint=1, TSN=req.TSN
                )
            )
            await asyncio.sleep(0)

            in_flight_requests -= 1
            assert in_flight_requests >= 0

        asyncio.create_task(callback(req))

    znp_server.reply_to(
        request=c.AF.DataRequestExt.Req(partial=True), responses=[make_response]
    )

    # We create a whole bunch at once
    await asyncio.gather(
        *[
            app.request(
                device,
                profile=260,
                cluster=1,
                src_ep=1,
                dst_ep=1,
                sequence=seq,
                data=b"\x00",
            )
            for seq in range(10)
        ]
    )

    assert in_flight_requests == 0
    assert did_lock

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_nonstandard_profile(device, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)

    ep = device.add_endpoint(2)
    ep.status = zigpy.endpoint.Status.ZDO_INIT
    ep.profile_id = 0x9876  # non-standard profile
    ep.add_input_cluster(0x0006)

    # Respond to a light turn on request
    data_req = znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(
                mode=t.AddrMode.NWK, address=device.nwk
            ),
            DstEndpoint=2,
            SrcEndpoint=1,  # we default to endpoint 1 for unknown profiles
            ClusterId=0x0006,
            partial=True,
        ),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            lambda req: c.AF.DataConfirm.Callback(
                Status=t.Status.SUCCESS,
                Endpoint=2,
                TSN=req.TSN,
            ),
            lambda req: c.AF.IncomingMsg.Callback(
                GroupId=0x0000,
                ClusterId=0x0006,
                SrcAddr=device.nwk,
                SrcEndpoint=2,
                DstEndpoint=1,
                WasBroadcast=t.Bool(False),
                LQI=63,
                SecurityUse=t.Bool(False),
                TimeStamp=12345678,
                TSN=0,
                Data=b"\x08" + bytes([req.TSN]) + b"\x0B\x00\x00",
                MacSrcAddr=device.nwk,
                MsgResultRadius=29,
            ),
        ],
    )

    await device.endpoints[2].on_off.off()

    await data_req

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_request_cancellation_shielding(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.spy(app._znp, "_unhandled_command")
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    delayed_reply_sent = asyncio.get_running_loop().create_future()

    def delayed_reply(req):
        async def inner():
            # Happens after DATA_CONFIRM_TIMEOUT expires but before ARSP_TIMEOUT
            await asyncio.sleep(0.5)
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS, Endpoint=1, TSN=req.TSN
                )
            )
            delayed_reply_sent.set_result(True)

        asyncio.create_task(inner())

    data_req = znp_server.reply_once_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            delayed_reply,
        ],
    )

    with pytest.raises(asyncio.TimeoutError):
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    await data_req
    await delayed_reply_sent

    assert app._znp._unhandled_command.call_count == 0

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_route_rediscovery_zdo(device, make_application, mocker):
    TSN = 1

    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    # Fail the first time
    route_discovered = False

    def route_replier(req):
        nonlocal route_discovered

        if not route_discovered:
            return c.ZDO.ExtRouteChk.Rsp(Status=c.zdo.RoutingStatus.FAIL)
        else:
            return c.ZDO.ExtRouteChk.Rsp(Status=c.zdo.RoutingStatus.SUCCESS)

    def set_route_discovered(req):
        nonlocal route_discovered
        route_discovered = True

        return c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)

    znp_server.reply_to(
        request=c.ZDO.ExtRouteChk.Req(Dst=device.nwk, partial=True),
        responses=[route_replier],
        override=True,
    )

    was_route_discovered = znp_server.reply_once_to(
        request=c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[set_route_discovered],
    )

    zdo_req = znp_server.reply_once_to(
        request=zdo_request_matcher(
            dst_addr=t.AddrModeAddress(t.AddrMode.NWK, device.nwk),
            command_id=zdo_t.ZDOCmd.Active_EP_req,
            TSN=TSN,
            zdo_NWKAddrOfInterest=device.nwk,
        ),
        responses=[
            c.ZDO.ActiveEpRsp.Callback(
                Src=device.nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=device.nwk,
                ActiveEndpoints=[],
            ),
            c.ZDO.MsgCbIncoming.Callback(
                Src=device.nwk,
                IsBroadcast=t.Bool.false,
                ClusterId=zdo_t.ZDOCmd.Active_EP_rsp,
                SecurityUse=0,
                TSN=TSN,
                MacDst=device.nwk,
                Data=serialize_zdo_command(
                    command_id=zdo_t.ZDOCmd.Active_EP_rsp,
                    Status=t.ZDOStatus.SUCCESS,
                    NWKAddrOfInterest=device.nwk,
                    ActiveEPList=[],
                ),
            ),
        ],
    )

    await device.zdo.Active_EP_req(device.nwk)

    await was_route_discovered
    await zdo_req

    # 6 accounts for the loopback requests
    assert sum(c.value for c in app.state.counters["Retry_NONE"].values()) == 6 + 1

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_route_rediscovery_af(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    # Fail the first time
    route_discovered = False

    def data_confirm_replier(req):
        nonlocal route_discovered

        return c.AF.DataConfirm.Callback(
            Status=t.Status.SUCCESS if route_discovered else t.Status.NWK_NO_ROUTE,
            Endpoint=1,
            TSN=1,
        )

    def set_route_discovered(req):
        nonlocal route_discovered
        route_discovered = True

        return c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)

    was_route_discovered = znp_server.reply_once_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[set_route_discovered],
    )

    znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    # Ignore the source routing request as well
    znp_server.reply_to(
        c.AF.DataRequestSrcRtg.Req(partial=True),
        responses=[
            c.AF.DataRequestSrcRtg.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    await app.request(
        device=device,
        profile=260,
        cluster=1,
        src_ep=1,
        dst_ep=1,
        sequence=1,
        data=b"\x00",
    )

    await was_route_discovered
    assert (
        sum(c.value for c in app.state.counters["Retry_RouteDiscovery"].values()) == 1
    )

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_use_ieee_addr(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    was_ieee_addr_used = False

    def data_confirm_replier(req):
        nonlocal was_ieee_addr_used

        if req.DstAddrModeAddress.mode == t.AddrMode.IEEE:
            status = t.Status.SUCCESS
            was_ieee_addr_used = True
        else:
            status = t.Status.MAC_NO_ACK

        return c.AF.DataConfirm.Callback(Status=status, Endpoint=1, TSN=1)

    znp_server.reply_once_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    # Ignore the source routing request as well
    znp_server.reply_to(
        c.AF.DataRequestSrcRtg.Req(partial=True),
        responses=[
            c.AF.DataRequestSrcRtg.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(Status=t.Status.MAC_NO_ACK, Endpoint=1, TSN=1),
        ],
    )

    await app.request(
        device=device,
        profile=260,
        cluster=1,
        src_ep=1,
        dst_ep=1,
        sequence=1,
        data=b"\x00",
    )

    assert was_ieee_addr_used
    assert sum(c.value for c in app.state.counters["Retry_IEEEAddress"].values()) == 1

    await app.shutdown()


@pytest.mark.parametrize("device_cls", FORMED_DEVICES)
@pytest.mark.parametrize("fw_assoc_remove", [True, False])
@pytest.mark.parametrize("final_status", [t.Status.SUCCESS, t.Status.APS_NO_ACK])
async def test_request_recovery_assoc_remove(
    device_cls, fw_assoc_remove, final_status, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    mocker.patch("zigpy_znp.zigbee.application.REQUEST_ERROR_RETRY_DELAY", new=0)

    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    assoc_device, _ = c.util.Device.deserialize(b"\xFF" * 100)
    assoc_device.shortAddr = device.nwk
    assoc_device.nodeRelation = c.util.NodeRelation.CHILD_FFD_RX_IDLE

    def data_confirm_replier(req):
        bad_assoc = assoc_device

        return c.AF.DataConfirm.Callback(
            Status=t.Status.MAC_TRANSACTION_EXPIRED if bad_assoc else final_status,
            Endpoint=1,
            TSN=1,
        )

    znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    znp_server.reply_to(
        c.AF.DataRequestSrcRtg.Req(partial=True),
        responses=[
            c.AF.DataRequestSrcRtg.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    def assoc_get_with_addr(req):
        nonlocal assoc_device

        if assoc_device is None:
            dev, _ = c.util.Device.deserialize(b"\xFF" * 100)
            return c.UTIL.AssocGetWithAddress.Rsp(Device=dev)

        return c.UTIL.AssocGetWithAddress.Rsp(Device=assoc_device)

    did_assoc_get = znp_server.reply_once_to(
        c.UTIL.AssocGetWithAddress.Req(IEEE=device.ieee, partial=True),
        responses=[assoc_get_with_addr],
    )

    if not issubclass(device_cls, FormedLaunchpadCC26X2R1):
        fw_assoc_remove = False

    # Not all firmwares support Add/Remove
    if fw_assoc_remove:

        def assoc_remove(req):
            nonlocal assoc_device

            if assoc_device is None:
                return c.UTIL.AssocRemove.Rsp(Status=t.Status.FAILURE)

            assoc_device = None
            return c.UTIL.AssocRemove.Rsp(Status=t.Status.SUCCESS)

        did_assoc_remove = znp_server.reply_once_to(
            c.UTIL.AssocRemove.Req(IEEE=device.ieee),
            responses=[assoc_remove],
        )

        did_assoc_add = znp_server.reply_once_to(
            c.UTIL.AssocAdd.Req(
                NWK=device.nwk,
                IEEE=device.ieee,
                NodeRelation=c.util.NodeRelation.CHILD_FFD_RX_IDLE,
            ),
            responses=[c.UTIL.AssocAdd.Rsp(Status=t.Status.SUCCESS)],
        )
    else:
        did_assoc_remove = None
        did_assoc_add = None

    was_route_discovered = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    req = app.request(
        device=device,
        profile=260,
        cluster=1,
        src_ep=1,
        dst_ep=1,
        sequence=1,
        data=b"\x00",
    )

    if fw_assoc_remove and final_status == t.Status.SUCCESS:
        await req
    else:
        with pytest.raises(DeliveryError):
            await req

    if fw_assoc_remove:
        await did_assoc_remove

        if final_status != t.Status.SUCCESS:
            # The association is re-added on failure
            await did_assoc_add
        else:
            assert not did_assoc_add.done()
    elif issubclass(device_cls, FormedLaunchpadCC26X2R1):
        await did_assoc_get
        assert was_route_discovered.call_count >= 1
    else:
        # Don't even attempt this with older firmwares
        assert not did_assoc_get.done()
        assert was_route_discovered.call_count == 0

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize("succeed", [True, False])
@pytest.mark.parametrize("relays", [[0x1111, 0x2222, 0x3333], []])
async def test_request_recovery_manual_source_route(
    device, succeed, relays, make_application, mocker
):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    mocker.patch("zigpy_znp.zigbee.application.REQUEST_ERROR_RETRY_DELAY", new=0)

    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)
    device.relays = relays

    def data_confirm_replier(req):
        if isinstance(req, c.AF.DataRequestExt.Req) or not succeed:
            return c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_NO_ACK,
                Endpoint=1,
                TSN=1,
            )
        else:
            return c.AF.DataConfirm.Callback(
                Status=t.Status.SUCCESS,
                Endpoint=1,
                TSN=1,
            )

    normal_data_request = znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    source_routing_data_request = znp_server.reply_to(
        c.AF.DataRequestSrcRtg.Req(partial=True),
        responses=[
            c.AF.DataRequestSrcRtg.Rsp(Status=t.Status.SUCCESS),
            data_confirm_replier,
        ],
    )

    znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    req = app.request(
        device=device,
        profile=260,
        cluster=1,
        src_ep=1,
        dst_ep=1,
        sequence=1,
        data=b"\x00",
    )

    if succeed:
        await req
    else:
        with pytest.raises(DeliveryError):
            await req

    # In either case only one source routing attempt is performed
    assert source_routing_data_request.call_count == 1
    assert normal_data_request.call_count >= 1

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_route_discovery_concurrency(device, make_application):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    route_discovery1 = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(Dst=0x1234, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    route_discovery2 = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(Dst=0x5678, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    await asyncio.gather(
        app._discover_route(0x1234),
        app._discover_route(0x5678),
        app._discover_route(0x1234),
        app._discover_route(0x5678),
        app._discover_route(0x5678),
        app._discover_route(0x5678),
        app._discover_route(0x1234),
    )

    assert route_discovery1.call_count == 1
    assert route_discovery2.call_count == 1

    await app._discover_route(0x5678)

    assert route_discovery1.call_count == 1
    assert route_discovery2.call_count == 2

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_send_security_and_packet_source_route(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    packet = zigpy_t.ZigbeePacket(
        src=zigpy_t.AddrModeAddress(
            addr_mode=zigpy_t.AddrMode.NWK, address=app.state.node_info.nwk
        ),
        src_ep=0x9A,
        dst=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0xEEFF),
        dst_ep=0xBC,
        tsn=0xDE,
        profile_id=0x1234,
        cluster_id=0x0006,
        data=zigpy_t.SerializableBytes(b"test data"),
        extended_timeout=False,
        tx_options=(
            zigpy_t.TransmitOptions.ACK | zigpy_t.TransmitOptions.APS_Encryption
        ),
        source_route=[0xAABB, 0xCCDD],
    )

    data_req = znp_server.reply_once_to(
        request=c.AF.DataRequestSrcRtg.Req(
            DstAddr=packet.dst.address,
            DstEndpoint=packet.dst_ep,
            # SrcEndpoint=packet.src_ep,
            ClusterId=packet.cluster_id,
            TSN=packet.tsn,
            Data=packet.data.serialize(),
            SourceRoute=packet.source_route,
            partial=True,
        ),
        responses=[
            c.AF.DataRequestSrcRtg.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.SUCCESS,
                Endpoint=packet.dst_ep,
                TSN=packet.tsn,
            ),
        ],
    )

    await app.send_packet(packet)
    req = await data_req
    assert c.af.TransmitOptions.ENABLE_SECURITY in req.Options

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_send_packet_failure(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    packet = zigpy_t.ZigbeePacket(
        src=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0x0000),
        src_ep=0x9A,
        dst=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0xEEFF),
        dst_ep=0xBC,
        tsn=0xDE,
        profile_id=0x1234,
        cluster_id=0x0006,
        data=zigpy_t.SerializableBytes(b"test data"),
    )

    znp_server.reply_to(
        request=c.ZDO.ExtRouteDisc.Req(Dst=packet.dst.address, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    znp_server.reply_to(
        request=c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_NO_ACK,
                Endpoint=packet.dst_ep,
                TSN=packet.tsn,
            ),
        ],
    )

    with pytest.raises(zigpy.exceptions.DeliveryError) as excinfo:
        await app.send_packet(packet)

    assert excinfo.value.status == t.Status.MAC_NO_ACK

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_send_packet_failure_disconnected(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    app._znp = None

    packet = zigpy_t.ZigbeePacket(
        src=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0x0000),
        src_ep=0x9A,
        dst=zigpy_t.AddrModeAddress(addr_mode=zigpy_t.AddrMode.NWK, address=0xEEFF),
        dst_ep=0xBC,
        tsn=0xDE,
        profile_id=0x1234,
        cluster_id=0x0006,
        data=zigpy_t.SerializableBytes(b"test data"),
    )

    with pytest.raises(zigpy.exceptions.DeliveryError) as excinfo:
        await app.send_packet(packet)

    assert "Coordinator is disconnected" in str(excinfo.value)

    await app.shutdown()
