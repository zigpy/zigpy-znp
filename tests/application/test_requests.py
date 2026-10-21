import asyncio

import pytest
import zigpy.endpoint
from zigpy.exceptions import DeliveryError
import zigpy.profiles
import zigpy.types as zigpy_t
import zigpy.zdo.types as zdo_t

import zigpy_znp.commands as c
import zigpy_znp.config as conf
from zigpy_znp.exceptions import CommandNotRecognized
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


def assoc_lookup_rsp(fill: bytes, nwk: int, relation: c.util.NodeRelation):
    """Build a `UTIL.AssocGetWithAddress` answer, with `fill` in the other fields."""
    assoc_device, _ = c.util.Device.deserialize(fill * 100)
    assoc_device.shortAddr = t.NWK(nwk)
    assoc_device.nodeRelation = relation

    return c.UTIL.AssocGetWithAddress.Rsp(Device=assoc_device)


ASSOC_NOT_FOUND_ZEROED = assoc_lookup_rsp(b"\x00", 0xFFFE, c.util.NodeRelation.PARENT)
ASSOC_NOT_FOUND_NOTUSED = assoc_lookup_rsp(b"\xff", 0xFFFF, c.util.NodeRelation.NOTUSED)


class AssocTable:
    """
    Association table of a simulated coordinator. It applies `UTIL.AssocRemove` and
    `UTIL.AssocAdd`, answers lookups for absent devices with `not_found` (Koenkk's
    builds: `0xFFFE`, then zeroes) and logs every request in order. `on_remove` runs
    right after a removal, `on_lookup` once a lookup's answer is built but before
    the host receives it.
    """

    def __init__(self, znp_server, entries, *, not_found=None, assoc_add=True):
        self.entries = dict(entries)
        self.not_found = not_found or ASSOC_NOT_FOUND_ZEROED
        self.assoc_add = assoc_add
        self.on_remove = None
        self.on_lookup = None
        self.log = []

        znp_server.reply_to(
            c.UTIL.AssocGetWithAddress.Req(partial=True), responses=[self.get]
        )
        znp_server.reply_to(
            c.UTIL.AssocRemove.Req(partial=True), responses=[self.remove]
        )
        znp_server.reply_to(c.UTIL.AssocAdd.Req(partial=True), responses=[self.add])

    def get(self, req):
        self.log.append(("AssocGetWithAddress", req.IEEE))

        if req.IEEE not in self.entries:
            rsp = self.not_found
        else:
            rsp = assoc_lookup_rsp(b"\x00", *self.entries[req.IEEE])

        if self.on_lookup is not None:
            self.on_lookup()

        return rsp

    def remove(self, req):
        self.log.append(("AssocRemove", req.IEEE))
        self.entries.pop(req.IEEE, None)

        if self.on_remove is not None:
            self.on_remove()

        return c.UTIL.AssocRemove.Rsp(Status=t.Status.SUCCESS)

    def add(self, req):
        self.log.append(("AssocAdd", req.IEEE, req.NWK, req.NodeRelation))

        # Koenkk's builds 20200805 and 20200925 have `AssocRemove`, not `AssocAdd`
        if not self.assoc_add:
            return c.RPCError.CommandNotRecognized.Rsp(
                ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId,
                RequestHeader=req.to_frame().header,
            )

        self.entries[req.IEEE] = (req.NWK, req.NodeRelation)

        return c.UTIL.AssocAdd.Rsp(Status=t.Status.SUCCESS)


async def request_with_failed_recovery(
    app,
    znp_server,
    device,
    during_retry=None,
    statuses=(t.Status.MAC_TRANSACTION_EXPIRED, t.Status.NWK_NO_ROUTE),
):
    """
    Send a request whose two attempts fail with `statuses`. By default the first
    one expires, starting the association recovery, and the retry finds no route.
    `during_retry` runs while the second attempt is in flight.
    """

    attempts = 0

    async def data_request(req):
        nonlocal attempts
        attempts += 1

        yield c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS)

        if attempts == 2 and during_retry is not None:
            during_retry()

        yield c.AF.DataConfirm.Callback(
            Status=statuses[attempts - 1], Endpoint=1, TSN=1
        )

    znp_server.reply_to(c.AF.DataRequestExt.Req(partial=True), responses=[data_request])
    znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
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


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize(
    ("lookup_rsp", "retried"),
    [
        # Not found: Z-Stack returns `INVALID_NODE_ADDR`. Koenkk's firmware zeroes
        # the remainder, which reads as `PARENT`. Stock firmware leaves it
        # uninitialized, so it may even contain a child relation.
        pytest.param(
            assoc_lookup_rsp(b"\x00", 0xFFFE, c.util.NodeRelation.PARENT),
            True,
            id="not_found_zeroed",
        ),
        pytest.param(
            assoc_lookup_rsp(b"\xa5", 0xFFFE, c.util.NodeRelation.CHILD_RFD),
            True,
            id="not_found_garbage",
        ),
        # Found, but not a direct child of the coordinator
        pytest.param(
            assoc_lookup_rsp(b"\x00", 0xABCD, c.util.NodeRelation.PARENT),
            True,
            id="parent",
        ),
        pytest.param(
            assoc_lookup_rsp(b"\x00", 0xABCD, c.util.NodeRelation.NEIGHBOR),
            True,
            id="neighbor",
        ),
        pytest.param(
            assoc_lookup_rsp(b"\x00", 0xABCD, c.util.NodeRelation.OTHER),
            True,
            id="other",
        ),
        # Unchanged: `NOTUSED` ends the send at once
        pytest.param(
            assoc_lookup_rsp(b"\xff", 0xABCD, c.util.NodeRelation.NOTUSED),
            False,
            id="notused",
        ),
    ],
)
async def test_request_recovery_assoc_not_a_child(
    device_cls, lookup_rsp, retried, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    data_req = znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_TRANSACTION_EXPIRED, Endpoint=1, TSN=1
            ),
        ],
    )

    did_assoc_get = znp_server.reply_to(
        c.UTIL.AssocGetWithAddress.Req(IEEE=device.ieee, partial=True),
        responses=[lookup_rsp],
    )

    # Match any arguments: neither command may be sent at all
    did_assoc_remove = znp_server.reply_to(
        c.UTIL.AssocRemove.Req(partial=True),
        responses=[c.UTIL.AssocRemove.Rsp(Status=t.Status.SUCCESS)],
    )

    did_assoc_add = znp_server.reply_to(
        c.UTIL.AssocAdd.Req(partial=True),
        responses=[c.UTIL.AssocAdd.Rsp(Status=t.Status.SUCCESS)],
    )

    was_route_discovered = znp_server.reply_to(
        c.ZDO.ExtRouteDisc.Req(Dst=device.nwk, partial=True),
        responses=[c.ZDO.ExtRouteDisc.Rsp(Status=t.Status.SUCCESS)],
    )

    with pytest.raises(DeliveryError) as exc_info:
        await app.request(
            device=device,
            profile=260,
            cluster=1,
            src_ep=1,
            dst_ep=1,
            sequence=1,
            data=b"\x00",
        )

    # The association table is left alone. Other than `NOTUSED`, the route is
    # rediscovered and the send retried once, as before, then the error propagates.
    assert exc_info.value.status == t.Status.MAC_TRANSACTION_EXPIRED
    assert data_req.call_count == (2 if retried else 1)
    assert did_assoc_get.call_count == 1
    assert did_assoc_remove.call_count == 0
    assert did_assoc_add.call_count == 0
    assert was_route_discovered.call_count == (1 if retried else 0)

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize(
    "relation",
    [
        c.util.NodeRelation.CHILD_RFD,
        c.util.NodeRelation.CHILD_RFD_RX_IDLE,
        c.util.NodeRelation.CHILD_FFD,
        c.util.NodeRelation.CHILD_FFD_RX_IDLE,
    ],
)
async def test_request_recovery_assoc_remove_child_relations(
    device_cls, relation, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    data_req = znp_server.reply_to(
        c.AF.DataRequestExt.Req(partial=True),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(
                Status=t.Status.MAC_TRANSACTION_EXPIRED, Endpoint=1, TSN=1
            ),
        ],
    )

    table = AssocTable(znp_server, {device.ieee: (device.nwk, relation)})

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

    # Every child relation is still removed, retried once and restored as it was
    assert data_req.call_count == 2
    assert was_route_discovered.call_count == 1
    assert table.log == [
        ("AssocGetWithAddress", device.ieee),
        ("AssocRemove", device.ieee),
        ("AssocGetWithAddress", device.ieee),
        ("AssocAdd", device.ieee, device.nwk, relation),
    ]

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize("rejoin", ["never", "during_retry", "during_restore_lookup"])
async def test_request_recovery_assoc_restore_after_rejoin(
    device_cls, rejoin, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    # A rejoin only updates the device here, it does not start a new interview
    mocker.patch.object(device, "schedule_initialize")

    table = AssocTable(
        znp_server, {device.ieee: (0xABCD, c.util.NodeRelation.CHILD_RFD)}
    )

    def rejoin_if(when):
        if rejoin == when:
            # The device rejoins through a router under a new address. The host learns
            # it from `ZDO.TCDevInd` or the announcement, both end in `handle_join`.
            # The coordinator's table does not list it.
            app.handle_join(nwk=0x1234, ieee=device.ieee, parent_nwk=0x5678)

    def on_lookup():
        # Only the restore looks the device up after its removal
        if ("AssocRemove", device.ieee) in table.log:
            rejoin_if("during_restore_lookup")

    table.on_lookup = on_lookup

    with pytest.raises(DeliveryError) as exc_info:
        await request_with_failed_recovery(
            app, znp_server, device, lambda: rejoin_if("during_retry")
        )

    assert exc_info.value.status == t.Status.NWK_NO_ROUTE

    removal = [
        ("AssocGetWithAddress", device.ieee),
        ("AssocRemove", device.ieee),
    ]
    restore_lookup = ("AssocGetWithAddress", device.ieee)

    if rejoin == "never":
        assert device.nwk == 0xABCD
        assert table.log == removal + [
            restore_lookup,
            ("AssocAdd", device.ieee, 0xABCD, c.util.NodeRelation.CHILD_RFD),
        ]
    elif rejoin == "during_retry":
        # The old address is not written back over the one the host now knows
        assert device.nwk == 0x1234
        assert table.log == removal
    else:
        # The address is checked again once the restore's lookup has returned
        assert device.nwk == 0x1234
        assert table.log == removal + [restore_lookup]

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_assoc_restore_trace_1730(
    device_cls, make_application, mocker
):
    # Order of a production log (2026-10-20 17:30, Koenkk's build 20250321): the
    # recovery runs on the final attempt, the device announces itself under its old
    # address and leaves while the route is rediscovered, the restore follows, and
    # the device rejoins under a new address five seconds later.
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)
    mocker.patch.object(device, "schedule_initialize")
    mocker.patch.object(device, "schedule_group_membership_scan")

    table = AssocTable(
        znp_server, {device.ieee: (0xABCD, c.util.NodeRelation.CHILD_RFD)}
    )

    def announce_and_leave():
        # Whether Z-Stack re-adds the entry at the announcement or drops it at the
        # leave is not measured; the table keeps it removed
        app.handle_join(nwk=0xABCD, ieee=device.ieee, parent_nwk=None)
        app.handle_leave(nwk=0xABCD, ieee=device.ieee)

    table.on_remove = announce_and_leave

    with pytest.raises(DeliveryError) as exc_info:
        await request_with_failed_recovery(
            app,
            znp_server,
            device,
            statuses=(t.Status.NWK_NO_ROUTE, t.Status.MAC_TRANSACTION_EXPIRED),
        )

    assert exc_info.value.status == t.Status.MAC_TRANSACTION_EXPIRED

    app.handle_join(nwk=0x1234, ieee=device.ieee, parent_nwk=0x0000)
    assert device.nwk == 0x1234

    # The new address arrives after the restore, so neither guard can apply
    assert table.log == [
        ("AssocGetWithAddress", device.ieee),
        ("AssocRemove", device.ieee),
        ("AssocGetWithAddress", device.ieee),
        ("AssocAdd", device.ieee, 0xABCD, c.util.NodeRelation.CHILD_RFD),
    ]

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
@pytest.mark.parametrize(
    ("entry_at_restore", "not_found", "restored"),
    [
        # Absent: the device is still removed, so it is restored as it was
        pytest.param(None, ASSOC_NOT_FOUND_ZEROED, True, id="absent_zeroed"),
        pytest.param(None, ASSOC_NOT_FOUND_NOTUSED, True, id="absent_notused"),
        # Present: Z-Stack re-associated the device before the host heard of it.
        # `UTIL.AssocAdd` would overwrite this entry in place.
        pytest.param(
            (0xABCD, c.util.NodeRelation.CHILD_RFD), None, False, id="present"
        ),
        pytest.param(
            (0x1234, c.util.NodeRelation.CHILD_RFD), None, False, id="present_new_nwk"
        ),
        pytest.param(
            (0xABCD, c.util.NodeRelation.NEIGHBOR), None, False, id="present_neighbor"
        ),
    ],
)
async def test_request_recovery_assoc_restore_lookup(
    device_cls, entry_at_restore, not_found, restored, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    table = AssocTable(
        znp_server,
        {device.ieee: (0xABCD, c.util.NodeRelation.CHILD_RFD)},
        not_found=not_found,
    )

    def during_retry():
        if entry_at_restore is not None:
            table.entries[device.ieee] = entry_at_restore

    with pytest.raises(DeliveryError):
        await request_with_failed_recovery(app, znp_server, device, during_retry)

    expected = [
        ("AssocGetWithAddress", device.ieee),
        ("AssocRemove", device.ieee),
        ("AssocGetWithAddress", device.ieee),
    ]

    if restored:
        expected.append(
            ("AssocAdd", device.ieee, 0xABCD, c.util.NodeRelation.CHILD_RFD)
        )

    assert table.log == expected

    await app.shutdown()


@pytest.mark.parametrize("device_cls", [FormedLaunchpadCC26X2R1])
async def test_request_recovery_assoc_add_unsupported(
    device_cls, make_application, mocker
):
    app, znp_server = make_application(server_cls=device_cls)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    table = AssocTable(
        znp_server,
        {device.ieee: (0xABCD, c.util.NodeRelation.CHILD_RFD)},
        assoc_add=False,
    )

    # Unchanged behaviour: the failed restore replaces the `DeliveryError`
    with pytest.raises(CommandNotRecognized) as exc_info:
        await request_with_failed_recovery(app, znp_server, device)

    assert isinstance(exc_info.value.__context__, DeliveryError)
    assert exc_info.value.__context__.status == t.Status.NWK_NO_ROUTE
    assert table.log == [
        ("AssocGetWithAddress", device.ieee),
        ("AssocRemove", device.ieee),
        ("AssocGetWithAddress", device.ieee),
        ("AssocAdd", device.ieee, 0xABCD, c.util.NodeRelation.CHILD_RFD),
    ]

    # The device stays removed
    assert device.ieee not in table.entries

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
