import json
import asyncio
import logging
import pathlib
import contextlib

import pytest
import zigpy.device

try:
    # Python 3.8 already has this
    from unittest.mock import AsyncMock as CoroutineMock  # noqa: F401
except ImportError:
    from asynctest import CoroutineMock  # noqa: F401

import zigpy.endpoint
import zigpy.zdo.types as zdo_t

import zigpy_znp.const as const
import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.uart import ZnpMtProtocol
from zigpy_znp.nvram import NVRAMHelper
from zigpy_znp.types.nvids import ExNvIds, NvSysIds, OsalNvIds, is_secure_nvid
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)

FAKE_SERIAL_PORT = "/dev/ttyFAKE0"


class ForwardingSerialTransport:
    """
    Serial transport that hooks directly into a protocol
    """

    class serial:
        # so the transport has a `serial` attribute
        name = FAKE_SERIAL_PORT
        baudrate = 45678

    def __init__(self, protocol):
        self.protocol = protocol
        self._is_connected = False
        self.other = None

    def _connect(self):
        assert not self._is_connected
        self._is_connected = True
        self.other.protocol.connection_made(self)

    def write(self, data):
        assert self._is_connected
        self.protocol.data_received(data)

    def close(self, *, error=ValueError("Connection was closed")):
        LOGGER.debug("Closing %s", self)
        if not self._is_connected:
            return

        self._is_connected = False

        # Our own protocol gets gracefully closed
        self.other.close(error=None)

        # The protocol we're forwarding to gets the error
        self.protocol.connection_lost(error)

    def __repr__(self):
        return f"<{type(self).__name__} to {self.protocol}>"


def config_for_port_path(path):
    return conf.CONFIG_SCHEMA({conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: path}})


@pytest.fixture
async def make_znp_server(mocker):
    transports = []

    mocker.patch("zigpy_znp.api.AFTER_CONNECT_DELAY", 0.001)
    mocker.patch("zigpy_znp.api.STARTUP_DELAY", 0.001)
    mocker.patch("zigpy_znp.uart.RTS_TOGGLE_DELAY", 0)

    def inner(server_cls, config=None):
        if config is None:
            config = config_for_port_path(FAKE_SERIAL_PORT)

        server = server_cls(config)
        server._transports = transports

        server.port_path = FAKE_SERIAL_PORT
        server._uart = None

        def passthrough_serial_conn(loop, protocol_factory, url, *args, **kwargs):
            LOGGER.info("Intercepting serial connection to %s", url)

            assert url == FAKE_SERIAL_PORT

            # No double connections!
            if any([t._is_connected for t in transports]):
                raise RuntimeError(
                    "Cannot open two connections to the same serial port"
                )

            if server._uart is None:
                server._uart = ZnpMtProtocol(server)
                mocker.spy(server._uart, "data_received")

            client_protocol = protocol_factory()

            # Client writes go to the server
            client_transport = ForwardingSerialTransport(server._uart)
            transports.append(client_transport)

            # Server writes go to the client
            server_transport = ForwardingSerialTransport(client_protocol)

            # Notify them of one another
            server_transport.other = client_transport
            client_transport.other = server_transport

            # And finally connect both simultaneously
            server_transport._connect()
            client_transport._connect()

            fut = loop.create_future()
            fut.set_result((client_transport, client_protocol))

            return fut

        mocker.patch(
            "serial_asyncio.create_serial_connection", new=passthrough_serial_conn
        )

        # So we don't have to import it every time
        server.serial_port = FAKE_SERIAL_PORT

        return server

    yield inner


@pytest.fixture
def make_connected_znp(make_znp_server, mocker):
    async def inner(server_cls):
        config = conf.CONFIG_SCHEMA(
            {
                conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: FAKE_SERIAL_PORT},
                conf.CONF_ZNP_CONFIG: {conf.CONF_SKIP_BOOTLOADER: False},
            }
        )

        mocker.patch("zigpy_znp.api.STARTUP_DELAY", 0)

        znp = ZNP(config)
        znp_server = make_znp_server(server_cls=server_cls)

        await znp.connect(test_port=False)

        znp.nvram.align_structs = server_cls.align_structs
        znp.version = server_cls.version

        if hasattr(znp_server, "ping_replier"):
            znp.capabilities = znp_server.ping_replier(None).Capabilities
        else:
            znp.capabilities = t.MTCapabilities(0)

        return znp, znp_server

    return inner


@pytest.fixture
def connected_znp(event_loop, make_connected_znp):
    znp, znp_server = event_loop.run_until_complete(make_connected_znp(BaseServerZNP))
    yield znp, znp_server
    znp.close()


def simple_deepcopy(d):
    if not hasattr(d, "copy"):
        return d

    if isinstance(d, (list, tuple)):
        return type(d)(map(simple_deepcopy, d))
    elif isinstance(d, dict):
        return type(d)({simple_deepcopy(k): simple_deepcopy(v) for k, v in d.items()})
    else:
        return d.copy()


def merge_dicts(a, b):
    c = simple_deepcopy(a)

    for key, value in b.items():
        if isinstance(value, dict):
            c[key] = merge_dicts(c.get(key, {}), value)
        else:
            c[key] = value

    return c


@contextlib.contextmanager
def swap_attribute(obj, name, value):
    old_value = getattr(obj, name)
    setattr(obj, name, value)

    try:
        yield old_value
    finally:
        setattr(obj, name, old_value)


@pytest.fixture
def make_application(make_znp_server):
    def inner(server_cls, client_config=None, server_config=None):
        default = config_for_port_path(FAKE_SERIAL_PORT)

        client_config = merge_dicts(default, client_config or {})
        server_config = merge_dicts(default, server_config or {})

        app = ControllerApplication(client_config)

        def add_initialized_device(self, *args, **kwargs):
            device = self.add_device(*args, **kwargs)
            device.status = zigpy.device.Status.ENDPOINTS_INIT
            device.model = "Model"
            device.manufacturer = "Manufacturer"

            device.node_desc = zdo_t.NodeDescriptor(
                logical_type=zdo_t.LogicalType.Router,
                complex_descriptor_available=0,
                user_descriptor_available=0,
                reserved=0,
                aps_flags=0,
                frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
                mac_capability_flags=142,
                manufacturer_code=4476,
                maximum_buffer_size=82,
                maximum_incoming_transfer_size=82,
                server_mask=11264,
                maximum_outgoing_transfer_size=82,
                descriptor_capability_field=0,
            )

            ep = device.add_endpoint(1)
            ep.status = zigpy.endpoint.Status.ZDO_INIT

            return device

        app.add_initialized_device = add_initialized_device.__get__(app)

        return app, make_znp_server(server_cls=server_cls, config=server_config)

    return inner


class BaseServerZNP(ZNP):
    align_structs = False
    version = None

    def _flatten_responses(self, request, responses):
        if responses is None:
            return
        elif isinstance(responses, t.CommandBase):
            yield responses
        elif callable(responses):
            yield from self._flatten_responses(request, responses(request))
        else:
            for response in responses:
                yield from self._flatten_responses(request, response)

    def reply_once_to(self, request, responses, *, override=False):
        if override:
            self._listeners[request.header].clear()

        future = self.wait_for_response(request)
        called_future = asyncio.get_running_loop().create_future()

        async def replier():
            request = await future

            for response in self._flatten_responses(request, responses):
                await asyncio.sleep(0.001)
                LOGGER.debug("Replying to %s with %s", request, response)
                self.send(response)

            called_future.set_result(request)

        asyncio.create_task(replier())

        return called_future

    def reply_to(self, request, responses, *, override=False):
        if override:
            self._listeners[request.header].clear()

        async def callback(request):
            callback.call_count += 1

            for response in self._flatten_responses(request, responses):
                await asyncio.sleep(0.001)
                LOGGER.debug("Replying to %s with %s", request, response)
                self.send(response)

        callback.call_count = 0

        self.callback_for_response(request, lambda r: asyncio.create_task(callback(r)))

        return callback

    def send(self, response):
        if response is not None and self._uart is not None:
            self._uart.send(response.to_frame(align=self.align_structs))

    def close(self):
        # We don't clear listeners on shutdown
        with swap_attribute(self, "_listeners", {}):
            return super().close()


def load_nvram_json(name):
    obj = json.loads((pathlib.Path(__file__).parent / "nvram" / name).read_text())
    nvram = {}

    for item_name, items in obj.items():
        item_id = ExNvIds[item_name]
        nvram[item_id] = {}

        for sub_name, value in items.items():
            if sub_name.startswith("0x"):
                sub_id = int(sub_name, 16)
            elif "+" in sub_name:
                sub_name, _, offset = sub_name.partition("+")
                sub_id = OsalNvIds[sub_name] + int(offset)
            else:
                sub_id = OsalNvIds[sub_name]

            nvram[item_id][sub_id] = bytes.fromhex(value)

    return nvram


def reply_to(request):
    def inner(function):
        if not hasattr(function, "_reply_to"):
            function._reply_to = []

        function._reply_to.append(request)

        return function

    return inner


class BaseZStackDevice(BaseServerZNP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.active_endpoints = []
        self._nvram = {}

        self.device_state = t.DeviceState.InitializedNotStarted

        # Handle the decorators
        for name in dir(self):
            func = getattr(self, name)

            for req in getattr(func, "_reply_to", []):
                self.reply_to(
                    request=req,
                    responses=[func],
                )

    def nvram_serialize(self, item):
        return NVRAMHelper.serialize(self, item)

    def nvram_deserialize(self, data, item_type):
        return NVRAMHelper.deserialize(self, data, item_type)

    def _unhandled_command(self, command):
        # XXX: check the capabilities with `ping_replier` to use `InvalidSubsystem`?
        LOGGER.warning("Server does not have a handler for command %s", command)

        self.send(
            c.RPCError.CommandNotRecognized.Rsp(
                ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId,
                RequestHeader=command.to_frame().header,
            )
        )

    def connection_lost(self, exc):
        self.active_endpoints.clear()

        return super().connection_lost(exc)

    def _create_network_nvram(self):
        self.nib = self._default_nib()

        empty_key = t.NwkActiveKeyItems(
            Active=t.NwkKeyDesc(
                KeySeqNum=0,
                Key=b"\x00" * 16,
            ),
            FrameCounter=0,
        )

        legacy = self._nvram[ExNvIds.LEGACY]
        legacy[OsalNvIds.STARTUP_OPTION] = self.nvram_serialize(t.StartupOptions.NONE)
        legacy[OsalNvIds.NWKKEY] = self.nvram_serialize(empty_key)
        legacy[OsalNvIds.NWK_ACTIVE_KEY_INFO] = self.nvram_serialize(empty_key.Active)
        legacy[OsalNvIds.NWK_ALTERN_KEY_INFO] = self.nvram_serialize(empty_key.Active)

    def update_device_state(self, state):
        self.device_state = state

        return c.ZDO.StateChangeInd.Callback(State=state)

    def create_nib(self, _=None):
        nib = self.nib
        nib.nwkState = t.NwkState.NWK_ROUTER
        nib.channelList, _ = t.Channels.deserialize(
            self._nvram[ExNvIds.LEGACY][OsalNvIds.CHANLIST]
        )
        nib.nwkLogicalChannel = (list(nib.channelList) + [11])[0]

        if OsalNvIds.APS_USE_EXT_PANID in self._nvram[ExNvIds.LEGACY]:
            epid = self._nvram[ExNvIds.LEGACY][OsalNvIds.APS_USE_EXT_PANID]
        else:
            epid = self._nvram[ExNvIds.LEGACY][OsalNvIds.EXTADDR]

        nib.extendedPANID = epid
        nib.nwkPanId, _ = t.NWK.deserialize(
            self._nvram[ExNvIds.LEGACY][OsalNvIds.PANID]
        )
        nib.nwkKeyLoaded = t.Bool(True)
        nib.nwkDevAddress = 0x0000

        self.nib = nib

        key_info = t.NwkActiveKeyItems(
            Active=t.NwkKeyDesc(
                KeySeqNum=0,
                Key=self._nvram[ExNvIds.LEGACY][OsalNvIds.PRECFGKEY],
            ),
            FrameCounter=2500,
        )

        self._nvram[ExNvIds.LEGACY][
            OsalNvIds.NWK_ACTIVE_KEY_INFO
        ] = self.nvram_serialize(key_info.Active)
        self._nvram[ExNvIds.LEGACY][
            OsalNvIds.NWK_ALTERN_KEY_INFO
        ] = self.nvram_serialize(key_info.Active)
        self._nvram[ExNvIds.LEGACY][OsalNvIds.NWKKEY] = self.nvram_serialize(key_info)

    def _default_nib(self):
        return t.NIB(
            SequenceNum=0,
            PassiveAckTimeout=5,
            MaxBroadcastRetries=2,
            MaxChildren=0,
            MaxDepth=20,
            MaxRouters=0,
            dummyNeighborTable=0,
            BroadcastDeliveryTime=30,
            ReportConstantCost=0,
            RouteDiscRetries=0,
            dummyRoutingTable=0,
            SecureAllFrames=1,
            SecurityLevel=5,
            SymLink=1,
            CapabilityFlags=143,
            TransactionPersistenceTime=7,
            nwkProtocolVersion=2,
            RouteDiscoveryTime=5,
            RouteExpiryTime=30,
            nwkDevAddress=0xFFFE,
            nwkLogicalChannel=0,
            nwkCoordAddress=0xFFFE,
            nwkCoordExtAddress=t.EUI64.convert("00:00:00:00:00:00:00:00"),
            nwkPanId=0xFFFF,
            nwkState=t.NwkState.NWK_INIT,
            channelList=t.Channels.NO_CHANNELS,
            beaconOrder=15,
            superFrameOrder=15,
            scanDuration=0,
            battLifeExt=0,
            allocatedRouterAddresses=0,
            allocatedEndDeviceAddresses=0,
            nodeDepth=0,
            extendedPANID=t.EUI64.convert("00:00:00:00:00:00:00:00"),
            nwkKeyLoaded=False,
            spare1=t.NwkKeyDesc(
                KeySeqNum=0, Key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            ),
            spare2=t.NwkKeyDesc(
                KeySeqNum=0, Key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            ),
            spare3=0,
            spare4=0,
            nwkLinkStatusPeriod=60,
            nwkRouterAgeLimit=3,
            nwkUseMultiCast=False,
            nwkIsConcentrator=True,
            nwkConcentratorDiscoveryTime=120,
            nwkConcentratorRadius=10,
            nwkAllFresh=1,
            nwkManagerAddr=0x0000,
            nwkTotalTransmissions=0,
            nwkUpdateId=0,
        )

    @reply_to(c.ZDO.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000))
    def active_endpoints_request(self, req):
        return [
            c.ZDO.ActiveEpReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.ActiveEpRsp.Callback(
                Src=0x0000,
                Status=t.ZDOStatus.SUCCESS,
                NWK=0x0000,
                ActiveEndpoints=[ep.Endpoint for ep in self.active_endpoints],
            ),
        ]

    @reply_to(c.AF.Register.Req(partial=True))
    def on_endpoint_registration(self, req):
        self.active_endpoints.insert(0, req)

        return c.AF.Register.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.AF.Delete.Req(partial=True))
    def on_endpoint_deletion(self, req):
        self.active_endpoints.remove(req)

        return c.AF.Delete.Rsp(Status=t.Status.SUCCESS)

    @reply_to(
        c.ZDO.SimpleDescReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000, partial=True)
    )
    def on_simple_desc_req(self, req):
        for ep in self.active_endpoints:
            if ep.Endpoint == req.Endpoint:
                return [
                    c.ZDO.SimpleDescReq.Rsp(Status=t.Status.SUCCESS),
                    c.ZDO.SimpleDescRsp.Callback(
                        Src=0x0000,
                        Status=t.ZDOStatus.SUCCESS,
                        NWK=0x0000,
                        SimpleDescriptor=zdo_t.SizePrefixedSimpleDescriptor(
                            endpoint=ep.Endpoint,
                            profile=ep.ProfileId,
                            device_type=ep.DeviceId,
                            device_version=ep.DeviceVersion,
                            input_clusters=ep.InputClusters,
                            output_clusters=ep.OutputClusters,
                        ),
                    ),
                ]

        # Bad things happen when an invalid endpoint ID is passed in
        pytest.fail("Simple descriptor request to an invalid endpoint breaks Z-Stack")

    @reply_to(c.SYS.OSALNVWrite.Req(partial=True))
    @reply_to(c.SYS.OSALNVWriteExt.Req(partial=True))
    def osal_nvram_write(self, req):
        if req.Id == OsalNvIds.POLL_RATE_OLD16:
            self._nvram[ExNvIds.LEGACY][req.Id] = req.Value[:2]
            return req.Rsp(Status=t.Status.SUCCESS)

        if req.Id not in self._nvram[ExNvIds.LEGACY]:
            return req.Rsp(Status=t.Status.INVALID_PARAMETER)

        value = bytearray(self._nvram[ExNvIds.LEGACY][req.Id])

        assert req.Offset + len(req.Value) <= len(value)

        if isinstance(req, c.SYS.OSALNVWrite.Req):
            # XXX: offset is completely ignored for normal writes
            value[0 : len(req.Value)] = req.Value
        else:
            value[req.Offset : req.Offset + len(req.Value)] = req.Value

        self._nvram[ExNvIds.LEGACY][req.Id] = value

        return req.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.OSALNVRead.Req(partial=True))
    @reply_to(c.SYS.OSALNVReadExt.Req(partial=True))
    def osal_nvram_read(self, req):
        if req.Id not in self._nvram[ExNvIds.LEGACY]:
            return req.Rsp(Status=t.Status.INVALID_PARAMETER, Value=t.ShortBytes(b""))

        value = self._nvram[ExNvIds.LEGACY][req.Id]

        if req.Id == OsalNvIds.POLL_RATE_OLD16:
            # XXX: not only is the offset ignored, the wrong command is used to respond
            return c.SYS.OSALNVRead.Rsp(
                Status=t.Status.SUCCESS, Value=t.ShortBytes(value)
            )

        # 248 is the max size we can read at once
        return req.Rsp(
            Status=t.Status.SUCCESS,
            Value=t.ShortBytes(value[req.Offset : req.Offset + 248]),
        )

    @reply_to(c.SYS.OSALNVItemInit.Req(partial=True))
    def osal_nvram_init(self, req):
        if len(req.Value) > req.ItemLen:
            return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.INVALID_PARAMETER)

        self._nvram[ExNvIds.LEGACY][req.Id] = req.Value.ljust(req.ItemLen, b"\xFF")

        return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.NV_ITEM_UNINIT)

    @reply_to(c.SYS.OSALNVLength.Req(partial=True))
    def osal_nvram_length(self, req):
        if req.Id == OsalNvIds.POLL_RATE_OLD16:
            # XXX: the item exists but its length is wrong
            return c.SYS.OSALNVLength.Rsp(ItemLen=0)
        else:
            length = len(self._nvram[ExNvIds.LEGACY].get(req.Id, b""))

        return c.SYS.OSALNVLength.Rsp(ItemLen=length)

    @reply_to(c.SYS.OSALNVDelete.Req(partial=True))
    def osal_nvram_delete(self, req):
        if req.Id not in self._nvram[ExNvIds.LEGACY]:
            return c.SYS.OSALNVDelete.Rsp(Status=t.Status.INVALID_PARAMETER)

        assert req.ItemLen == len(self._nvram[ExNvIds.LEGACY][req.Id])
        self._nvram[ExNvIds.LEGACY].pop(req.Id)

        return c.SYS.OSALNVDelete.Rsp(Status=t.Status.SUCCESS)

    @property
    def nib(self):
        try:
            v = self.nvram_deserialize(
                self._nvram[ExNvIds.LEGACY][OsalNvIds.NIB], t.NIB
            )
        except KeyError:
            v = self._default_nib()

        return v

    @nib.setter
    def nib(self, nib):
        assert isinstance(nib, t.NIB)
        self._nvram[ExNvIds.LEGACY][OsalNvIds.NIB] = self.nvram_serialize(nib)

    @reply_to(c.SYS.ResetReq.Req(Type=t.ResetType.Soft))
    def reset_req(self, request, *, _handle_startup_reset=True):
        if (
            self._nvram.get(ExNvIds.LEGACY, {}).get(OsalNvIds.STARTUP_OPTION)
            is not None
            and _handle_startup_reset
        ):
            startup, _ = t.StartupOptions.deserialize(
                self._nvram[ExNvIds.LEGACY][OsalNvIds.STARTUP_OPTION]
            )

            if startup & t.StartupOptions.ClearState:
                self._create_network_nvram()
                self._nvram[ExNvIds.LEGACY][
                    OsalNvIds.STARTUP_OPTION
                ] = t.StartupOptions.NONE.serialize()

        version = self.version_replier(None)

        return c.SYS.ResetInd.Callback(
            Reason=t.ResetReason.PowerUp,
            TransportRev=version.TransportRev,
            ProductId=version.ProductId,
            MajorRel=version.MajorRel,
            MinorRel=version.MinorRel,
            MaintRel=version.MaintRel,
        )

    @reply_to(c.UTIL.GetDeviceInfo.Req())
    def util_device_info(self, request):
        nwk = 0xFFFE

        if self.device_state == t.DeviceState.StartedAsCoordinator:
            nwk = 0x0000

        return c.UTIL.GetDeviceInfo.Rsp(
            Status=t.Status.SUCCESS,
            IEEE=t.EUI64.deserialize(self._nvram[ExNvIds.LEGACY][OsalNvIds.EXTADDR])[0],
            NWK=nwk,
            DeviceType=t.DeviceTypeCapabilities(7),
            DeviceState=self.device_state,  # dynamic!!!
            AssociatedDevices=[],
        )

    @reply_to(
        c.ZDO.MgmtNWKUpdateReq.Req(Dst=0x0000, DstAddrMode=t.AddrMode.NWK, partial=True)
    )
    def nwk_update_req(self, request):
        valid_channels = [t.Channels.from_channel_list([i]) for i in range(11, 26 + 1)]

        if request.ScanDuration == 0xFE:
            assert request.Channels in valid_channels

            def update_channel():
                nib = self.nib
                nib.nwkLogicalChannel = 11 + valid_channels.index(request.Channels)
                nib.nwkUpdateId += 1

                self.nib = nib

            asyncio.get_running_loop().call_later(0.1, update_channel)

            return c.ZDO.MgmtNWKUpdateReq.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.ZDO.ExtRouteChk.Req(partial=True))
    def zdo_route_check(self, request):
        return c.ZDO.ExtRouteChk.Rsp(Status=c.zdo.RoutingStatus.SUCCESS)


class BaseZStack1CC2531(BaseZStackDevice):
    align_structs = False
    version = 1.2
    code_revision = 20190608

    @reply_to(c.SYS.OSALNVRead.Req(partial=True))
    @reply_to(c.SYS.OSALNVReadExt.Req(partial=True))
    def osal_nvram_read(self, request):
        if is_secure_nvid(request.Id):
            # Reading out key material from the device is not allowed
            return request.Rsp(
                Status=t.Status.INVALID_PARAMETER, Value=t.ShortBytes(b"")
            )

        return super().osal_nvram_read(request)

    @reply_to(c.SAPI.ZBReadConfiguration.Req(partial=True))
    def sapi_zb_read_conf(self, request):
        # But you can still read key material with this command
        read_rsp = super().osal_nvram_read(
            c.SYS.OSALNVRead.Req(Id=OsalNvIds(request.ConfigId), Offset=0)
        )

        return request.Rsp(
            Status=read_rsp.Status, ConfigId=request.ConfigId, Value=read_rsp.Value
        )

    @reply_to(c.SYS.Ping.Req())
    def ping_replier(self, request):
        return c.SYS.Ping.Rsp(
            Capabilities=(
                t.MTCapabilities.APP
                | t.MTCapabilities.UTIL
                | t.MTCapabilities.SAPI
                | t.MTCapabilities.ZDO
                | t.MTCapabilities.AF
                | t.MTCapabilities.SYS
            )
        )

    @reply_to(c.SYS.Version.Req())
    def version_replier(self, request):
        return c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=0,
            MajorRel=2,
            MinorRel=6,
            MaintRel=3,
            CodeRevision=self.code_revision,
            BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_BIN,
            BootloaderRevision=0,
        )

    def _default_nib(self):
        return (
            super()
            ._default_nib()
            .replace(nwkLinkStatusPeriod=15, nwkConcentratorDiscoveryTime=60)
        )

    @reply_to(c.ZDO.StartupFromApp.Req(partial=True))
    def startup_from_app(self, req):
        if self.nib.nwkState == t.NwkState.NWK_ROUTER:
            return [
                c.ZDO.StartupFromApp.Rsp(State=c.zdo.StartupState.RestoredNetworkState),
                self.update_device_state(t.DeviceState.StartedAsCoordinator),
            ]
        else:
            self._create_network_nvram()

            return [
                c.ZDO.StartupFromApp.Rsp(State=c.zdo.StartupState.NewNetworkState),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartedAsCoordinator),
                self.create_nib,
            ]

    @reply_to(c.ZDO.NodeDescReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000))
    def node_desc_responder(self, req):
        return [
            c.ZDO.NodeDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.NodeDescRsp.Callback(
                Src=0x0000,
                Status=t.ZDOStatus.SUCCESS,
                NWK=0x0000,
                NodeDescriptor=c.zdo.NullableNodeDescriptor(
                    byte1=0,
                    byte2=64,
                    mac_capability_flags=143,
                    manufacturer_code=0,
                    maximum_buffer_size=80,
                    maximum_incoming_transfer_size=160,
                    server_mask=1,  # this differs
                    maximum_outgoing_transfer_size=160,
                    descriptor_capability_field=0,
                ),
            ),
        ]

    @reply_to(
        c.ZDO.MgmtPermitJoinReq.Req(AddrMode=t.AddrMode.NWK, Dst=0x0000, partial=True)
    )
    @reply_to(
        c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.Broadcast, Dst=0xFFFC, partial=True
        )
    )
    def permit_join(self, request):
        if request.Duration != 0:
            rsp = [c.ZDO.PermitJoinInd.Callback(Duration=request.Duration)]
        else:
            rsp = []

        return rsp + [
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
            c.ZDO.PermitJoinInd.Callback(Duration=0),
        ]

    @reply_to(c.UTIL.LEDControl.Req(partial=True))
    def led_responder(self, req):
        return req.Rsp(Status=t.Status.SUCCESS)


class BaseZStack3Device(BaseZStackDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._new_channel = None
        self._first_connection = True

    @reply_to(
        c.AppConfig.BDBSetChannel.Req(IsPrimary=False, Channel=t.Channels.NO_CHANNELS)
    )
    def handle_bdb_set_secondary_channel(self, request):
        return c.AppConfig.BDBSetChannel.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.AppConfig.BDBSetChannel.Req(IsPrimary=True, partial=True))
    def handle_bdb_set_primary_channel(self, request):
        self._new_channel = request.Channel

        return c.AppConfig.BDBSetChannel.Rsp(Status=t.Status.SUCCESS)

    @reply_to(
        c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.NWK, Dst=0x0000, Duration=0, partial=True
        )
    )
    @reply_to(
        c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=t.AddrMode.Broadcast, Dst=0xFFFC, Duration=0, partial=True
        )
    )
    def permit_join(self, request):
        return [
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ]

    def create_nib(self, _=None):
        super().create_nib()

        nib = self.nib

        if self._new_channel is not None:
            nib.channelList = self._new_channel
            self._new_channel = None

        self.nib = nib

        self._nvram[ExNvIds.LEGACY][OsalNvIds.BDBNODEISONANETWORK] = b"\x01"

    @reply_to(
        c.AppConfig.BDBStartCommissioning.Req(
            Mode=c.app_config.BDBCommissioningMode.NwkFormation
        )
    )
    def handle_bdb_start_commissioning(self, request):
        if self._nvram[ExNvIds.LEGACY].get(OsalNvIds.BDBNODEISONANETWORK) == b"\x01":
            return [
                c.AppConfig.BDBStartCommissioning.Rsp(Status=t.Status.SUCCESS),
                self.update_device_state(t.DeviceState.StartedAsCoordinator),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    Status=c.app_config.BDBCommissioningStatus.NetworkRestored,
                    Mode=c.app_config.BDBCommissioningMode.NONE,
                    RemainingModes=c.app_config.BDBCommissioningMode.NwkFormation,
                ),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    Status=c.app_config.BDBCommissioningStatus.Success,
                    Mode=c.app_config.BDBCommissioningMode.NwkFormation,
                    RemainingModes=c.app_config.BDBCommissioningMode.NONE,
                ),
            ]
        else:
            self._create_network_nvram()

            return [
                c.AppConfig.BDBStartCommissioning.Rsp(Status=t.Status.SUCCESS),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    Status=c.app_config.BDBCommissioningStatus.InProgress,
                    Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                    RemainingModes=c.app_config.BDBCommissioningMode.NwkFormation,
                ),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartingAsCoordinator),
                self.update_device_state(t.DeviceState.StartedAsCoordinator),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    Status=c.app_config.BDBCommissioningStatus.Success,
                    Mode=c.app_config.BDBCommissioningMode.NwkSteering,
                    RemainingModes=c.app_config.BDBCommissioningMode.NONE,
                ),
                self.create_nib,
            ]

    @reply_to(c.SYS.Ping.Req())
    def ping_replier(self, request):
        return c.SYS.Ping.Rsp(
            Capabilities=(
                t.MTCapabilities.APP_CNF
                | t.MTCapabilities.GP
                | t.MTCapabilities.UTIL
                | t.MTCapabilities.ZDO
                | t.MTCapabilities.AF
                | t.MTCapabilities.SYS
            )
        )

    def connection_made(self):
        super().connection_made()

        if not self._first_connection:
            return

        self._first_connection = False

        # Z-Stack 3 devices send a callback when they're first used
        asyncio.get_running_loop().call_soon(
            self.send, self.reset_req(None, _handle_startup_reset=False)
        )


class BaseLaunchpadCC26X2R1(BaseZStack3Device):
    version = 3.30
    align_structs = True
    code_revision = 20200805

    def _create_network_nvram(self):
        super()._create_network_nvram()
        self._nvram[ExNvIds.LEGACY][OsalNvIds.APS_LINK_KEY_TABLE] = b"\xFF" * 20
        self._nvram[ExNvIds.ADDRMGR] = {
            addr: self.nvram_serialize(const.EMPTY_ADDR_MGR_ENTRY)
            for addr in range(0x0000, 0x0100 + 1)
        }

    def create_nib(self, _=None):
        super().create_nib()

        self._nvram[ExNvIds.NWK_SEC_MATERIAL_TABLE][0x0000] = self.nvram_serialize(
            t.NwkSecMaterialDesc(
                FrameCounter=2500,
                ExtendedPanID=self.nib.extendedPANID,
            )
        )

        self._nvram[ExNvIds.NWK_SEC_MATERIAL_TABLE][0x0001] = self.nvram_serialize(
            t.NwkSecMaterialDesc(
                FrameCounter=0xFFFFFFFF,
                ExtendedPanID=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
            )
        )

    @reply_to(c.SYS.NVLength.Req(SysId=NvSysIds.ZSTACK, partial=True))
    def nvram_length(self, req):
        value = self._nvram.get(ExNvIds(req.ItemId), {}).get(req.SubId, b"")

        return c.SYS.NVLength.Rsp(Length=len(value))

    @reply_to(c.SYS.NVRead.Req(SysId=NvSysIds.ZSTACK, partial=True))
    def nvram_read(self, req):
        if req.SubId not in self._nvram.get(ExNvIds(req.ItemId), {}):
            return c.SYS.NVRead.Rsp(Status=t.Status.FAILURE, Value=b"")

        value = self._nvram.setdefault(req.ItemId, {})[req.SubId]

        return c.SYS.NVRead.Rsp(
            Status=t.Status.SUCCESS, Value=value[req.Offset :][: req.Length]
        )

    @reply_to(c.SYS.NVWrite.Req(SysId=NvSysIds.ZSTACK, partial=True))
    def nvram_write(self, req):
        if req.SubId not in self._nvram.get(ExNvIds(req.ItemId), {}):
            return c.SYS.NVWrite.Rsp(Status=t.Status.FAILURE)

        value = bytearray(self._nvram[req.ItemId][req.SubId])
        value[req.Offset : req.Offset + len(req.Value)] = req.Value
        self._nvram.setdefault(req.ItemId, {})[req.SubId] = bytes(value)

        return c.SYS.NVWrite.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.NVCreate.Req(SysId=NvSysIds.ZSTACK, partial=True))
    def nvram_create(self, req):
        if req.SubId in self._nvram.get(ExNvIds(req.ItemId), {}):
            return c.SYS.NVCreate.Rsp(Status=t.Status.SUCCESS)

        self._nvram.setdefault(req.ItemId, {})[req.SubId] = bytes(req.Length)

        return c.SYS.NVCreate.Rsp(Status=t.Status.NV_ITEM_UNINIT)

    @reply_to(c.SYS.NVDelete.Req(SysId=NvSysIds.ZSTACK, partial=True))
    def nvram_delete(self, req):
        try:
            self._nvram.get(ExNvIds(req.ItemId), {}).pop(req.SubId)
            return c.SYS.NVDelete.Rsp(Status=t.Status.SUCCESS)
        except KeyError:
            return c.SYS.NVDelete.Rsp(Status=t.Status.NV_OPER_FAILED)

    @reply_to(c.SYS.Version.Req())
    def version_replier(self, request):
        return c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=1,
            MajorRel=2,
            MinorRel=7,
            MaintRel=1,
            CodeRevision=self.code_revision,
            BootloaderBuildType=c.sys.BootloaderBuildType.NON_BOOTLOADER_BUILD,
            BootloaderRevision=0xFFFFFFFF,
        )

    @reply_to(c.ZDO.NodeDescReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000))
    def node_desc_responder(self, req):
        return [
            c.ZDO.NodeDescReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.NodeDescRsp.Callback(
                Src=0x0000,
                Status=t.ZDOStatus.SUCCESS,
                NWK=0x0000,
                NodeDescriptor=c.zdo.NullableNodeDescriptor(
                    byte1=0,
                    byte2=64,
                    mac_capability_flags=143,
                    manufacturer_code=0,
                    maximum_buffer_size=80,
                    maximum_incoming_transfer_size=160,
                    server_mask=11265,
                    maximum_outgoing_transfer_size=160,
                    descriptor_capability_field=0,
                ),
            ),
        ]

    @reply_to(c.UTIL.LEDControl.Req(partial=True))
    def led_responder(self, req):
        # XXX: Yes, there is *no response*
        return


class BaseZStack3CC2531(BaseZStack3Device):
    version = 3.0
    align_structs = False
    code_revision = 20190425

    def _create_network_nvram(self):
        super()._create_network_nvram()
        self._nvram[ExNvIds.LEGACY][OsalNvIds.APS_LINK_KEY_TABLE] = b"\xFF" * 17
        self._nvram[ExNvIds.LEGACY][OsalNvIds.ADDRMGR] = 124 * self.nvram_serialize(
            const.EMPTY_ADDR_MGR_ENTRY
        )

    def create_nib(self, _=None):
        super().create_nib()

        self._nvram[ExNvIds.LEGACY][
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START
        ] = self.nvram_serialize(
            t.NwkSecMaterialDesc(
                FrameCounter=2500,
                ExtendedPanID=self.nib.extendedPANID,
            )
        )

        self._nvram[ExNvIds.LEGACY][
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END
        ] = self.nvram_serialize(
            t.NwkSecMaterialDesc(
                FrameCounter=0xFFFFFFFF,
                ExtendedPanID=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
            )
        )

    @reply_to(c.SYS.Version.Req())
    def version_replier(self, request):
        return c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=2,
            MajorRel=2,
            MinorRel=7,
            MaintRel=2,
            CodeRevision=self.code_revision,
            BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_BIN,
            BootloaderRevision=0,
        )

    node_desc_responder = BaseZStack1CC2531.node_desc_responder

    @reply_to(c.UTIL.LEDControl.Req(partial=True))
    def led_responder(self, req):
        return req.Rsp(Status=t.Status.SUCCESS)


class FormedLaunchpadCC26X2R1(BaseLaunchpadCC26X2R1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2652R-ZStack4.formed.json")


class ResetLaunchpadCC26X2R1(BaseLaunchpadCC26X2R1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2652R-ZStack4.reset.json")


class FormedZStack3CC2531(BaseZStack3CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2531-ZStack3.formed.json")


class ResetZStack3CC2531(BaseZStack3CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2531-ZStack3.reset.json")


class FormedZStack1CC2531(BaseZStack1CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2531-ZStack1.formed.json")


class ResetZStack1CC2531(BaseZStack1CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nvram = load_nvram_json("CC2531-ZStack1.reset.json")


EMPTY_DEVICES = [
    ResetLaunchpadCC26X2R1,
    ResetZStack3CC2531,
    ResetZStack1CC2531,
]

FORMED_DEVICES = [
    FormedLaunchpadCC26X2R1,
    FormedZStack3CC2531,
    FormedZStack1CC2531,
]

FORMED_ZSTACK3_DEVICES = [FormedLaunchpadCC26X2R1, FormedZStack3CC2531]
assert all(d in FORMED_DEVICES for d in FORMED_ZSTACK3_DEVICES)

ALL_DEVICES = EMPTY_DEVICES + FORMED_DEVICES
