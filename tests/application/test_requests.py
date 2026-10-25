import asyncio

import pytest
import zigpy.endpoint
from zigpy.exceptions import DeliveryError
import zigpy.profiles
import zigpy.types as zigpy_t
import zigpy.zdo.types as zdo_t

import zigpy_znp.commands as c
import zigpy_znp.config as conf
import zigpy_znp.types as t

from ..conftest import (
    FORMED_DEVICES,
    BaseLaunchpadCC26X2R1,
    CoroutineMock,
    FormedLaunchpadCC26X2R1,
    FormedLaunchpadCC26X2R1WithoutAssocCommands,
    serialize_zdo_command,
    zdo_request_matcher,
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
    with pytest.raises(DeliveryError):
        await device.endpoints[1].on_off.on()

    assert app.send_packet.call_count >= 1
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

            if app._concurrent_requests_semaphore.locked(priority=0):
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
                Data=b"\x08" + bytes([req.TSN]) + b"\x0b\x00\x00",
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

    znp_server.reply_to(
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
    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_route_rediscovery_then_assoc_failure(
    device, make_application, mocker
):
    # A NWK_NO_ROUTE failure that consumes the first attempt, followed by a
    # first-time MAC_TRANSACTION_EXPIRED recovery on the final attempt, must surface
    # as a DeliveryError rather than silently reporting a successful send.
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    znp_server.assoc_add_new(
        nwk=device.nwk,
        ieee=device.ieee,
        node_relation=c.util.NodeRelation.CHILD_FFD_RX_IDLE,
    )

    # First attempt fails with NWK_NO_ROUTE, the retried attempt fails with a
    # first-time MAC_TRANSACTION_EXPIRED association failure
    data_confirm_statuses = iter(
        [t.Status.NWK_NO_ROUTE, t.Status.MAC_TRANSACTION_EXPIRED]
    )

    def data_confirm_replier(req):
        return c.AF.DataConfirm.Callback(
            Status=next(data_confirm_statuses),
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

    # The association table responds on its own; just watch the mutations
    did_assoc_remove = mocker.spy(znp_server, "assoc_remove")
    did_assoc_add = mocker.spy(znp_server, "assoc_add_new")

    was_route_discovered = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    with pytest.raises(DeliveryError):
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    # Route discovery runs once for the first-attempt NWK_NO_ROUTE and once during
    # the final-attempt MAC_TRANSACTION_EXPIRED recovery
    assert was_route_discovered.call_count == 2
    # The association is removed exactly once during recovery and, since the send
    # ultimately fails, must be re-added exactly once
    assert len(did_assoc_remove.mock_calls) == 1
    assert len(did_assoc_add.mock_calls) == 1

    await app.shutdown()


@pytest.mark.parametrize(
    "device_cls", FORMED_DEVICES + [FormedLaunchpadCC26X2R1WithoutAssocCommands]
)
@pytest.mark.parametrize("final_status", [t.Status.SUCCESS, t.Status.APS_NO_ACK])
async def test_request_recovery_assoc_remove(
    device_cls, final_status, make_application, mocker
):
    # Only the newer Z-Stack 3 firmware builds expose the custom AssocAdd/AssocRemove
    # commands that back the child-association recovery flow
    is_launchpad = issubclass(device_cls, BaseLaunchpadCC26X2R1)
    fw_assoc_remove = issubclass(device_cls, FormedLaunchpadCC26X2R1)

    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)

    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    znp_server.assoc_add_new(
        nwk=device.nwk,
        ieee=device.ieee,
        node_relation=c.util.NodeRelation.CHILD_FFD_RX_IDLE,
    )

    # The association table responds on its own; just watch the mutations
    did_assoc_get = mocker.spy(znp_server, "assoc_get")
    did_assoc_remove = mocker.spy(znp_server, "assoc_remove")
    did_assoc_add = mocker.spy(znp_server, "assoc_add_new")

    def data_confirm_replier(req):
        # The child stops expiring transactions once its association is dropped
        bad_assoc = len(did_assoc_remove.mock_calls) == 0

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
        assert len(did_assoc_remove.mock_calls) >= 1

        if final_status != t.Status.SUCCESS:
            # The association is re-added on failure
            assert len(did_assoc_add.mock_calls) >= 1
        else:
            assert len(did_assoc_add.mock_calls) == 0
    elif is_launchpad:
        assert len(did_assoc_get.mock_calls) >= 1
    else:
        # Don't even attempt this with older firmwares
        assert len(did_assoc_get.mock_calls) == 0
        assert was_route_discovered.call_count == 0

    await app.shutdown()


def absent_lookup_with_address_0xfffe(znp_server, relation=c.util.NodeRelation.PARENT):
    # Real miss: 0xFFFE, then zeros on Koenkk's builds (`PARENT`) or garbage on stock
    # Z-Stack, which may read as a child
    def lookup(req):
        device = znp_server.assoc_get(ieee=req.IEEE, nwk=req.NWK)

        if device is None:
            device, _ = c.util.Device.deserialize(b"\x00" * 100)
            device.shortAddr = t.NWK(0xFFFE)
            device.nodeRelation = relation

        return c.UTIL.AssocGetWithAddress.Rsp(Device=device)

    znp_server.reply_to(
        c.UTIL.AssocGetWithAddress.Req(partial=True), responses=[lookup], override=True
    )


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize(
    ("relation", "absent_relation", "retried"),
    [
        # Miss as `NOTUSED` (model default): send ends at once
        (None, None, False),
        (None, c.util.NodeRelation.PARENT, True),
        (None, c.util.NodeRelation.CHILD_RFD, True),
        # Found, not a direct child
        (c.util.NodeRelation.PARENT, None, True),
        (c.util.NodeRelation.NEIGHBOR, None, True),
        (c.util.NodeRelation.OTHER, None, True),
    ],
)
async def test_request_recovery_assoc_not_a_child(
    device_cls, relation, absent_relation, retried, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    if relation is not None:
        znp_server.assoc_add_new(
            nwk=device.nwk, ieee=device.ieee, node_relation=relation
        )

    if absent_relation is not None:
        absent_lookup_with_address_0xfffe(znp_server, absent_relation)

    did_assoc_remove = mocker.spy(znp_server, "assoc_remove")
    did_assoc_add = mocker.spy(znp_server, "assoc_add_new")

    data_req = znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_TRANSACTION_EXPIRED, Endpoint=1, TSN=1
            ),
        ],
    )

    was_route_discovered = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(Dst=device.nwk, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    with pytest.raises(DeliveryError):
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    # Table untouched, route rediscovered, send retried
    assert data_req.call_count == (2 if retried else 1)
    assert was_route_discovered.call_count == (1 if retried else 0)
    assert did_assoc_remove.call_count == 0
    assert did_assoc_add.call_count == 0

    await app.shutdown()


RFD = c.util.NodeRelation.CHILD_RFD


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_assoc_other_address(
    device_cls, make_application, mocker
):
    # The firmware holds the device as a child at an address other than device.nwk:
    # dropping it cannot help, and the entry must survive
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)
    entry = znp_server.assoc_add_new(nwk=0x1234, ieee=device.ieee, node_relation=RFD)

    did_assoc_remove = mocker.spy(znp_server, "assoc_remove")
    did_assoc_add = mocker.spy(znp_server, "assoc_add_new")

    data_req = znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_TRANSACTION_EXPIRED, Endpoint=1, TSN=1
            ),
        ],
    )

    was_route_discovered = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(Dst=device.nwk, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    with pytest.raises(DeliveryError):
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    assert data_req.call_count == 2
    assert was_route_discovered.call_count == 1
    assert did_assoc_remove.call_count == 0
    assert did_assoc_add.call_count == 0
    assert znp_server.assoc_get(ieee=device.ieee) is entry

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize(
    ("scenario", "relation", "restored"),
    [
        # Each child relation: removed, restored as it was
        ("unchanged", c.util.NodeRelation.CHILD_RFD, True),
        ("unchanged", c.util.NodeRelation.CHILD_RFD_RX_IDLE, True),
        ("unchanged", c.util.NodeRelation.CHILD_FFD, True),
        ("unchanged", c.util.NodeRelation.CHILD_FFD_RX_IDLE, True),
        ("koenkk_lookup", RFD, True),
        # Host knows a new address: no restore
        ("rejoin_during_retry", RFD, False),
        ("rejoin_during_restore_lookup", RFD, False),
        # Firmware has the device again: no overwrite
        ("re_associated", RFD, False),
        ("re_associated_new_nwk", RFD, False),
    ],
)
async def test_request_recovery_assoc_restore(
    device_cls, scenario, relation, restored, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    # Rejoin only updates the device, no interview
    mocker.patch.object(device, "schedule_initialize")

    assoc_add_new = znp_server.assoc_add_new
    assoc_add_new(nwk=device.nwk, ieee=device.ieee, node_relation=relation)

    if scenario == "koenkk_lookup":
        absent_lookup_with_address_0xfffe(znp_server)

    assoc_get = znp_server.assoc_get

    def rejoin_on_restore_lookup(**kwargs):
        # Only the restore looks up after the removal
        entry = assoc_get(**kwargs)

        if entry is None and scenario == "rejoin_during_restore_lookup":
            app.handle_join(nwk=0x1234, ieee=device.ieee, parent_nwk=0x5678)

        return entry

    mocker.patch.object(znp_server, "assoc_get", side_effect=rejoin_on_restore_lookup)
    did_assoc_remove = mocker.spy(znp_server, "assoc_remove")
    did_assoc_add = mocker.spy(znp_server, "assoc_add_new")

    attempts = 0

    def data_confirm_replier(req):
        nonlocal attempts
        attempts += 1

        # Attempt 1 expires (recovery), retry: no route
        if attempts == 2:
            if scenario == "rejoin_during_retry":
                app.handle_join(nwk=0x1234, ieee=device.ieee, parent_nwk=0x5678)
            elif scenario.startswith("re_associated"):
                nwk = 0x1234 if scenario.endswith("new_nwk") else device.nwk
                assoc_add_new(nwk=nwk, ieee=device.ieee, node_relation=relation)

        return c.AF.DataConfirm.Callback(
            Status=(
                t.Status.MAC_TRANSACTION_EXPIRED
                if attempts == 1
                else t.Status.NWK_NO_ROUTE
            ),
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
        c.ZDO.ExtRouteDisc.Req(partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    with pytest.raises(DeliveryError):
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    assert did_assoc_remove.call_count == 1

    if restored:
        did_assoc_add.assert_called_once_with(
            nwk=0xABCD, ieee=device.ieee, node_relation=relation
        )
    else:
        did_assoc_add.assert_not_called()

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
        source_route=[zigpy_t.NWK(0xAABB), zigpy_t.NWK(0xCCDD)],
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
