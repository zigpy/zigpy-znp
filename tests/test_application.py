import asyncio
import logging

import pytest

try:
    # Python 3.8 already has this
    from mock import AsyncMock as CoroutineMock
except ImportError:
    from asynctest import CoroutineMock

import zigpy
import zigpy_znp.types as t
import zigpy_znp.commands as c
import zigpy_znp.config as conf

import zigpy.device
from zigpy.zdo.types import ZDOCmd, SizePrefixedSimpleDescriptor

from zigpy_znp.uart import ZnpMtProtocol

from zigpy_znp.api import ZNP
from zigpy_znp.uart import connect as uart_connect
from zigpy_znp.znp.nib import NIB, NwkState16, NwkKeyDesc
from zigpy_znp.types.nvids import NwkNvIds
from zigpy_znp.zigbee.application import ControllerApplication


from .test_api import (  # noqa: F401
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

        # We just respond to pings, nothing more.
        # XXX: the lambda allows us to replace `ping_replier` if necessary
        self.callback_for_response(c.SYS.Ping.Req(), lambda r: self.ping_replier(r))
        self.callback_for_response(
            c.SYS.Version.Req(), lambda r: self.version_replier(r)
        )

    def ping_replier(self, request):
        self.send(c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities(1625)))

    def version_replier(self, request):
        self.send(
            c.SYS.Version.Rsp(
                TransportRev=2,
                ProductId=1,
                MajorRel=2,
                MinorRel=7,
                MaintRel=1,
                CodeRevision=20200417,
                BootloaderBuildType=c.sys.BootloaderBuildType.NON_BOOTLOADER_BUILD,
                BootloaderRevision=0xFFFFFFFF,
            )
        )

    def reply_once_to(self, request, responses):
        called_future = asyncio.get_running_loop().create_future()

        async def callback(request):
            if callback.called:
                return

            callback.called = request

            for response in responses:
                await asyncio.sleep(0.001)
                LOGGER.debug("Replying to %s with %s", request, response)

                if callable(response):
                    self.send(response(request))
                else:
                    self.send(response)

            called_future.set_result(request)

        callback.called = False
        self.callback_for_response(request, lambda r: asyncio.create_task(callback(r)))

        return called_future

    def reply_to(self, request, responses):
        async def callback(request):
            callback.call_count += 1

            for response in responses:
                await asyncio.sleep(0.001)
                LOGGER.debug("Replying to %s with %s", request, response)

                if callable(response):
                    self.send(response(request))
                else:
                    self.send(response)

        callback.call_count = 0

        self.callback_for_response(request, lambda r: asyncio.create_task(callback(r)))

        return callback

    def send(self, response):
        if response is not None:
            self._uart.send(response.to_frame())


@pytest.fixture
async def znp_server(mocker):
    device = "/dev/ttyFAKE0"
    config = config_for_port_path(device)

    server_znp = ServerZNP(config)
    server_znp._uart = None

    server_znp_proto = ZnpMtProtocol(server_znp)

    def passthrough_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        fut = loop.create_future()
        assert url == device

        if server_znp._uart is None:
            server_znp._uart = server_znp_proto

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


def make_application(znp_server, config=None):
    app = ControllerApplication(config or config_for_port_path("/dev/ttyFAKE0"))

    # Handle the entire startup sequence
    znp_server.reply_to(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        responses=[
            c.SYS.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=2,
                ProductId=1,
                MajorRel=2,
                MinorRel=7,
                MaintRel=1,
            )
        ],
    )

    active_eps = [1, 2]

    znp_server.reply_to(
        request=c.ZDO.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
        responses=[
            c.ZDO.ActiveEpReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.ActiveEpRsp.Callback(
                Src=0x0000,
                Status=t.ZDOStatus.SUCCESS,
                NWK=0x0000,
                ActiveEndpoints=active_eps,
            ),
        ],
    )

    def on_endpoint_registration(req):
        assert req.Endpoint not in active_eps

        active_eps.append(req.Endpoint)
        active_eps.sort(reverse=True)

        return c.AF.Register.Rsp(Status=t.Status.SUCCESS)

    znp_server.reply_to(
        request=c.AF.Register.Req(partial=True), responses=[on_endpoint_registration],
    )

    def on_endpoint_deletion(req):
        assert req.Endpoint in active_eps

        active_eps.remove(req.Endpoint)

        return c.AF.Delete.Rsp(Status=t.Status.SUCCESS)

    znp_server.reply_to(
        request=c.AF.Delete.Req(partial=True), responses=[on_endpoint_deletion],
    )

    znp_server.reply_to(
        request=c.AppConfig.BDBStartCommissioning.Req(
            Mode=c.app_config.BDBCommissioningMode.NwkFormation
        ),
        responses=[
            c.AppConfig.BDBStartCommissioning.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator),
            c.AppConfig.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.NetworkRestored,
                Mode=c.app_config.BDBCommissioningMode.NONE,
                RemainingModes=c.app_config.BDBCommissioningMode.NwkFormation,
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.FormationFailure,
                Mode=c.app_config.BDBCommissioningMode.NwkFormation,
                RemainingModes=c.app_config.BDBCommissioningMode.NONE,
            ),
        ],
    )

    # Simulate a bit of NVRAM
    nvram = {
        NwkNvIds.HAS_CONFIGURED_ZSTACK3: b"\x55",
        NwkNvIds.NIB: NIB(
            SequenceNum=203,
            PassiveAckTimeout=5,
            MaxBroadcastRetries=2,
            MaxChildren=51,
            MaxDepth=20,
            MaxRouters=51,
            dummyNeighborTable=0,
            BroadcastDeliveryTime=30,
            ReportConstantCost=0,
            RouteDiscRetries=0,
            dummyRoutingTable=0,
            SecureAllFrames=1,
            SecurityLevel=5,
            SymLink=1,
            CapabilityFlags=143,
            PaddingByte0=b"\x00",
            TransactionPersistenceTime=7,
            nwkProtocolVersion=2,
            RouteDiscoveryTime=5,
            RouteExpiryTime=30,
            PaddingByte1=b"\x00",
            nwkDevAddress=0x0000,
            nwkLogicalChannel=25,
            PaddingByte2=b"\x00",
            nwkCoordAddress=0x0000,
            nwkCoordExtAddress=t.EUI64.convert("00:00:00:00:00:00:00:00"),
            nwkPanId=34453,
            nwkState=NwkState16.NWK_ROUTER,
            channelList=t.Channels.from_channel_list([15, 20, 25]),
            beaconOrder=15,
            superFrameOrder=15,
            scanDuration=4,
            battLifeExt=0,
            allocatedRouterAddresses=1,
            allocatedEndDeviceAddresses=1,
            nodeDepth=0,
            extendedPANID=t.EUI64.convert("a8:c0:3b:db:53:ca:60:a8"),
            nwkKeyLoaded=t.Bool.true,
            spare1=NwkKeyDesc(keySeqNum=0, key=[0] * 16),
            spare2=NwkKeyDesc(keySeqNum=0, key=[0] * 16),
            spare3=0,
            spare4=0,
            nwkLinkStatusPeriod=15,
            nwkRouterAgeLimit=3,
            nwkUseMultiCast=t.Bool.false,
            nwkIsConcentrator=t.Bool.true,
            nwkConcentratorDiscoveryTime=120,
            nwkConcentratorRadius=10,
            nwkAllFresh=1,
            PaddingByte3=b"\x00",
            nwkManagerAddr=0x0000,
            nwkTotalTransmissions=5559,
            nwkUpdateId=0,
            PaddingByte4=b"\x00",
        ).serialize(),
        NwkNvIds.EXTENDED_PAN_ID: b"\xA8\x60\xCA\x53\xDB\x3B\xC0\xA8",
        NwkNvIds.EXTADDR: b"\x5C\xAC\xAA\x1C\x00\x4B\x12\x00",
        NwkNvIds.CHANLIST: b"\x00\x80\x10\x02",
        NwkNvIds.PANID: b"\x95\x86",
        NwkNvIds.CONCENTRATOR_ENABLE: b"\x01",
        NwkNvIds.CONCENTRATOR_DISCOVERY: b"\x78",
        NwkNvIds.CONCENTRATOR_RC: b"\x01",
        NwkNvIds.SRC_RTG_EXPIRY_TIME: b"\xFF",
        NwkNvIds.NWK_CHILD_AGE_ENABLE: b"\x00",
        NwkNvIds.LOGICAL_TYPE: b"\x00",
    }

    def nvram_write(req):
        nvram[req.Id] = req.Value
        return c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)

    znp_server.reply_to(
        request=c.SYS.OSALNVWrite.Req(Offset=0, partial=True), responses=[nvram_write],
    )

    def nvram_read(req):
        if req.Id not in nvram:
            return c.SYS.OSALNVRead.Rsp(Status=t.Status.INVALID_PARAMETER, Value=b"")

        return c.SYS.OSALNVRead.Rsp(Status=t.Status.SUCCESS, Value=nvram[req.Id],)

    znp_server.reply_to(
        request=c.SYS.OSALNVRead.Req(Offset=0, partial=True), responses=[nvram_read],
    )

    def nvram_init(req):
        nvram[req.Id] = req.Value

        return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.SUCCESS)

    znp_server.reply_to(
        request=c.SYS.OSALNVItemInit.Req(partial=True), responses=[nvram_init]
    )

    # Reply to `self.permit_ncp(0)`
    znp_server.reply_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.NWK, Dst=0x0000, Duration=0, TCSignificance=1,
        ),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    znp_server.reply_to(
        request=c.Util.GetDeviceInfo.Req(),
        responses=[
            c.Util.GetDeviceInfo.Rsp(
                Status=t.Status.SUCCESS,
                IEEE=t.EUI64.deserialize(nvram[NwkNvIds.EXTADDR])[0],
                NWK=t.NWK(0xFFFE),
                DeviceType=t.DeviceTypeCapabilities(7),
                DeviceState=t.DeviceState.InitializedNotStarted,
                AssociatedDevices=[],
            )
        ],
    )

    znp_server._nvram_state = nvram

    return app, znp_server


@pytest.fixture
def application(znp_server):
    return lambda config=None: make_application(znp_server, config)


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup_skip_bootloader(application, mocker):
    app, znp_server = application()

    first_uart_byte = None

    def create_patched_write(original_write):
        def patched_write(data):
            nonlocal first_uart_byte

            # Intercept the first byte if it's destined for the bootloader
            is_for_bootloader = data[0] in c.ubl.BootloaderRunMode._value2member_map_

            if first_uart_byte is None and is_for_bootloader:
                first_uart_byte = data[0]
                data = data[1:]

            return original_write(data)

        return patched_write

    async def patched_uart_connect(config, api):
        protocol = await uart_connect(config, api)
        protocol.transport.write = create_patched_write(protocol.transport.write)

        return protocol

    mocker.patch("zigpy_znp.uart.connect", side_effect=patched_uart_connect)

    app.update_config({conf.CONF_ZNP_CONFIG: {conf.CONF_SKIP_BOOTLOADER: True}})
    await app.startup(auto_form=False)

    assert first_uart_byte == c.ubl.BootloaderRunMode.FORCE_RUN


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup_nib_cc26x2(application):
    app, znp_server = application()

    # This doesn't raise an error even if our NIB is empty
    assert app.channel is None

    await app.startup(auto_form=False)

    assert app.channel == 25
    assert app.channels == t.Channels.from_channel_list([15, 20, 25])

    assert app.zigpy_device.manufacturer == "Texas Instruments"
    assert app.zigpy_device.model == "CC13X2/CC26X2"


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup_nib_cc2531(application):
    app, znp_server = application()

    # Use a CC2531 NIB
    znp_server._nvram_state[NwkNvIds.NIB] = (
        b"\xCC\x05\x02\x10\x14\x10\x00\x14\x00\x00\x00\x01\x05\x01\x8F\x07\x00\x02\x05"
        b"\x1E\x00\x00\x0B\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xFC\x8D\x08\x00\x08"
        b"\x00\x00\x0F\x0F\x04\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x85\x33\xCE\x1C"
        b"\x00\x4B\x12\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x3C\x03\x00\x01\x78\x0A\x01\x00\x00\x00\x00\x00"
    )

    await app.startup(auto_form=False)

    assert app.zigpy_device.manufacturer == "Texas Instruments"
    assert app.zigpy_device.model == "CC2531"


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup_endpoints(application):
    app, znp_server = application()

    endpoints = []
    znp_server.callback_for_response(c.AF.Register.Req(partial=True), endpoints.append)

    await app.startup(auto_form=False)

    assert len(endpoints) == 2


@pytest_mark_asyncio_timeout(seconds=5)
async def test_application_startup_failure(application):
    app, znp_server = application()

    znp_server._nvram_state.pop(NwkNvIds.HAS_CONFIGURED_ZSTACK3)

    # We cannot start the application if Z-Stack is not configured and without auto_form
    with pytest.raises(RuntimeError):
        await app.startup(auto_form=False)

    # An invalid value is still bad
    znp_server._nvram_state[NwkNvIds.HAS_CONFIGURED_ZSTACK3] = b"\x00"

    with pytest.raises(RuntimeError):
        await app.startup(auto_form=False)


@pytest_mark_asyncio_timeout()
async def test_application_startup_reset(application, mocker):
    app, znp_server = application()

    mocker.spy(app, "_reset")
    await app.startup()

    assert app._reset.call_count >= 1


@pytest_mark_asyncio_timeout()
async def test_application_startup_slow(application, mocker):
    app, znp_server = application()

    znp_server._nvram_state[NwkNvIds.LOGICAL_TYPE] = b"\x01"

    mocker.spy(app, "_reset")
    await app.startup()

    assert app._reset.call_count >= 1


@pytest_mark_asyncio_timeout(seconds=3)
async def test_application_startup_tx_power(application):
    app, znp_server = application()

    set_tx_power = znp_server.reply_once_to(
        request=c.SYS.SetTxPower.Req(TXPower=19),
        responses=[c.SYS.SetTxPower.Rsp(Status=t.Status.SUCCESS)],
    )

    app.update_config({conf.CONF_ZNP_CONFIG: {conf.CONF_TX_POWER: 19}})

    await app.startup(auto_form=False)
    await set_tx_power


@pytest_mark_asyncio_timeout(seconds=3)
async def test_application_startup_led_mode(application):
    app, znp_server = application()

    set_led_mode = znp_server.reply_once_to(
        request=c.Util.LEDControl.Req(partial=True),
        responses=[c.Util.LEDControl.Rsp(Status=t.Status.SUCCESS)],
    )

    app.update_config({conf.CONF_ZNP_CONFIG: {conf.CONF_LED_MODE: "off"}})

    await app.startup(auto_form=False)
    led_req = await set_led_mode

    assert led_req.Mode == c.util.LEDMode.OFF
    assert led_req.LED == 0xFF


@pytest_mark_asyncio_timeout(seconds=3)
async def test_permit_join(application):
    app, znp_server = application()

    # Handle the ZDO broadcast sent by Zigpy
    data_req_sent = znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(partial=True, SrcEndpoint=0, DstEndpoint=0),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(Status=t.Status.SUCCESS, Endpoint=0, TSN=1),
        ],
    )

    # Handle the permit join request sent by us
    permit_join_sent = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(Duration=10, partial=True),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0xFFFC, Status=t.ZDOStatus.SUCCESS),
        ],
    )

    await app.startup(auto_form=False)
    await app.permit(time_s=10)

    # Make sure both commands were received
    await asyncio.gather(data_req_sent, permit_join_sent)


@pytest_mark_asyncio_timeout(seconds=3)
async def test_permit_join_failure(application):
    app, znp_server = application()

    # Handle the ZDO broadcast sent by Zigpy
    data_req_sent = znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(partial=True, SrcEndpoint=0, DstEndpoint=0),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            c.AF.DataConfirm.Callback(Status=t.Status.SUCCESS, Endpoint=0, TSN=1),
        ],
    )

    # Handle the permit join request sent by us
    permit_join_sent = znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(Duration=10, partial=True),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0xFFFC, Status=t.ZDOStatus.TIMEOUT),
        ],
    )

    await app.startup(auto_form=False)

    with pytest.raises(RuntimeError):
        await app.permit(time_s=10)

    # Make sure both commands were received
    await asyncio.gather(data_req_sent, permit_join_sent)


@pytest_mark_asyncio_timeout(seconds=3)
async def test_on_zdo_relays_message_callback(application, mocker):
    app, znp_server = application()
    await app.startup(auto_form=False)

    device = mocker.Mock()
    mocker.patch.object(app, "get_device", return_value=device)

    znp_server.send(c.ZDO.SrcRtgInd.Callback(DstAddr=0x1234, Relays=[0x5678, 0xABCD]))
    assert device.relays == [0x5678, 0xABCD]


@pytest_mark_asyncio_timeout(seconds=3)
async def test_on_zdo_device_announce(application, mocker):
    app, znp_server = application()
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_message")

    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xFA9E)

    znp_server.send(
        c.ZDO.EndDeviceAnnceInd.Callback(
            Src=0x0001,
            NWK=device.nwk,
            IEEE=device.ieee,
            Capabilities=c.zdo.MACCapabilities.Router,
        )
    )

    app.handle_message.called_once_with(cluster=ZDOCmd.Device_annce)


@pytest_mark_asyncio_timeout(seconds=3)
async def test_on_zdo_device_join(application, mocker):
    app, znp_server = application()
    await app.startup(auto_form=False)

    mocker.patch.object(app, "handle_join")

    nwk = 0x1234
    ieee = t.EUI64(range(8))

    znp_server.send(c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0001))
    app.handle_join.assert_called_once_with(nwk=nwk, ieee=ieee, parent_nwk=0x0001)


@pytest_mark_asyncio_timeout(seconds=3)
async def test_on_zdo_device_leave_callback(application, mocker):
    app, znp_server = application()
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


@pytest_mark_asyncio_timeout(seconds=3)
async def test_on_af_message_callback(application, mocker):
    app, znp_server = application()
    await app.startup(auto_form=False)

    device = mocker.Mock()
    mocker.patch.object(
        app,
        "get_device",
        side_effect=[device, device, device, KeyError("No such device")],
    )
    mocker.patch.object(app, "handle_message")

    af_message = c.AF.IncomingMsg.Callback(
        GroupId=1,
        ClusterId=2,
        SrcAddr=0xABCD,
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
    app.get_device.assert_called_once_with(nwk=0xABCD)
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=260, cluster=2, src_ep=4, dst_ep=1, message=b"test"
    )

    # ZLL message
    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    znp_server.send(af_message.replace(DstEndpoint=2))
    app.get_device.assert_called_once_with(nwk=0xABCD)
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=49246, cluster=2, src_ep=4, dst_ep=2, message=b"test"
    )

    # Message on an unknown endpoint (is this possible?)
    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    znp_server.send(af_message.replace(DstEndpoint=3))
    app.get_device.assert_called_once_with(nwk=0xABCD)
    device.radio_details.assert_called_once_with(lqi=19, rssi=None)
    app.handle_message.assert_called_once_with(
        sender=device, profile=260, cluster=2, src_ep=4, dst_ep=3, message=b"test"
    )

    # Message from an unknown device
    device.reset_mock()
    app.handle_message.reset_mock()
    app.get_device.reset_mock()

    znp_server.send(af_message)
    app.get_device.assert_called_once_with(nwk=0xABCD)
    assert device.radio_details.call_count == 0
    assert app.handle_message.call_count == 0


@pytest_mark_asyncio_timeout(seconds=3)
async def test_probe_unsuccessful(pingable_serial_port):  # noqa: F811
    assert not (
        await ControllerApplication.probe(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: "/dev/null"})
        )
    )


@pytest_mark_asyncio_timeout(seconds=3)
async def test_probe_successful(pingable_serial_port):  # noqa: F811
    assert await ControllerApplication.probe(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: pingable_serial_port})
    )


@pytest_mark_asyncio_timeout(seconds=3)
async def test_probe_multiple(pingable_serial_port):  # noqa: F811
    config = conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: pingable_serial_port})

    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)


@pytest_mark_asyncio_timeout(seconds=5)
async def test_reconnect(event_loop, application):
    app, znp_server = application()

    # Make auto-reconnection happen really fast
    app._config[conf.CONF_ZNP_CONFIG][conf.CONF_AUTO_RECONNECT_RETRY_DELAY] = 0.01

    # Don't clean up our server's listeners when it gets disconnected
    znp_server.close = lambda self: None

    # Start up the server
    await app.startup(auto_form=False)
    assert app._znp is not None

    # Don't reply to the ping request after this
    old_ping_replier = znp_server.ping_replier
    znp_server.ping_replier = lambda request: None

    # Now that we're connected, close the connection due to an error
    SREQ_TIMEOUT = 0.2
    app._config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT] = SREQ_TIMEOUT
    app._znp._uart.connection_lost(RuntimeError("Uh oh"))

    # ZNP should be closed
    assert app._znp is None

    # Wait for the SREQ_TIMEOUT to pass, we should still fail to reconnect
    await asyncio.sleep(SREQ_TIMEOUT + 0.1)
    assert app._znp is None

    # Start responding to pings after this
    znp_server.ping_replier = old_ping_replier

    # Our reconnect task should complete a moment after we send the ping reply
    while app._znp is None:
        await asyncio.sleep(0.01)

    assert app._znp is not None
    assert app._znp._uart is not None


@pytest_mark_asyncio_timeout(seconds=3)
async def test_auto_connect(mocker, application):
    AUTO_DETECTED_PORT = "/dev/ttyFAKE0"

    app, znp_server = application()

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


@pytest_mark_asyncio_timeout(seconds=3)
async def test_close(mocker, application):
    app, znp_server = application()
    app.connection_lost = mocker.MagicMock(wraps=app.connection_lost)

    await app.startup(auto_form=False)
    app._znp._uart.connection_lost(None)

    app.connection_lost.assert_called_once_with(None)


@pytest_mark_asyncio_timeout(seconds=3)
async def test_shutdown(mocker, application):
    app, znp_server = application()

    await app.startup(auto_form=False)

    mocker.patch.object(app, "_reconnect_task", autospec=app._reconnect_task)
    mocker.patch.object(app, "_znp")

    await app.shutdown()

    app._reconnect_task.cancel.assert_called_once_with()
    app._znp.close.assert_called_once_with()


@pytest_mark_asyncio_timeout(seconds=3)
async def test_zdo_request_interception(application, mocker):
    app, znp_server = application()
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

    await active_ep_req

    assert status == t.Status.SUCCESS


@pytest_mark_asyncio_timeout(seconds=10)
async def test_zigpy_request(application, mocker):
    app, znp_server = application()
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
            c.AF.DataConfirm.Callback(Status=t.Status.SUCCESS, Endpoint=1, TSN=TSN,),
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


@pytest_mark_asyncio_timeout(seconds=10)
async def test_zigpy_request_failure(application, mocker):
    app, znp_server = application()
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
            c.AF.DataConfirm.Callback(Status=t.Status.FAILURE, Endpoint=1, TSN=TSN,),
        ],
    )

    mocker.spy(app, "_send_request")

    # Fail to turn on the light
    with pytest.raises(zigpy.exceptions.DeliveryError):
        await device.endpoints[1].on_off.on()

    assert app._send_request.call_count == 1


@pytest_mark_asyncio_timeout(seconds=3)
@pytest.mark.parametrize(
    "use_ieee,dev_addr",
    [
        (True, t.AddrModeAddress(mode=t.AddrMode.IEEE, address=t.EUI64(range(8)))),
        (False, t.AddrModeAddress(mode=t.AddrMode.NWK, address=t.NWK(0xAABB))),
    ],
)
async def test_request_use_ieee(application, mocker, use_ieee, dev_addr):
    app, znp_server = application()
    device = app.add_device(ieee=t.EUI64(range(8)), nwk=0xAABB)

    mocker.patch.object(app, "_send_request", new=CoroutineMock())

    await app.request(
        device,
        use_ieee=use_ieee,
        profile=1,
        cluster=2,
        src_ep=3,
        dst_ep=4,
        sequence=5,
        data=b"6",
    )

    assert app._send_request.call_count == 1
    assert app._send_request.mock_calls[0][2]["dst_addr"] == dev_addr


@pytest_mark_asyncio_timeout(seconds=3)
async def test_update_network_noop(mocker, application):
    app, znp_server = application()

    await app.startup(auto_form=False)

    app._znp = mocker.NonCallableMock()

    # Nothing should be called
    await app.update_network(reset=False)

    # This will call _znp.request and fail
    with pytest.raises(TypeError):
        await app.update_network(reset=True)


@pytest_mark_asyncio_timeout(seconds=5)
async def test_update_network_extensive(mocker, caplog, application):
    app, znp_server = application()

    await app.startup(auto_form=False)
    mocker.spy(app, "_reset")

    channel = t.uint8_t(20)
    pan_id = t.PanId(0x1234)
    extended_pan_id = t.ExtendedPanId(range(8))
    channels = t.Channels.from_channel_list([11, 15, 20])
    network_key = t.KeyData(range(16))

    bdb_set_primary_channel = znp_server.reply_once_to(
        request=c.AppConfig.BDBSetChannel.Req(IsPrimary=True, Channel=channels),
        responses=[c.AppConfig.BDBSetChannel.Rsp(Status=t.Status.SUCCESS)],
    )

    bdb_set_secondary_channel = znp_server.reply_once_to(
        request=c.AppConfig.BDBSetChannel.Req(
            IsPrimary=False, Channel=t.Channels.NO_CHANNELS
        ),
        responses=[c.AppConfig.BDBSetChannel.Rsp(Status=t.Status.SUCCESS)],
    )

    # Make sure we actually change things
    assert app.channel != channel
    assert app.pan_id != pan_id
    assert app.extended_pan_id != extended_pan_id

    with caplog.at_level(logging.WARNING):
        await app.update_network(
            channel=channel,
            channels=channels,
            extended_pan_id=extended_pan_id,
            network_key=network_key,
            pan_id=pan_id,
            tc_address=t.EUI64(range(8)),
            tc_link_key=t.KeyData(range(8)),
            update_id=0,
            reset=True,
        )

    # We should receive a few warnings for `tc_` stuff
    assert len(caplog.records) >= 2

    await bdb_set_primary_channel
    await bdb_set_secondary_channel

    app._reset.assert_called_once_with()

    # Ensure we set everything we could
    assert app.nwk_update_id is None  # We can't use it
    assert app.channel == channel
    assert app.channels == channels
    assert app.pan_id == pan_id
    assert app.extended_pan_id == extended_pan_id


@pytest_mark_asyncio_timeout(seconds=5)
async def test_update_network_bad_channel(mocker, caplog, application):
    app, znp_server = application()

    with pytest.raises(ValueError):
        # 12 is not in the mask
        await app.update_network(
            channel=t.uint8_t(12), channels=t.Channels.from_channel_list([11, 15, 20]),
        )


@pytest_mark_asyncio_timeout(seconds=3)
async def test_force_remove(application, mocker):
    app, znp_server = application()

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


@pytest_mark_asyncio_timeout(seconds=3)
async def test_auto_form_unnecessary(application, mocker, caplog):
    app, znp_server = application()

    mocker.patch.object(app, "form_network", new=CoroutineMock())

    with caplog.at_level(logging.WARNING):
        await app.startup(auto_form=True)

    # We should receive no warnings or errors
    assert not caplog.records

    assert app.form_network.call_count == 0


@pytest_mark_asyncio_timeout(seconds=3)
@pytest.mark.parametrize("channel", [None, 15, 20, 25])
async def test_auto_form_necessary(channel, application, mocker, caplog):
    app, znp_server = application()
    app._config[conf.CONF_NWK][conf.CONF_NWK_CHANNEL] = channel
    nvram = znp_server._nvram_state

    nvram.pop(NwkNvIds.HAS_CONFIGURED_ZSTACK3)

    mocker.patch.object(app, "update_network", new=CoroutineMock())
    mocker.spy(app, "_reset")

    znp_server.reply_to(
        request=c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1),
        responses=[c.SYS.OSALNVDelete.Rsp(Status=t.Status.NV_ITEM_UNINIT)],
    )

    # Remove the existing listener that simulates the normal startup sequence
    bdb_hdr = c.AppConfig.BDBStartCommissioning.Req(partial=True).header
    orig_commissioning_listeners = znp_server._listeners[bdb_hdr].copy()
    znp_server._listeners[bdb_hdr].clear()

    # And copy what the device actually sends
    did_normal_startup = znp_server.reply_once_to(
        request=c.AppConfig.BDBStartCommissioning.Req(
            Mode=c.app_config.BDBCommissioningMode.NwkFormation
        ),
        responses=[
            c.AppConfig.BDBStartCommissioning.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartingAsCoordinator),
            c.AppConfig.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.InProgress,
                Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                RemainingModes=c.app_config.BDBCommissioningMode.NwkFormation,
            ),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartingAsCoordinator),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartingAsCoordinator),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartingAsCoordinator),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartingAsCoordinator),
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator),
            c.AppConfig.BDBCommissioningNotification.Callback(
                Status=c.app_config.BDBCommissioningStatus.Success,
                Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                RemainingModes=c.app_config.BDBCommissioningMode.NONE,
            ),
        ],
    )

    # And reset it back to normal immediately after we form the network
    def reset_commissioning_listeners(_):
        znp_server._listeners[bdb_hdr] = orig_commissioning_listeners

    did_normal_startup.add_done_callback(reset_commissioning_listeners)

    # The NIB contains an invalid logical channel at first
    orig_nib, _ = NIB.deserialize(nvram[NwkNvIds.NIB])
    assert nvram[NwkNvIds.NIB] == orig_nib.serialize()
    nvram[NwkNvIds.NIB] = orig_nib.replace(nwkLogicalChannel=0).serialize()

    nib_read_count = 0

    def reset_nib(_):
        nonlocal nib_read_count
        nib_read_count += 1

        # Let it be invalid for a few reads
        if nib_read_count == 2:
            nvram[NwkNvIds.NIB] = orig_nib.serialize()

    znp_server.reply_to(
        request=c.SYS.OSALNVRead.Req(Id=NwkNvIds.NIB, Offset=0), responses=[reset_nib]
    )

    with caplog.at_level(logging.WARNING):
        # Finally test startup with auto forming
        await app.startup(auto_form=True)

    # We should receive no application warnings or errors
    assert not [r for r in caplog.records if "Task was destroyed" not in r.getMessage()]

    if channel in (25, None):
        assert app.update_network.call_count == 1
    else:
        # A second network update is performed to switch the channel over
        assert app.update_network.call_count == 2

    assert nvram[NwkNvIds.HAS_CONFIGURED_ZSTACK3] == b"\x55"
    assert (
        nvram[NwkNvIds.STARTUP_OPTION]
        == (t.StartupOptions.ClearState | t.StartupOptions.ClearConfig).serialize()
    )
    assert nvram[NwkNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    assert nvram[NwkNvIds.ZDO_DIRECT_CB] == t.Bool(True).serialize()


@pytest_mark_asyncio_timeout(seconds=3)
async def test_clean_shutdown(application, mocker):
    app, znp_server = application()

    # This should not throw
    await app.shutdown()


@pytest_mark_asyncio_timeout(seconds=3)
async def test_unclean_shutdown(application, mocker):
    app, znp_server = application()
    app._znp = None

    # This should also not throw
    await app.shutdown()


@pytest_mark_asyncio_timeout(seconds=3)
async def test_mrequest(application, mocker):
    app, znp_server = application()

    mocker.patch.object(app, "_send_request", new=CoroutineMock())
    group = app.groups.add_group(0x1234, "test group")

    await group.endpoint.on_off.on()

    assert app._send_request.call_count == 1
    assert app._send_request.mock_calls[0][2]["dst_addr"] == t.AddrModeAddress(
        mode=t.AddrMode.Group, address=0x1234
    )
    assert app._send_request.mock_calls[0][2]["data"] == b"\x01\x01\x01"


@pytest_mark_asyncio_timeout(seconds=3)
async def test_new_device_join_and_bind(application, mocker):
    app, znp_server = application()
    await app.startup(auto_form=False)

    nwk = 0x6A7C
    ieee = t.EUI64([0x00, 0x17, 0x88, 0x01, 0x08, 0x64, 0x6C, 0x81][::-1])

    # Handle the ZDO permit join broadcast sent by Zigpy
    znp_server.reply_once_to(
        request=c.AF.DataRequestExt.Req(
            partial=True,
            DstAddrModeAddress=t.AddrModeAddress(
                mode=t.AddrMode.Broadcast,
                address=zigpy.types.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
            ),
            DstEndpoint=0,
            DstPanId=0x0000,
            SrcEndpoint=0,
            ClusterId=54,
            Radius=0,
            Data=b"\x01\x3C\x00",
        ),
        responses=[
            c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS),
            lambda r: c.AF.DataConfirm.Callback(
                Status=t.Status.SUCCESS, Endpoint=0, TSN=r.TSN
            ),
        ],
    )

    znp_server.reply_once_to(
        request=c.ZDO.MgmtPermitJoinReq.Req(partial=True),
        responses=[
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0xFFFC, Status=t.ZDOStatus.SUCCESS),
            c.ZDO.TCDevInd.Callback(SrcNwk=nwk, SrcIEEE=ieee, ParentNwk=0x0000),
        ],
    )

    znp_server.reply_to(
        request=c.ZDO.NodeDescReq.Req(DstAddr=nwk, NWKAddrOfInterest=nwk),
        responses=[
            c.ZDO.NodeDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.EndDeviceAnnceInd.Callback(
                Src=nwk,
                NWK=nwk,
                IEEE=ieee,
                Capabilities=c.zdo.MACCapabilities.AllocateShortAddrDuringAssocNeeded,
            ),
            c.ZDO.NodeDescRsp.Callback(
                Src=nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=nwk,
                NodeDescriptor=c.zdo.NullableNodeDescriptor(
                    2, 64, 128, 4107, 89, 63, 0, 63, 0
                ),
            ),
        ],
    )

    znp_server.reply_to(
        request=c.ZDO.ActiveEpReq.Req(DstAddr=nwk, NWKAddrOfInterest=nwk),
        responses=[
            c.ZDO.ActiveEpReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.ActiveEpRsp.Callback(
                Src=nwk, Status=t.ZDOStatus.SUCCESS, NWK=nwk, ActiveEndpoints=[2, 1]
            ),
        ],
    )

    znp_server.reply_to(
        request=c.ZDO.SimpleDescReq.Req(DstAddr=nwk, NWKAddrOfInterest=nwk, Endpoint=2),
        responses=[
            c.ZDO.SimpleDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.SimpleDescRsp.Callback(
                Src=nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=nwk,
                SimpleDescriptor=SizePrefixedSimpleDescriptor(
                    2, 260, 263, 0, [0, 1, 3, 1030, 1024, 1026], [25]
                ),
            ),
        ],
    )

    znp_server.reply_to(
        request=c.ZDO.SimpleDescReq.Req(DstAddr=nwk, NWKAddrOfInterest=nwk, Endpoint=1),
        responses=[
            c.ZDO.SimpleDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.SimpleDescRsp.Callback(
                Src=nwk,
                Status=t.ZDOStatus.SUCCESS,
                NWK=nwk,
                SimpleDescriptor=SizePrefixedSimpleDescriptor(
                    1, 49246, 2128, 2, [0], [0, 3, 4, 6, 8, 768, 5]
                ),
            ),
        ],
    )

    def data_req_callback(request):
        if request.Data == bytes([0x00, request.TSN]) + b"\x00\x04\x00\x05\x00":
            # Manufacturer + model
            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS,
                    Endpoint=request.SrcEndpoint,
                    TSN=request.TSN,
                )
            )
            znp_server.send(
                c.AF.IncomingMsg.Callback(
                    GroupId=0x0000,
                    ClusterId=request.ClusterId,
                    SrcAddr=nwk,
                    SrcEndpoint=request.DstEndpoint,
                    DstEndpoint=request.SrcEndpoint,
                    WasBroadcast=t.Bool.false,
                    LQI=156,
                    SecurityUse=t.Bool.false,
                    TimeStamp=2123652,
                    TSN=0,
                    Data=b"\x18"
                    + bytes([request.TSN])
                    + b"\x01\x04\x00\x00\x42\x07\x50\x68\x69\x6C\x69\x70\x73\x05\x00"
                    + b"\x00\x42\x06\x53\x4D\x4C\x30\x30\x31",
                    MacSrcAddr=nwk,
                    MsgResultRadius=29,
                )
            )
        elif request.Data == bytes([0x00, request.TSN]) + b"\x00\x04\x00":
            # Manufacturer
            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS,
                    Endpoint=request.SrcEndpoint,
                    TSN=request.TSN,
                )
            )
            znp_server.send(
                c.AF.IncomingMsg.Callback(
                    GroupId=0x0000,
                    ClusterId=request.ClusterId,
                    SrcAddr=nwk,
                    SrcEndpoint=request.DstEndpoint,
                    DstEndpoint=request.SrcEndpoint,
                    WasBroadcast=t.Bool.false,
                    LQI=156,
                    SecurityUse=t.Bool.false,
                    TimeStamp=2123652,
                    TSN=0,
                    Data=b"\x18"
                    + bytes([request.TSN])
                    + b"\x01\x04\x00\x00\x42\x07\x50\x68\x69\x6C\x69\x70\x73",
                    MacSrcAddr=nwk,
                    MsgResultRadius=29,
                )
            )
        elif request.Data == bytes([0x00, request.TSN]) + b"\x00\x05\x00":
            # Model
            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))
            znp_server.send(
                c.AF.DataConfirm.Callback(
                    Status=t.Status.SUCCESS,
                    Endpoint=request.SrcEndpoint,
                    TSN=request.TSN,
                )
            )
            znp_server.send(
                c.AF.IncomingMsg.Callback(
                    GroupId=0x0000,
                    ClusterId=request.ClusterId,
                    SrcAddr=nwk,
                    SrcEndpoint=request.DstEndpoint,
                    DstEndpoint=request.SrcEndpoint,
                    WasBroadcast=t.Bool.false,
                    LQI=156,
                    SecurityUse=t.Bool.false,
                    TimeStamp=2123652,
                    TSN=0,
                    Data=b"\x18"
                    + bytes([request.TSN])
                    + b"\x01\x05\x00\x00\x42\x06\x53\x4D\x4C\x30\x30\x31",
                    MacSrcAddr=nwk,
                    MsgResultRadius=29,
                )
            )

    znp_server.callback_for_response(
        c.AF.DataRequestExt.Req(
            partial=True,
            DstAddrModeAddress=t.AddrModeAddress(mode=t.AddrMode.NWK, address=nwk),
        ),
        data_req_callback,
    )

    device_future = asyncio.get_running_loop().create_future()

    class TestListener:
        def device_initialized(self, device):
            device_future.set_result(device)

    app.add_listener(TestListener())

    await app.permit(time_s=60)  # duration is sent as byte 0x3C in first ZDO broadcast

    # The device has finally joined and been initialized
    device = await device_future

    assert not device.initializing
    assert device.model == "SML001"
    assert device.manufacturer == "Philips"
    assert set(device.endpoints.keys()) == {0, 1, 2}

    assert set(device.endpoints[1].in_clusters.keys()) == {0}
    assert set(device.endpoints[1].out_clusters.keys()) == {0, 3, 4, 6, 8, 768, 5}

    assert set(device.endpoints[2].in_clusters.keys()) == {0, 1, 3, 1030, 1024, 1026}
    assert set(device.endpoints[2].out_clusters.keys()) == {25}

    # Once we've confirmed the device is good, start testing binds
    def bind_req_callback(request):
        assert request.Dst == nwk
        assert request.Src == ieee
        assert request.SrcEndpoint in device.endpoints

        cluster = request.ClusterId
        ep = device.endpoints[request.SrcEndpoint]
        assert cluster in ep.in_clusters or cluster in ep.out_clusters

        assert request.Address.ieee == app.ieee
        assert request.Address.addrmode == 0x03

        # Make sure the endpoint profiles match up
        our_ep = request.Address.endpoint
        assert app.get_device(nwk=0x0000).endpoints[our_ep].profile_id == ep.profile_id

        znp_server.send(c.ZDO.BindReq.Rsp(Status=t.Status.SUCCESS))
        znp_server.send(c.ZDO.BindRsp.Callback(Src=nwk, Status=t.ZDOStatus.SUCCESS))

    znp_server.callback_for_response(
        c.ZDO.BindReq.Req(Dst=nwk, Src=ieee, partial=True), bind_req_callback
    )

    for ep_id, endpoint in device.endpoints.items():
        if ep_id == 0:
            continue

        for cluster in endpoint.in_clusters.values():
            await cluster.bind()


@pytest_mark_asyncio_timeout(seconds=3)
async def test_request_concurrency(application, mocker):
    config = config_for_port_path("/dev/ttyFAKE0")
    config[conf.CONF_MAX_CONCURRENT_REQUESTS] = 2

    app, znp_server = application(conf.CONFIG_SCHEMA(config))
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
                    Status=t.Status.SUCCESS, Endpoint=1, TSN=req.TSN,
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
