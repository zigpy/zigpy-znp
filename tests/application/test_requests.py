import asyncio

import pytest
import zigpy.types
from zigpy.zdo.types import ZDOCmd, SizePrefixedSimpleDescriptor

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c

from ..conftest import FORMED_DEVICES, CoroutineMock

pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_zdo_request_interception(device, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.startup(auto_form=False)

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)

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

    TSN = 1

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    device.initializing = False

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

    TSN = 1

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    device.initializing = False

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
    with pytest.raises(zigpy.exceptions.DeliveryError):
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

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)
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
async def test_force_remove(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    mocker.patch("zigpy_znp.zigbee.application.ZDO_REQUEST_TIMEOUT", new=0.3)

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    device.initializing = False

    # Reply to zigpy's leave request
    bad_mgmt_leave_req = znp_server.reply_once_to(
        request=c.ZDO.MgmtLeaveReq.Req(DstAddr=device.nwk, partial=True),
        responses=[c.ZDO.MgmtLeaveReq.Rsp(Status=t.Status.FAILURE)],
    )

    # Reply to our own leave request
    good_mgmt_leave_req = znp_server.reply_once_to(
        request=c.ZDO.MgmtLeaveReq.Req(DstAddr=0x0000, partial=True),
        responses=[
            c.ZDO.MgmtLeaveReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtLeaveRsp.Callback(Src=0x000, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    # Make sure the device exists
    assert app.get_device(nwk=device.nwk) is device

    await app.remove(device.ieee)
    await asyncio.gather(bad_mgmt_leave_req, good_mgmt_leave_req)

    # Make sure the device is gone once we remove it
    with pytest.raises(KeyError):
        app.get_device(nwk=device.nwk)

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


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.timeout(10)
async def test_request_concurrency(device, make_application, mocker):
    app, znp_server = make_application(
        server_cls=device, client_config={conf.CONF_MAX_CONCURRENT_REQUESTS: 2}
    )

    await app.startup()

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    # Keep track of how many requests we receive at once
    in_flight_requests = 0

    def make_response(req):
        async def callback(req):
            nonlocal in_flight_requests
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
            for seq in range(20)
        ]
    )

    assert all(status == t.Status.SUCCESS for status, msg in responses)

    await app.shutdown()
