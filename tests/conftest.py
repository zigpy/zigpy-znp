import json
import asyncio
import logging
import pathlib
import contextlib

import pytest

try:
    # Python 3.8 already has this
    from unittest.mock import AsyncMock as CoroutineMock  # noqa: F401
except ImportError:
    from asynctest import CoroutineMock  # noqa: F401

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.uart import ZnpMtProtocol
from zigpy_znp.znp.nib import NIB, CC2531NIB, NwkState8, NwkKeyDesc, parse_nib
from zigpy_znp.types.nvids import NvSysIds, NwkNvIds, OsalExNvIds, is_secure_nvid
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
        LOGGER.error("Closing %s", self)
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
    double_connect = False

    mocker.patch("zigpy_znp.api.AFTER_CONNECT_DELAY", 0.001)
    mocker.patch("zigpy_znp.api.STARTUP_DELAY", 0.001)
    mocker.patch("zigpy_znp.uart.RTS_TOGGLE_DELAY", 0)

    def inner(server_cls, config=None):
        if config is None:
            config = config_for_port_path(FAKE_SERIAL_PORT)

        server = server_cls(config)

        server.port_path = FAKE_SERIAL_PORT
        server._uart = None

        def passthrough_serial_conn(loop, protocol_factory, url, *args, **kwargs):
            LOGGER.info("Intercepting serial connection to %s", url)

            assert url == FAKE_SERIAL_PORT

            # No double connections!
            if any([t._is_connected for t in transports]):
                nonlocal double_connect
                double_connect = True

                assert False, "Refusing to connect twice"

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

    # Ensure there are no leaks
    if transports:
        assert not any([t._is_connected for t in transports]), "Connection leaked"

    # and no double connects
    if double_connect:
        assert False, "Cannot connect twice"


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

        return app, make_znp_server(server_cls=server_cls, config=server_config)

    return inner


class BaseServerZNP(ZNP):
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

    def reply_once_to(self, request, responses):
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

    def reply_to(self, request, responses):
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
        if response is not None:
            self._uart.send(response.to_frame())

    def close(self):
        # We don't clear listeners on shutdown
        with swap_attribute(self, "_listeners", {}):
            return super().close()


def load_nvram_json(name):
    obj = json.loads((pathlib.Path(__file__).parent / "nvram" / name).read_text())

    return {
        "nwk": {NwkNvIds[k]: bytes.fromhex(v) for k, v in obj["nwk"].items()},
        "osal": {OsalExNvIds[k]: bytes.fromhex(v) for k, v in obj["osal"].items()},
    }


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
        self.nib = None
        self.nvram = {}

        self.device_state = t.DeviceState.InitializedNotStarted

        # Handle the decorators
        for name in dir(self):
            func = getattr(self, name)

            for req in getattr(func, "_reply_to", []):
                self.reply_to(
                    request=req,
                    responses=[func],
                )

    def _unhandled_command(self, command):
        # XXX: check the capabilities with `ping_replier` to use `InvalidSubsystem`?
        self.send(
            c.RPCError.CommandNotRecognized.Rsp(
                ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId,
                RequestHeader=command.to_frame().header,
            )
        )

    def connection_lost(self, exc):
        self.active_endpoints.clear()

        return super().connection_lost(exc)

    @reply_to(c.ZDO.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000))
    def active_endpoints_request(self, req):
        return [
            c.ZDO.ActiveEpReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.ActiveEpRsp.Callback(
                Src=0x0000,
                Status=t.ZDOStatus.SUCCESS,
                NWK=0x0000,
                ActiveEndpoints=self.active_endpoints,
            ),
        ]

    @reply_to(c.AF.Register.Req(partial=True))
    def on_endpoint_registration(self, req):
        assert req.Endpoint not in self.active_endpoints

        self.active_endpoints.append(req.Endpoint)
        self.active_endpoints.sort(reverse=True)

        return c.AF.Register.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.AF.Delete.Req(partial=True))
    def on_endpoint_deletion(self, req):
        assert req.Endpoint in self.active_endpoints

        self.active_endpoints.remove(req.Endpoint)

        return c.AF.Delete.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.OSALNVWrite.Req(partial=True))
    @reply_to(c.SYS.OSALNVWriteExt.Req(partial=True))
    def osal_nvram_write(self, req):
        if req.Id == NwkNvIds.POLL_RATE_OLD16:
            self.nvram["nwk"][req.Id] = req.Value[:2]
            return req.Rsp(Status=t.Status.SUCCESS)

        if req.Id not in self.nvram["nwk"] and req.Id != NwkNvIds.NIB:
            return req.Rsp(Status=t.Status.INVALID_PARAMETER)

        if req.Id == NwkNvIds.NIB:
            assert req.Offset == 0
            assert len(req.Value) == len(self.nib.serialize())

            self.nib, _ = type(self.nib).deserialize(req.Value)
        else:
            value = bytearray(self.nvram["nwk"][req.Id])

            assert req.Offset + len(req.Value) <= len(value)

            if isinstance(req, c.SYS.OSALNVWrite.Req):
                # XXX: offset is completely ignored for normal writes
                value[0 : len(req.Value)] = req.Value
            else:
                value[req.Offset : req.Offset + len(req.Value)] = req.Value

            self.nvram["nwk"][req.Id] = value

        return req.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.OSALNVRead.Req(partial=True))
    @reply_to(c.SYS.OSALNVReadExt.Req(partial=True))
    def osal_nvram_read(self, req):
        if req.Id not in self.nvram["nwk"] and req.Id != NwkNvIds.NIB:
            return req.Rsp(Status=t.Status.INVALID_PARAMETER, Value=t.ShortBytes(b""))

        if req.Id == NwkNvIds.NIB:
            if self.nib is None:
                return req.Rsp(
                    Status=t.Status.INVALID_PARAMETER, Value=t.ShortBytes(b"")
                )

            value = self.nib.serialize()
        else:
            value = self.nvram["nwk"][req.Id]

        if req.Id == NwkNvIds.POLL_RATE_OLD16:
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

        self.nvram["nwk"][req.Id] = req.Value.ljust(req.ItemLen, b"\xFF")

        return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.NV_ITEM_UNINIT)

    @reply_to(c.SYS.OSALNVLength.Req(partial=True))
    def osal_nvram_length(self, req):
        if req.Id == NwkNvIds.NIB and self.nib is not None:
            length = len(self.nib.serialize())
        elif req.Id == NwkNvIds.POLL_RATE_OLD16:
            # XXX: the item exists but its length is wrong
            return c.SYS.OSALNVLength.Rsp(ItemLen=0)
        else:
            length = len(self.nvram["nwk"].get(req.Id, b""))

        return c.SYS.OSALNVLength.Rsp(ItemLen=length)

    @reply_to(c.SYS.OSALNVDelete.Req(partial=True))
    def osal_nvram_delete(self, req):
        if req.Id not in self.nvram["nwk"]:
            return c.SYS.OSALNVDelete.Rsp(Status=t.Status.INVALID_PARAMETER)

        assert req.ItemLen == len(self.nvram["nwk"][req.Id])
        self.nvram["nwk"].pop(req.Id)

        return c.SYS.OSALNVDelete.Rsp(Status=t.Status.SUCCESS)

    def default_nib(self):
        if "nib" not in self.nvram["nwk"]:
            return self._default_nib()

        return parse_nib(self.nvram["nwk"][NwkNvIds.NIB])

    @reply_to(c.SYS.ResetReq.Req(Type=t.ResetType.Soft))
    def reset_req(self, request):
        version = self.version_replier(None)

        return c.SYS.ResetInd.Callback(
            Reason=t.ResetReason.PowerUp,
            TransportRev=version.TransportRev,
            ProductId=version.ProductId,
            MajorRel=version.MajorRel,
            MinorRel=version.MinorRel,
            MaintRel=version.MaintRel,
        )

    @reply_to(c.Util.GetDeviceInfo.Req())
    def util_device_info(self, request):
        return c.Util.GetDeviceInfo.Rsp(
            Status=t.Status.SUCCESS,
            IEEE=t.EUI64.deserialize(self.nvram["nwk"][NwkNvIds.EXTADDR])[0],
            NWK=t.NWK(0xFFFE),  # ???
            DeviceType=t.DeviceTypeCapabilities(7),  # fixed
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
                self.nib.nwkLogicalChannel = 11 + valid_channels.index(request.Channels)
                self.nib.nwkUpdateId += 1

            asyncio.get_running_loop().call_later(0.1, update_channel)

            return c.ZDO.MgmtNWKUpdateReq.Rsp(Status=t.Status.SUCCESS)


class BaseZStack1CC2531(BaseZStackDevice):
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
            c.SYS.OSALNVRead.Req(Id=NwkNvIds(request.ConfigId), Offset=0)
        )

        return request.Rsp(
            Status=read_rsp.Status, ConfigId=request.ConfigId, Value=read_rsp.Value
        )

    @reply_to(c.SYS.Ping.Req())
    def ping_replier(self, request):
        return c.SYS.Ping.Rsp(
            Capabilities=(
                t.MTCapabilities.CAP_APP
                | t.MTCapabilities.CAP_UTIL
                | t.MTCapabilities.CAP_SAPI
                | t.MTCapabilities.CAP_ZDO
                | t.MTCapabilities.CAP_AF
                | t.MTCapabilities.CAP_SYS
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
            CodeRevision=20190608,
            BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_BIN,
            BootloaderRevision=0,
        )

    def _default_nib(self):
        return CC2531NIB.deserialize(
            load_nvram_json("CC2531-ZStack1.reset.json")["nwk"][NwkNvIds.NIB]
        )[0]

    @reply_to(c.ZDO.StartupFromApp.Req(partial=True))
    def startup_from_app(self, req):
        if self.nib.nwkState == NwkState8.NWK_ROUTER:
            return [
                c.ZDO.StartupFromApp.Rsp(State=c.zdo.StartupState.RestoredNetworkState),
                c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator),
            ]
        else:

            def update_logical_channel(req):
                self.nib.nwkState = NwkState8.NWK_ROUTER
                self.nib.channelList, _ = t.Channels.deserialize(
                    self.nvram["nwk"][NwkNvIds.CHANLIST]
                )
                self.nib.nwkLogicalChannel = 15
                self.nib.nwkPanId, _ = t.NWK.deserialize(
                    self.nvram["nwk"][NwkNvIds.PANID]
                )

                return []

            return [
                c.ZDO.StartupFromApp.Rsp(State=c.zdo.StartupState.NewNetworkState),
                c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartingAsCoordinator
                ),
                c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartingAsCoordinator
                ),
                c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartingAsCoordinator
                ),
                c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator),
                update_logical_channel,
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
            AddrMode=t.AddrMode.NWK, Dst=0x0000, Duration=0, TCSignificance=1
        )
    )
    def permit_join(self, request):
        return [
            c.ZDO.MgmtPermitJoinReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, Status=t.ZDOStatus.SUCCESS),
        ]

    def update_device_state(self, state):
        self.device_state = state

        return c.ZDO.StateChangeInd.Callback(State=state)

    @reply_to(
        c.AppConfig.BDBStartCommissioning.Req(
            Mode=c.app_config.BDBCommissioningMode.NwkFormation
        )
    )
    def handle_bdb_start_commissioning(self, request):
        if self.nvram["nwk"][NwkNvIds.BDBNODEISONANETWORK] == b"\x01":
            return [
                c.AppConfig.BDBStartCommissioning.Rsp(Status=t.Status.SUCCESS),
                self.update_device_state(t.DeviceState.StartedAsCoordinator),
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
            ]
        else:

            def update_logical_channel(req):
                if self.nib is None:
                    self.nib = self.default_nib()

                if self._new_channel is not None:
                    self.nib.channelList = self._new_channel
                    self._new_channel = None

                self.nib.nwkLogicalChannel = 15
                self.nvram["nwk"][NwkNvIds.BDBNODEISONANETWORK] = b"\x01"

                return []

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
                update_logical_channel,
            ]

    @reply_to(c.SYS.Ping.Req())
    def ping_replier(self, request):
        return c.SYS.Ping.Rsp(
            Capabilities=(
                t.MTCapabilities.CAP_APP_CNF
                | t.MTCapabilities.CAP_GP
                | t.MTCapabilities.CAP_UTIL
                | t.MTCapabilities.CAP_ZDO
                | t.MTCapabilities.CAP_AF
                | t.MTCapabilities.CAP_SYS
            )
        )

    def connection_made(self):
        super().connection_made()

        if not self._first_connection:
            return

        self._first_connection = False

        # Z-Stack 3 devices send a callback when they're first used
        asyncio.get_running_loop().call_soon(self.send, self.reset_req(None))


class BaseLaunchpadCC26X2R1(BaseZStack3Device):
    @reply_to(c.SYS.NVLength.Req(SysId=NvSysIds.ZSTACK, SubId=0, partial=True))
    def nvram_length(self, req):
        value = self.nvram["osal"].get(req.ItemId, b"")

        return c.SYS.NVLength.Rsp(Length=len(value))

    @reply_to(c.SYS.NVRead.Req(SysId=NvSysIds.ZSTACK, SubId=0, partial=True))
    def nvram_read(self, req):
        if req.ItemId not in self.nvram["osal"]:
            return c.SYS.NVRead.Rsp(Status=t.Status.FAILURE, Value=b"")

        value = self.nvram["osal"][req.ItemId]

        return c.SYS.NVRead.Rsp(
            Status=t.Status.SUCCESS, Value=value[req.Offset :][: req.Length]
        )

    @reply_to(c.SYS.NVWrite.Req(SysId=NvSysIds.ZSTACK, SubId=0, partial=True))
    def nvram_write(self, req):
        if req.ItemId not in self.nvram["osal"]:
            return c.SYS.NVWrite.Rsp(Status=t.Status.FAILURE)

        value = bytearray(self.nvram["osal"][req.ItemId])
        value[req.Offset : req.Offset + len(req.Value)] = req.Value
        self.nvram["osal"][OsalExNvIds(req.ItemId)] = bytes(value)

        return c.SYS.NVWrite.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.NVCreate.Req(SysId=NvSysIds.ZSTACK, SubId=0, partial=True))
    def nvram_create(self, req):
        if req.ItemId in self.nvram["osal"]:
            return c.SYS.NVCreate.Rsp(Status=t.Status.SUCCESS)

        self.nvram["osal"][OsalExNvIds(req.ItemId)] = bytes(req.Length)

        return c.SYS.NVCreate.Rsp(Status=t.Status.SUCCESS)

    @reply_to(c.SYS.Version.Req())
    def version_replier(self, request):
        return c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=1,
            MajorRel=2,
            MinorRel=7,
            MaintRel=1,
            CodeRevision=20200805,
            BootloaderBuildType=c.sys.BootloaderBuildType.NON_BOOTLOADER_BUILD,
            BootloaderRevision=0xFFFFFFFF,
        )

    def _default_nib(self):
        return NIB.deserialize(
            load_nvram_json("CC2652R-ZStack4.reset.json")["nwk"][NwkNvIds.NIB]
        )[0]

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


class BaseZStack3CC2531(BaseZStack3Device):
    @reply_to(c.SYS.Version.Req())
    def version_replier(self, request):
        return c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=2,
            MajorRel=2,
            MinorRel=7,
            MaintRel=2,
            CodeRevision=20190425,
            BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_BIN,
            BootloaderRevision=0,
        )

    def _default_nib(self):
        return CC2531NIB(
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
            nwkState=NwkState8.NWK_INIT,
            channelList=t.Channels.NO_CHANNELS,
            beaconOrder=15,
            superFrameOrder=15,
            scanDuration=0,
            battLifeExt=0,
            allocatedRouterAddresses=0,
            allocatedEndDeviceAddresses=0,
            nodeDepth=0,
            extendedPANID=t.EUI64.convert("00:00:00:00:00:00:00:00"),
            nwkKeyLoaded=t.Bool.false,
            spare1=NwkKeyDesc(
                keySeqNum=0, key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            ),
            spare2=NwkKeyDesc(
                keySeqNum=0, key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            ),
            spare3=0,
            spare4=0,
            nwkLinkStatusPeriod=60,
            nwkRouterAgeLimit=3,
            nwkUseMultiCast=t.Bool.false,
            nwkIsConcentrator=t.Bool.true,
            nwkConcentratorDiscoveryTime=120,
            nwkConcentratorRadius=10,
            nwkAllFresh=1,
            nwkManagerAddr=0x0000,
            nwkTotalTransmissions=0,
            nwkUpdateId=0,
        )

    node_desc_responder = BaseZStack1CC2531.node_desc_responder


class BlankLaunchpadCC26X2R1(BaseLaunchpadCC26X2R1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2652R-ZStack4.blank.json")
        self.nib = None


class FormedLaunchpadCC26X2R1(BaseLaunchpadCC26X2R1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2652R-ZStack4.formed.json")
        self.nib, _ = NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


class ResetLaunchpadCC26X2R1(BaseLaunchpadCC26X2R1):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2652R-ZStack4.reset.json")
        self.nib, _ = NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


class BlankZStack3CC2531(BaseZStack3CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack3.blank.json")
        self.nib = None


class FormedZStack3CC2531(BaseZStack3CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack3.formed.json")
        self.nib, _ = CC2531NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


class ResetZStack3CC2531(BaseZStack3CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack3.reset.json")
        self.nib = None


class BlankZStack1CC2531(BaseZStack1CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack1.blank.json")
        self.nib, _ = CC2531NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


class FormedZStack1CC2531(BaseZStack1CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack1.formed.json")
        self.nib, _ = CC2531NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


class ResetZStack1CC2531(BaseZStack1CC2531):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.nvram = load_nvram_json("CC2531-ZStack1.reset.json")
        self.nib, _ = CC2531NIB.deserialize(self.nvram["nwk"][NwkNvIds.NIB])


EMPTY_DEVICES = [
    BlankLaunchpadCC26X2R1,
    ResetLaunchpadCC26X2R1,
    BlankZStack3CC2531,
    ResetZStack3CC2531,
    BlankZStack1CC2531,
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
