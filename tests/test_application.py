import asyncio
import logging

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.uart import ZnpMtProtocol

from zigpy_znp.api import ZNP
from zigpy_znp.zigbee.application import ControllerApplication


from test_api import pytest_mark_asyncio_timeout

LOGGER = logging.getLogger(__name__)


class ForwardingTransport:
    class serial:
        name = "/dev/passthrough"

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
        super().__init__(*args, auto_reconnect=False, **kwargs)

        # We just respond to pings, nothing more
        self.callback_for_response(c.SysCommands.Ping.Req(), self.ping_replier)

    def reply_once_to(self, request, responses):
        async def callback():
            if callback.called:
                return

            callback.called = True

            for response in responses:
                await asyncio.sleep(0.1)
                self.send(response)

        callback.called = False
        self.callback_for_response(request, lambda _: asyncio.create_task(callback()))

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
async def znp_client_server(mocker, event_loop):
    server_znp = ServerZNP()
    server_znp._uart = ZnpMtProtocol(server_znp)
    device = "/dev/ttyFAKE0"

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

    znp = ZNP()
    await znp.connect(device, baudrate=1234_5678)

    return znp, server_znp


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup(znp_client_server, event_loop):
    znp, server_znp = znp_client_server

    # Now that we're connected, handle a few requests
    server_znp.reply_to(
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

    server_znp.reply_to(
        request=c.ZDOCommands.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
        responses=[
            c.ZDOCommands.ActiveEpReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.ActiveEpRsp.Callback(
                Src=0x0000, Status=t.ZDOStatus.SUCCESS, NWK=0x0000, ActiveEndpoints=[]
            ),
        ],
    )

    server_znp.reply_to(
        request=c.AFCommands.Register.Req(partial=True),
        responses=[c.AFCommands.Register.Rsp(Status=t.Status.Success)],
    )

    server_znp.reply_to(
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

    num_endpoints = 5
    endpoints = []

    def register_endpoint(request):
        nonlocal num_endpoints
        num_endpoints -= 1

        endpoints.append(request)

        if num_endpoints < 0:
            raise RuntimeError("Too many endpoints registered")

    server_znp.callback_for_response(
        c.AFCommands.Register.Req(partial=True), register_endpoint
    )

    application = ControllerApplication(znp)
    await application.startup(auto_form=False)

    assert len(endpoints) == 5


@pytest_mark_asyncio_timeout(seconds=1)
async def test_permit_join(znp_client_server, event_loop):
    znp, server_znp = znp_client_server

    # Handle the broadcast sent by Zigpy
    server_znp.reply_once_to(
        request=c.AFCommands.DataRequestExt.Req(partial=True),
        responses=[
            c.AFCommands.DataRequestExt.Rsp(Status=t.Status.Success),
            c.AFCommands.DataConfirm.Callback(
                Status=t.Status.Success, Endpoint=0, TSN=1
            ),
        ],
    )

    # Handle the permit join request sent by us
    server_znp.reply_once_to(
        request=c.ZDOCommands.MgmtPermitJoinReq.Req(partial=True),
        responses=[
            c.ZDOCommands.MgmtPermitJoinReq.Rsp(Status=t.Status.Success),
            c.ZDOCommands.MgmtPermitJoinRsp.Callback(
                Src=0x0000, Status=t.ZDOStatus.SUCCESS
            ),
        ],
    )

    application = ControllerApplication(znp)

    await application.permit(time_s=10)
