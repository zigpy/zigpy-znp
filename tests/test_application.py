import asyncio
import logging

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
import zigpy_znp.config as conf

from zigpy.zdo.types import ZDOCmd

from zigpy_znp.uart import ZnpMtProtocol

from zigpy_znp.api import ZNP
from zigpy_znp.uart import connect as uart_connect
from zigpy_znp.zigbee.application import ControllerApplication


from test_api import (  # noqa: F401
    pytest_mark_asyncio_timeout,
    config_for_port_path,
    pingable_serial_port,
)

LOGGER = logging.getLogger(__name__)


class ForwardingTransport:
    class serial:
        name = "/dev/passthrough"
        baudrate = 45678

    def __init__(self, protocol):
        self.protocol = protocol

    def write(self, data):
        LOGGER.debug("Sending data %s to %s via %s", data, self.protocol, self)
        self.protocol.data_received(data)

    def close(self, exc=None):
        self.protocol.connection_lost(exc)

    def __repr__(self):
        return f"<{type(self).__name__} for {self.protocol}>"


class ServerZNP(ZNP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We just respond to pings, nothing more
        self.callback_for_response(
            c.SysCommands.Ping.Req(), lambda r: self.ping_replier(r)
        )

    def reply_once_to(self, request, responses):
        called_future = asyncio.get_running_loop().create_future()

        async def callback():
            if callback.called:
                return

            callback.called = True

            for response in responses:
                await asyncio.sleep(0.1)
                self.send(response)

            called_future.set_result(True)

        callback.called = False
        self.callback_for_response(request, lambda _: asyncio.create_task(callback()))

        return called_future

    def reply_to(self, request, responses):
        async def callback():
            for response in responses:
                await asyncio.sleep(0.1)
                self.send(response)

        self.callback_for_response(request, lambda _: asyncio.create_task(callback()))

    def ping_replier(self, request):
        # XXX: what in the world is this received MTCapabilities value?
        # It does not match up at all to the TI codebase
        self.send(c.SysCommands.Ping.Rsp(Capabilities=t.MTCapabilities(1625)))

    def send(self, response):
        self._uart.send(response.to_frame())


@pytest.fixture
async def znp_server(mocker):
    device = "/dev/ttyFAKE0"
    config = config_for_port_path(device)

    server_znp = ServerZNP(config)
    server_znp._uart = ZnpMtProtocol(server_znp)

    def passthrough_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        fut = loop.create_future()
        assert url == device

        client_protocol = protocol_factory()

        # Client writes go to the server
        client_transport = ForwardingTransport(server_znp._uart)

        # Server writes go to the client
        server_transport = ForwardingTransport(client_protocol)

        # Once both are setup, notify each one of their transport
        server_znp._uart.connection_made(server_transport)
        client_protocol.connection_made(client_transport)

        fut.set_result((client_transport, client_protocol))

        return fut

    mocker.patch("serial_asyncio.create_serial_connection", new=passthrough_serial_conn)

    return server_znp


@pytest.fixture
def application(znp_server):
    app = ControllerApplication(config_for_port_path("/dev/ttyFAKE0"))

    # Handle the entire startup sequence
    znp_server.reply_to(
        request=c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft),
        responses=[
            c.SysCommands.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=2,
                ProductId=1,
                MajorRel=2,
                MinorRel=7,
                MaintRel=1,
            )
        ],
    )

    znp_server.reply_to(
        request=c.ZDOCommands.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
        responses=[
            c.ZDOCommands.ActiveEpReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.ActiveEpRsp.Callback(
                Src=0x0000, Status=t.ZDOStatus.SUCCESS, NWK=0x0000, ActiveEndpoints=[]
            ),
        ],
    )

    znp_server.reply_to(
        request=c.AFCommands.Register.Req(partial=True),
        responses=[c.AFCommands.Register.Rsp(Status=t.Status.Success)],
    )

    znp_server.reply_to(
        request=c.APPConfigCommands.BDBStartCommissioning.Req(
            Mode=c.app_config.BDBCommissioningMode.NetworkFormation
        ),
        responses=[
            c.APPConfigCommands.BDBStartCommissioning.Rsp(Status=t.Status.Success),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.Success,
                Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                RemainingModes=c.app_config.BDBRemainingCommissioningModes.NONE,
            ),
            c.APPConfigCommands.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.NoNetwork,
                Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                RemainingModes=c.app_config.BDBRemainingCommissioningModes.NONE,
            ),
        ],
    )

    return app, znp_server


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup(application):
    app, znp_server = application

    num_endpoints = 5
    endpoints = []

    def register_endpoint(request):
        nonlocal num_endpoints
        num_endpoints -= 1

        endpoints.append(request)

        if num_endpoints < 0:
            raise RuntimeError("Too many endpoints registered")

    znp_server.callback_for_response(
        c.AFCommands.Register.Req(partial=True), register_endpoint
    )

    await app.startup(auto_form=False)

    assert len(endpoints) == 5


@pytest_mark_asyncio_timeout(seconds=2)
async def test_permit_join(application):
    app, znp_server = application

    # Handle the ZDO broadcast sent by Zigpy
    data_req_sent = znp_server.reply_once_to(
        request=c.AFCommands.DataRequestExt.Req(
            partial=True, SrcEndpoint=0, DstEndpoint=0
        ),
        responses=[
            c.AFCommands.DataRequestExt.Rsp(Status=t.Status.Success),
            c.AFCommands.DataConfirm.Callback(
                Status=t.Status.Success, Endpoint=0, TSN=1
            ),
        ],
    )

    # Handle the permit join request sent by us
    permit_join_sent = znp_server.reply_once_to(
        request=c.ZDOCommands.MgmtPermitJoinReq.Req(partial=True),
        responses=[
            c.ZDOCommands.MgmtPermitJoinReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.MgmtPermitJoinRsp.Callback(
                Src=0x0000, Status=t.ZDOStatus.SUCCESS
            ),
        ],
    )

    await app.startup(auto_form=False)
    await app.permit(time_s=10)

    # Make sure both commands were received
    await asyncio.gather(data_req_sent, permit_join_sent)


@pytest_mark_asyncio_timeout(seconds=2)
async def test_permit_join_failure(application):
    app, znp_server = application

    # Handle the ZDO broadcast sent by Zigpy
    data_req_sent = znp_server.reply_once_to(
        request=c.AFCommands.DataRequestExt.Req(
            partial=True, SrcEndpoint=0, DstEndpoint=0
        ),
        responses=[
            c.AFCommands.DataRequestExt.Rsp(Status=t.Status.Success),
            c.AFCommands.DataConfirm.Callback(
                Status=t.Status.Success, Endpoint=0, TSN=1
            ),
        ],
    )

    # Handle the permit join request sent by us
    permit_join_sent = znp_server.reply_once_to(
        request=c.ZDOCommands.MgmtPermitJoinReq.Req(partial=True),
        responses=[
            c.ZDOCommands.MgmtPermitJoinReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.MgmtPermitJoinRsp.Callback(
                Src=0xFFFF, Status=t.ZDOStatus.TIMEOUT
            ),
        ],
    )

    await app.startup(auto_form=False)

    with pytest.raises(RuntimeError):
        await app.permit(time_s=10)

    # Make sure both commands were received
    await asyncio.gather(data_req_sent, permit_join_sent)


@pytest_mark_asyncio_timeout()
async def test_on_zdo_relays_message_callback(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    device = mocker.Mock()
    mocker.patch.object(app, "get_device", return_value=device)

    znp_server.send(
        c.ZDOCommands.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD])
    )
    assert device.relays == [0x5678, 0xABCD]


@pytest_mark_asyncio_timeout()
async def test_on_zdo_device_announce(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join")

    nwk = 0x1234
    ieee = t.EUI64(range(8))

    znp_server.send(
        c.ZDOCommands.EndDeviceAnnceInd.Callback(
            Src=0x0001, NWK=nwk, IEEE=ieee, Capabilities=c.zdo.MACCapabilities.Router
        )
    )
    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0)


@pytest_mark_asyncio_timeout()
async def test_on_zdo_device_join(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join")

    nwk = 0x1234
    ieee = t.EUI64(range(8))

    znp_server.send(
        c.ZDOCommands.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001)
    )
    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)


@pytest_mark_asyncio_timeout()
async def test_on_zdo_device_leave_callback(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_leave")

    nwk = 0x1234
    ieee = t.EUI64(range(8))

    znp_server.send(
        c.ZDOCommands.LeaveInd.Callback(
            NWK=nwk, IEEE=ieee, Request=False, Remove=False, Rejoin=False
        )
    )
    app.handle_leave.assert_called_once_with(nwk=nwk, ieee=ieee)


@pytest_mark_asyncio_timeout()
async def test_on_af_message_callback(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    device = mocker.Mock()
    mocker.patch.object(
        app, "get_device", side_effect=[device, KeyError("No such device")]
    )
    mocker.patch.object(app, "handle_message")

    af_message = c.AFCommands.IncomingMsg.Callback(
        GroupId=1,
        ClusterId=2,
        SrcAddr=0xABCD,
        SrcEndpoint=4,
        DstEndpoint=5,
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
    app.get_device.assert_called_once_with(nwk=0xABCD)
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=260, cluster=2, src_ep=4, dst_ep=5, message=b"test"
    )

    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    # Message from an unknown device
    znp_server.send(af_message)
    app.get_device.assert_called_once_with(nwk=0xABCD)
    assert device.radio_details.call_count == 0
    assert app.handle_message.call_count == 0


@pytest_mark_asyncio_timeout()
async def test_probe(pingable_serial_port):  # noqa: F811
    assert not (
        await ControllerApplication.probe(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: "/dev/null"})
        )
    )

    assert await ControllerApplication.probe(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: pingable_serial_port})
    )


@pytest_mark_asyncio_timeout(seconds=5)
async def test_reconnect(event_loop, application):
    app, znp_server = application
    app._config[conf.CONF_ZNP_CONFIG][conf.CONF_AUTO_RECONNECT_RETRY_DELAY] = 0.01

    await app.startup(auto_form=False)

    # Don't reply to the ping request this time
    old_ping_replier = znp_server.ping_replier
    znp_server.ping_replier = lambda request: None

    # Now that we're connected, close the connection due to an error
    SREQ_TIMEOUT = 0.2
    app._config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT] = SREQ_TIMEOUT
    app._znp._uart.connection_lost(RuntimeError("Uh oh"))
    app.connection_lost(RuntimeError("Uh oh"))

    assert app._znp is None

    # Wait for the SREQ_TIMEOUT to pass, we should fail to reconnect
    await asyncio.sleep(SREQ_TIMEOUT + 0.1)
    assert app._znp is None

    # Respond to the ping appropriately
    znp_server.ping_replier = old_ping_replier

    # Our reconnect task should complete after we send the ping reply
    reconnect_fut = event_loop.create_future()
    app._reconnect_task.add_done_callback(lambda _: reconnect_fut.set_result(None))

    # We should be reconnected soon and the app should have been restarted
    await reconnect_fut
    assert app._znp is not None
    assert app._znp._uart is not None


@pytest_mark_asyncio_timeout()
async def test_auto_connect(mocker, application):
    AUTO_DETECTED_PORT = "/dev/ttyFAKE0"

    app, znp_server = application

    uart_guess_port = mocker.patch(
        "zigpy_znp.uart.guess_port", return_value=AUTO_DETECTED_PORT
    )

    async def fixed_uart_connect(config, api):
        protocol = await uart_connect(config, api)
        protocol.transport.serial.name = AUTO_DETECTED_PORT

        return protocol

    uart_connect_mock = mocker.patch(
        "zigpy_znp.uart.connect", side_effect=fixed_uart_connect
    )

    app._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH] = "auto"
    await app.startup(auto_form=False)

    assert uart_guess_port.call_count == 1
    assert uart_connect_mock.call_count == 1
    assert app._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH] == AUTO_DETECTED_PORT


@pytest_mark_asyncio_timeout()
async def test_close(mocker, application):
    app, znp_server = application
    app.connection_lost = mocker.MagicMock(wraps=app.connection_lost)

    await app.startup(auto_form=False)
    app._znp._uart.connection_lost(None)

    app.connection_lost.assert_called_once_with(None)


@pytest_mark_asyncio_timeout()
async def test_shutdown(mocker, application):
    app, znp_server = application

    await app.startup(auto_form=False)

    mocker.patch.object(app, "_reconnect_task")
    mocker.patch.object(app, "_znp")

    await app.shutdown()

    app._reconnect_task.cancel.assert_called_once_with()
    app._znp.close.assert_called_once_with()


@pytest_mark_asyncio_timeout(seconds=2)
async def test_zdo_request_interception(application, mocker):
    app, znp_server = application
    await app.startup(auto_form=False)

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0x0011)

    # Send back a request response
    active_ep_req = znp_server.reply_once_to(
        request=c.ZDOCommands.ActiveEpReq.Req(
            DstAddr=device.nwk, NWKAddrOfInterest=device.nwk
        ),
        responses=[
            c.ZDOCommands.ActiveEpReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.ActiveEpRsp.Callback(
                Src=device.nwk,
                Status=t.ZDOStatus.SUCCESS,
                ActiveEndpoints=[0, 1, 2],
                NWK=device.nwk,
            ),
        ],
    )

    status, message = await app.request(
        device=device,
        profile=260,
        cluster=ZDOCmd.Active_EP_req,
        src_ep=0,
        dst_ep=0,
        sequence=0,
        data=b"test",
    )

    await active_ep_req

    assert status == t.Status.Success
