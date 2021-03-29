import asyncio

import pytest
import zigpy.zdo
from zigpy.zdo.types import ZDOCmd, SizePrefixedSimpleDescriptor
from zigpy.exceptions import DeliveryError

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.exceptions import InvalidCommandResponse

from ..conftest import FORMED_DEVICES, CoroutineMock, FormedLaunchpadCC26X2R1

pytestmark = [pytest.mark.asyncio]


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_zdo_request_interception(device, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)

    # Send back a request response
    active_ep_req = znp_server.reply_once_to(
        request=c.ZDO.SimpleDescReq.Req(
            DstAddr=device.nwk, NWKAddrOfInterest=device.nwk, Endpoint=1
        ),
        responses=[
            c.ZDO.SimpleDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.SimpleDescRsp.Callback(
                Src=device.nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=device.nwk,
                SimpleDescriptor=SizePrefixedSimpleDescriptor(
                    *dict(
                        endpoint=1,
                        profile=49246,
                        device_type=256,
                        device_version=2,
                        input_clusters=[0, 3, 4, 5, 6, 8, 2821, 4096],
                        output_clusters=[5, 25, 32, 4096],
                    ).values()
                ),
            ),
        ],
    )

    status, message = await app.request(
        device=device,
        profile=260,
        cluster=ZDOCmd.Simple_Desc_req,
        src_ep=0,
        dst_ep=0,
        sequence=1,
        data=b"\x01\x9e\xfa\x01",
        use_ieee=False,
    )

    assert status == t.Status.SUCCESS
    await active_ep_req

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_zigpy_request(device, make_application):
    app, znp_server = make_application(device)
    await app.startup(auto_form=False)

    TSN = 2

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    ep = device.add_endpoint(1)
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

    TSN = 2

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

    mocker.spy(app, "_send_request")

    # Fail to turn on the light
    with pytest.raises(InvalidCommandResponse):
        await device.endpoints[1].on_off.on()

    assert app._send_request.call_count == 1
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

    mocker.patch.object(app, "_send_request", new=CoroutineMock())

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

    assert app._send_request.call_count == 1
    assert app._send_request.mock_calls[0][2]["dst_addr"] == addr

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.parametrize("status", [t.ZDOStatus.SUCCESS, t.ZDOStatus.TIMEOUT, None])
async def test_remove(device, make_application, status, mocker):
    app, znp_server = make_application(server_cls=device)
    app._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 0.1

    # Only zigpy>=0.29.0 has this method
    if hasattr(app, "_remove_device"):
        mocker.spy(app, "_remove_device")

    await app.startup(auto_form=False)
    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    responses = [c.ZDO.MgmtLeaveReq.Rsp(Status=t.Status.SUCCESS)]

    if status is not None:
        responses.append(c.ZDO.MgmtLeaveRsp.Callback(Src=0x0000, Status=status))

    # Normal ZDO leave must fail
    normal_remove_req = znp_server.reply_once_to(
        request=c.ZDO.MgmtLeaveReq.Req(
            DstAddr=device.nwk, IEEE=device.ieee, partial=True
        ),
        responses=[
            c.ZDO.MgmtLeaveReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtLeaveRsp.Callback(Src=device.nwk, Status=t.ZDOStatus.TIMEOUT),
        ],
    )

    # Make sure the device exists
    assert app.get_device(nwk=device.nwk) is device

    await app.remove(device.ieee)
    await normal_remove_req

    if hasattr(app, "_remove_device"):
        # Make sure the device is going to be removed
        assert app._remove_device.call_count == 1
    else:
        # Make sure the device is gone
        with pytest.raises(KeyError):
            app.get_device(ieee=device.ieee)

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_mrequest(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    mocker.patch.object(app, "_send_request", new=CoroutineMock())
    group = app.groups.add_group(0x1234, "test group")

    await group.endpoint.on_off.on()

    assert app._send_request.call_count == 1
    assert app._send_request.mock_calls[0][2]["dst_addr"] == t.AddrModeAddress(
        mode=t.AddrMode.Group, address=0x1234
    )
    assert app._send_request.mock_calls[0][2]["data"] == b"\x01\x01\x01"

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_mrequest_doesnt_block(device, make_application, event_loop):
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

    request_sent = event_loop.create_future()
    request_sent.add_done_callback(lambda _: znp_server.send(data_confirm_rsp))

    await app.startup(auto_form=False)

    group = app.groups.add_group(0x1234, "test group")
    await group.endpoint.on_off.on()
    request_sent.set_result(True)

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_unimplemented_zdo_converter(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    await app.startup()

    with pytest.raises(RuntimeError):
        await zigpy.zdo.broadcast(
            app,
            ZDOCmd.Remove_node_cache_req,
            0x0000,
            0x00,
            t.NWK(0x1234),
            t.EUI64.convert("11:22:33:44:55:66:77:88"),
            broadcast_address=0xFFFC,
        )

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
    )

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_concurrency(device, make_application, mocker):
    app, znp_server = make_application(
        server_cls=device,
        client_config={"znp_config": {conf.CONF_MAX_CONCURRENT_REQUESTS: 2}},
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
    responses = await asyncio.gather(
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

    assert all(status == t.Status.SUCCESS for status, msg in responses)
    assert in_flight_requests == 0
    assert did_lock

    await app.shutdown()


"""
@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_request_concurrency_overflow(device, make_application, mocker):
    mocker.patch("zigpy_znp.zigbee.application.MAX_WAITING_REQUESTS", new=1)

    app, znp_server = make_application(
        server_cls=device, client_config={
            'znp_config': {conf.CONF_MAX_CONCURRENT_REQUESTS: 1}
        }
    )

    await app.startup()

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    def make_response(req):
        async def callback(req):
            await asyncio.sleep(0.01 * req.TSN)

            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS, Endpoint=1, TSN=req.TSN
                )
            )

        asyncio.create_task(callback(req))

    znp_server.reply_to(
        request=c.AF.DataRequestExt.Req(partial=True), responses=[make_response]
    )

    # We can only handle 1 in-flight request and 1 enqueued request. Last one will fail.
    responses = await asyncio.gather(
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
            for seq in range(3)
        ], return_exceptions=True)

    (rsp1, stat1), (rsp2, stat2), error3 = responses

    assert rsp1 == rsp2 == t.Status.SUCCESS
    assert isinstance(error3, ValueError)

    await app.shutdown()
"""


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_nonstandard_profile(device, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)
    device.node_desc, _ = device.node_desc.deserialize(bytes(14))

    ep = device.add_endpoint(2)
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
async def test_request_cancellation_shielding(
    device, make_application, mocker, event_loop
):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.spy(app._znp, "_unhandled_command")
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)

    delayed_reply_sent = event_loop.create_future()

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
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    # The data confirm timeout must be shorter than the ARSP timeout
    mocker.patch("zigpy_znp.zigbee.application.DATA_CONFIRM_TIMEOUT", new=0.1)
    app._znp._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT] = 1

    device = app.add_initialized_device(ieee=t.EUI64(range(8)), nwk=0xABCD)
    device.node_desc, _ = device.node_desc.deserialize(bytes(14))

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
        c.ZDO.ExtRouteChk.Req(Dst=device.nwk, partial=True),
        responses=[route_replier],
        override=True,
    )

    was_route_discovered = znp_server.reply_once_to(
        c.ZDO.ExtRouteDisc.Req(
            Dst=device.nwk, Options=c.zdo.RouteDiscoveryOptions.UNICAST, partial=True
        ),
        responses=[set_route_discovered],
    )

    zdo_req = znp_server.reply_once_to(
        c.ZDO.ActiveEpReq.Req(DstAddr=device.nwk, NWKAddrOfInterest=device.nwk),
        responses=[
            c.ZDO.ActiveEpReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.ActiveEpRsp.Callback(
                Src=device.nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=device.nwk,
                ActiveEndpoints=[],
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
    device.node_desc, _ = device.node_desc.deserialize(bytes(14))

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
    device.node_desc, _ = device.node_desc.deserialize(bytes(14))

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
            return c.Util.AssocGetWithAddress.Rsp(Device=dev)

        return c.Util.AssocGetWithAddress.Rsp(Device=assoc_device)

    did_assoc_get = znp_server.reply_once_to(
        c.Util.AssocGetWithAddress.Req(IEEE=device.ieee, partial=True),
        responses=[assoc_get_with_addr],
    )

    if not issubclass(device_cls, FormedLaunchpadCC26X2R1):
        fw_assoc_remove = False

    # Not all firmwares support Add/Remove
    if fw_assoc_remove:

        def assoc_remove(req):
            nonlocal assoc_device

            if assoc_device is None:
                return c.Util.AssocRemove.Rsp(Status=t.Status.FAILURE)

            assoc_device = None
            return c.Util.AssocRemove.Rsp(Status=t.Status.SUCCESS)

        did_assoc_remove = znp_server.reply_once_to(
            c.Util.AssocRemove.Req(IEEE=device.ieee),
            responses=[assoc_remove],
        )

        did_assoc_add = znp_server.reply_once_to(
            c.Util.AssocAdd.Req(
                NWK=device.nwk,
                IEEE=device.ieee,
                NodeRelation=c.util.NodeRelation.CHILD_FFD_RX_IDLE,
            ),
            responses=[c.Util.AssocAdd.Rsp(Status=t.Status.SUCCESS)],
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
    device.node_desc, _ = device.node_desc.deserialize(bytes(14))

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
