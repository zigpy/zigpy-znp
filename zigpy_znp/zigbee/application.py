import os
import typing
import asyncio
import logging
import itertools
import async_timeout

import zigpy.util
import zigpy.types
import zigpy.device
import zigpy.config
import zigpy.application
import zigpy.profiles
import zigpy.zcl.foundation

from zigpy.zcl import clusters
from zigpy.types import (
    ExtendedPanId,
    deserialize as list_deserialize,
    Struct as ZigpyStruct,
)
from zigpy.zdo.types import ZDOCmd, ZDOHeader, CLUSTERS as ZDO_CLUSTERS
from zigpy.exceptions import DeliveryError

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.znp.nib import parse_nib
from zigpy_znp.exceptions import InvalidCommandResponse
from zigpy_znp.types.nvids import NwkNvIds


ZDO_ENDPOINT = 0
ZDO_REQUEST_TIMEOUT = 10  # seconds
DATA_CONFIRM_TIMEOUT = 5  # seconds
LOGGER = logging.getLogger(__name__)


ZDO_COMPLEX_CONVERTERS = {
    ZDOCmd.Node_Desc_req: (
        (
            lambda addr, device, NWKAddrOfInterest: c.ZDO.NodeDescReq.Req(
                DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (lambda addr: c.ZDO.NodeDescRsp.Callback(partial=True, Src=addr)),
        (
            lambda rsp: (
                ZDOCmd.Node_Desc_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "NodeDescriptor": rsp.NodeDescriptor,
                },
            )
        ),
    ),
    ZDOCmd.Active_EP_req: (
        (
            lambda addr, device, NWKAddrOfInterest: c.ZDO.ActiveEpReq.Req(
                DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (lambda addr: c.ZDO.ActiveEpRsp.Callback(partial=True, Src=addr)),
        (
            lambda rsp: (
                ZDOCmd.Active_EP_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "ActiveEPList": rsp.ActiveEndpoints,
                },
            )
        ),
    ),
    ZDOCmd.Simple_Desc_req: (
        (
            lambda addr, device, NWKAddrOfInterest, EndPoint: (
                c.ZDO.SimpleDescReq.Req(
                    DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest, Endpoint=EndPoint
                )
            )
        ),
        (lambda addr: c.ZDO.SimpleDescRsp.Callback(partial=True, Src=addr)),
        (
            lambda rsp: (
                ZDOCmd.Simple_Desc_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "SimpleDescriptor": rsp.SimpleDescriptor,
                },
            )
        ),
    ),
    ZDOCmd.Mgmt_Permit_Joining_req: (
        (
            lambda addr, device, PermitDuration, TC_Significant: (
                c.ZDO.MgmtPermitJoinReq.Req(
                    AddrMode=t.AddrMode.NWK,
                    Dst=addr,
                    Duration=PermitDuration,
                    TCSignificance=TC_Significant,
                )
            )
        ),
        (lambda addr: c.ZDO.MgmtPermitJoinRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Mgmt_Permit_Joining_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Leave_req: (
        (
            lambda addr, device, DeviceAddress, Options: c.ZDO.MgmtLeaveReq.Req(
                DstAddr=addr,
                IEEE=device.ieee,
                RemoveChildren_Rejoin=c.zdo.LeaveOptions(Options),
            )
        ),
        (lambda addr: c.ZDO.MgmtLeaveRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Mgmt_Leave_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Bind_req: (
        (
            lambda addr, device, SrcAddress, SrcEndpoint, ClusterID, DstAddress: (
                c.ZDO.BindReq.Req(
                    Dst=addr,
                    Src=SrcAddress,
                    SrcEndpoint=SrcEndpoint,
                    ClusterId=ClusterID,
                    Address=DstAddress,
                )
            )
        ),
        (lambda addr: c.ZDO.BindRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Bind_rsp, {"Status": rsp.Status})),
    ),
}


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA
    SCHEMA_DEVICE = conf.SCHEMA_DEVICE

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=conf.CONFIG_SCHEMA(config))

        self._znp = None

        # It's simpler to work with Task objects if they're never actually None
        self._reconnect_task = asyncio.Future()
        self._reconnect_task.cancel()

    @classmethod
    async def probe(cls, device_config: conf.ConfigType) -> bool:
        znp = ZNP(conf.CONFIG_SCHEMA({conf.CONF_DEVICE: device_config}))
        LOGGER.debug("Probing %s", znp._port_path)

        try:
            await znp.connect()
            return True
        except Exception as e:
            LOGGER.warning(
                "Failed to probe ZNP radio with config %s", device_config, exc_info=e
            )
            return False
        finally:
            znp.close()

    def _receive_zdo_message(
        self, cluster: ZDOCmd, *, tsn: t.uint8_t, sender, **zdo_kwargs
    ) -> None:
        field_names, field_types = ZDO_CLUSTERS[cluster]
        assert set(zdo_kwargs) == set(field_names)

        # Type cast all of the field args and kwargs
        zdo_args = []

        for name, field_type in zip(field_names, field_types):
            zdo_arg = zdo_kwargs[name]

            if issubclass(field_type, ZigpyStruct) and hasattr(ZigpyStruct, "_fields"):
                # Old-style zigpy structs do not have "copy constructors"
                new_obj = field_type()

                for field_name, _ in new_obj._fields:
                    setattr(new_obj, field_name, getattr(zdo_arg, field_name))
            else:
                new_obj = field_type(zdo_arg)

            zdo_args.append(zdo_arg)

        message = t.serialize_list([t.uint8_t(tsn)] + zdo_args)

        LOGGER.debug("Pretending we received a ZDO message: %s", message)

        self.handle_message(
            sender=sender,
            profile=zigpy.profiles.zha.PROFILE_ID,
            cluster=cluster,
            src_ep=ZDO_ENDPOINT,
            dst_ep=ZDO_ENDPOINT,
            message=message,
        )

    def on_zdo_relays_message(self, msg: c.ZDO.SrcRtgInd.Callback) -> None:
        LOGGER.info("ZDO device relays: %s", msg)
        device = self.get_device(nwk=msg.DstAddr)
        device.relays = msg.Relays

    def on_zdo_device_announce(self, msg: c.ZDO.EndDeviceAnnceInd.Callback) -> None:
        LOGGER.info("ZDO device announce: %s", msg)

        self._receive_zdo_message(
            cluster=ZDOCmd.Device_annce,
            tsn=0xFF,
            sender=self.get_device(ieee=msg.IEEE),
            NWKAddr=msg.NWK,
            IEEEAddr=msg.IEEE,
            Capability=msg.Capabilities,
        )

    def on_tc_device_join(self, msg: c.ZDO.TCDevInd.Callback) -> None:
        LOGGER.info("TC device join: %s", msg)
        self.handle_join(nwk=msg.SrcNwk, ieee=msg.SrcIEEE, parent_nwk=msg.ParentNwk)

    def on_zdo_device_leave(self, msg: c.ZDO.LeaveInd.Callback) -> None:
        LOGGER.info("ZDO device left: %s", msg)
        self.handle_leave(nwk=msg.NWK, ieee=msg.IEEE)

    def on_af_message(self, msg: c.AF.IncomingMsg.Callback) -> None:
        try:
            device = self.get_device(nwk=msg.SrcAddr)
        except KeyError:
            LOGGER.warning(
                "Received an AF message from an unknown device: 0x%04x", msg.SrcAddr
            )
            return

        device.radio_details(lqi=msg.LQI, rssi=None)

        self.handle_message(
            sender=device,
            profile=zigpy.profiles.zha.PROFILE_ID,
            cluster=msg.ClusterId,
            src_ep=msg.SrcEndpoint,
            dst_ep=msg.DstEndpoint,
            message=msg.Data,
        )

    async def shutdown(self):
        """Shutdown application."""

        self._reconnect_task.cancel()

        if self._znp is not None:
            self._znp.close()

    def _bind_callbacks(self, api):
        api.callback_for_response(
            c.AF.IncomingMsg.Callback(partial=True), self.on_af_message
        )

        # ZDO requests need to be handled explicitly
        api.callback_for_response(
            c.ZDO.EndDeviceAnnceInd.Callback(partial=True), self.on_zdo_device_announce,
        )

        api.callback_for_response(
            c.ZDO.TCDevInd.Callback.Callback(partial=True), self.on_tc_device_join,
        )

        api.callback_for_response(
            c.ZDO.LeaveInd.Callback(partial=True), self.on_zdo_device_leave
        )

        api.callback_for_response(
            c.ZDO.SrcRtgInd.Callback(partial=True), self.on_zdo_relays_message
        )

    async def _reconnect(self) -> None:
        for attempt in itertools.count(start=1):
            LOGGER.debug(
                "Trying to reconnect to %s, attempt %d",
                self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH],
                attempt,
            )

            try:
                await self.startup()

                return
            except Exception as e:
                LOGGER.error("Failed to reconnect", exc_info=e)
                await asyncio.sleep(
                    self._config[conf.CONF_ZNP_CONFIG][
                        conf.CONF_AUTO_RECONNECT_RETRY_DELAY
                    ]
                )

    def connection_lost(self, exc):
        self._znp = None

        # exc=None means that the connection was closed
        if exc is None:
            LOGGER.debug("Connection was purposefully closed. Not reconnecting.")
            return

        # Reconnect in the background using our previously-detected port.
        LOGGER.debug("Starting background reconnection task")

        self._reconnect_task.cancel()
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _register_endpoint(
        self,
        endpoint,
        profile_id=zigpy.profiles.zha.PROFILE_ID,
        device_id=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
        device_version=0b0000,
        latency_req=c.af.LatencyReq.NoLatencyReqs,
        input_clusters=[],
        output_clusters=[],
    ):
        return await self._znp.request(
            c.AF.Register.Req(
                Endpoint=endpoint,
                ProfileId=profile_id,
                DeviceId=device_id,
                DeviceVersion=device_version,
                LatencyReq=latency_req,  # completely ignored by Z-Stack
                InputClusters=input_clusters,
                OutputClusters=output_clusters,
            ),
            RspStatus=t.Status.SUCCESS,
        )

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""

        znp = ZNP(self.config)
        znp.set_application(self)
        self._bind_callbacks(znp)
        await znp.connect()

        self._znp = znp

        # XXX: To make sure we don't switch to the wrong device upon reconnect,
        #      update our config to point to the last-detected port.
        if self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH] == "auto":
            self._config[conf.CONF_DEVICE][
                conf.CONF_DEVICE_PATH
            ] = self._znp._uart.transport.serial.name

        # It's better to configure these explicitly than rely on the NVRAM defaults
        await self._znp.nvram_write(NwkNvIds.CONCENTRATOR_ENABLE, t.Bool(True))
        await self._znp.nvram_write(NwkNvIds.CONCENTRATOR_DISCOVERY, t.uint8_t(120))
        await self._znp.nvram_write(NwkNvIds.CONCENTRATOR_RC, t.Bool(True))
        await self._znp.nvram_write(NwkNvIds.SRC_RTG_EXPIRY_TIME, t.uint8_t(255))
        await self._znp.nvram_write(NwkNvIds.NWK_CHILD_AGE_ENABLE, t.Bool(False))

        # XXX: the undocumented `znpBasicCfg` request can do this
        await self._znp.nvram_write(
            NwkNvIds.LOGICAL_TYPE, t.DeviceLogicalType.Coordinator
        )

        # Reset to make the above NVRAM writes take effect.
        # This also ensures any previously-started network joins don't continue.
        await self._reset()

        try:
            is_configured = (
                await self._znp.nvram_read(NwkNvIds.HAS_CONFIGURED_ZSTACK3)
            ) == b"\x55"
        except InvalidCommandResponse as e:
            assert e.response.Status == t.Status.INVALID_PARAMETER
            is_configured = False

        if not is_configured and not auto_form:
            raise RuntimeError("Cannot start application, network is not formed")
        elif auto_form and is_configured:
            LOGGER.info("ZNP is already configured, no need to form a network.")
        elif auto_form and not is_configured:
            await self.form_network()

        if self.config[conf.CONF_ZNP_CONFIG][conf.CONF_TX_POWER] is not None:
            dbm = self.config[conf.CONF_ZNP_CONFIG][conf.CONF_TX_POWER]

            await self._znp.request(
                c.SYS.SetTxPower.Req(TXPower=dbm), RspStatus=t.Status.SUCCESS
            )

        if self.config[conf.CONF_ZNP_CONFIG][conf.CONF_LED_MODE] is not None:
            led_mode = self.config[conf.CONF_ZNP_CONFIG][conf.CONF_LED_MODE]

            await self._znp.request(
                c.Util.LEDControl.Req(LED=0xFF, Mode=led_mode),
                RspStatus=t.Status.SUCCESS,
            )

        device_info = await self._znp.request(
            c.Util.GetDeviceInfo.Req(), RspStatus=t.Status.SUCCESS
        )

        self._ieee = device_info.IEEE

        if device_info.DeviceState != t.DeviceState.StartedAsCoordinator:
            # Start the application and wait until it's ready
            await self._znp.request_callback_rsp(
                request=c.ZDO.StartupFromApp.Req(StartDelay=100),
                RspState=c.zdo.StartupState.RestoredNetworkState,
                callback=c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartedAsCoordinator
                ),
            )

        # Get our active endpoints
        endpoints = await self._znp.request_callback_rsp(
            request=c.ZDO.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.ActiveEpRsp.Callback(partial=True),
        )

        # Clear out the list of active endpoints
        for endpoint in endpoints.ActiveEndpoints:
            await self._znp.request(
                c.AF.Delete.Req(Endpoint=endpoint), RspStatus=t.Status.SUCCESS
            )

        # We really need only a single endpoint
        await self._register_endpoint(
            endpoint=1,
            profile_id=zigpy.profiles.zha.PROFILE_ID,
            device_id=zigpy.profiles.zha.DeviceType.IAS_CONTROL,
            input_clusters=[clusters.general.Ota.cluster_id],
            output_clusters=[
                clusters.security.IasZone.cluster_id,
                clusters.security.IasWd.cluster_id,
            ],
        )

        nib = parse_nib(await self._znp.nvram_read(NwkNvIds.NIB))
        LOGGER.debug("Parsed NIB: %s", nib)

        self._channel = nib.nwkLogicalChannel
        self._channels = nib.channelList
        self._pan_id = nib.nwkPanId
        self._ext_pan_id = nib.extendedPANID
        self._nwk = nib.nwkDevAddress

        LOGGER.info(
            "Using channel mask %s, currently on channel %d",
            self.channels,
            self.channel,
        )

        # Add the coordinator as a device to make groups work
        self.devices[self.ieee] = ZNPCoordinator(self, self.ieee, self.nwk)

    async def update_network(
        self,
        *,
        channel: typing.Optional[t.uint8_t] = None,
        channels: typing.Optional[t.Channels] = None,
        extended_pan_id: typing.Optional[t.ExtendedPanId] = None,
        network_key: typing.Optional[t.KeyData] = None,
        pan_id: typing.Optional[t.PanId] = None,
        tc_address: typing.Optional[t.EUI64] = None,
        tc_link_key: typing.Optional[t.KeyData] = None,
        update_id: int = 0,
        reset: bool = True,
    ):
        if (
            channel is not None
            and channels is not None
            and not t.Channels.from_channel_list([channel]) & channels
        ):
            raise ValueError("Channel does not overlap with channel mask")

        if tc_link_key is not None:
            LOGGER.warning("Trust center link key in config is not yet supported")

        if tc_address is not None:
            LOGGER.warning("Trust center address in config is not yet supported")

        if channels is not None:
            await self._znp.request(
                c.Util.SetChannels.Req(Channels=channels), RspStatus=t.Status.SUCCESS,
            )
            await self._znp.request(
                c.AppConfig.BDBSetChannel.Req(IsPrimary=True, Channel=channels),
                RspStatus=t.Status.SUCCESS,
            )
            await self._znp.request(
                c.AppConfig.BDBSetChannel.Req(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.SUCCESS,
            )

            self._channels = channels

        if channel is not None:
            # We modify the logical channel value directly in the NIB.
            # Does this actually work?
            nib = parse_nib(await self._znp.nvram_read(NwkNvIds.NIB))
            nib.nwkLogicalChannel = channel
            await self._znp.nvram_write(NwkNvIds.NIB, nib.serialize())

            self._channel = channel

        if pan_id is not None:
            await self._znp.request(
                c.Util.SetPanId.Req(PanId=pan_id), RspStatus=t.Status.SUCCESS
            )

            self._pan_id = pan_id

        if extended_pan_id is not None:
            # There is no Util request to do this
            await self._znp.nvram_write(NwkNvIds.EXTENDED_PAN_ID, extended_pan_id)

            self._ext_pan_id = extended_pan_id

        if network_key is not None:
            await self._znp.request(
                c.Util.SetPreConfigKey.Req(PreConfigKey=network_key),
                RspStatus=t.Status.SUCCESS,
            )

            # XXX: The Util request does not actually write to this NV address
            await self._znp.nvram_write(NwkNvIds.PRECFGKEYS_ENABLE, t.Bool(True))

        if reset:
            # We have to reset afterwards
            await self._reset()

    async def _reset(self):
        await self._znp.request_callback_rsp(
            request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
            callback=c.SYS.ResetInd.Callback(partial=True),
        )

    async def form_network(self):
        # These options are read only on startup so we perform a soft reset right after
        await self._znp.nvram_write(
            NwkNvIds.STARTUP_OPTION, t.StartupOptions.ClearState
        )

        pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_PAN_ID]
        extended_pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_EXTENDED_PAN_ID]

        await self.update_network(
            channels=self.config[conf.CONF_NWK][conf.CONF_NWK_CHANNELS],
            pan_id=0xFFFF if pan_id is None else pan_id,
            extended_pan_id=ExtendedPanId(os.urandom(8))
            if extended_pan_id is None
            else extended_pan_id,
            network_key=t.KeyData(os.urandom(16)),
            reset=False,
        )

        # We want to receive all ZDO callbacks to proxy them back to zipgy
        await self._znp.nvram_write(NwkNvIds.ZDO_DIRECT_CB, t.Bool(True))

        # Reset now so that the changes take effect
        await self._reset()

        await self._znp.request(
            c.AppConfig.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NwkFormation
            ),
            RspStatus=t.Status.SUCCESS,
        )

        # This may take a while because of some sort of background scanning.
        # This can probably be disabled.
        await self._znp.wait_for_response(
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator)
        )

        # Create the NV item that keeps track of whether or not we're configured
        osal_create_rsp = await self._znp.request(
            c.SYS.OSALNVItemInit.Req(
                Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1, Value=b"\x55"
            )
        )

        if osal_create_rsp.Status not in (t.Status.SUCCESS, t.Status.NV_ITEM_UNINIT):
            raise RuntimeError(
                "Could not create HAS_CONFIGURED_ZSTACK3 NV item"
            )  # pragma: no cover

        # Initializing the item won't guarantee that it holds this exact value
        await self._znp.nvram_write(NwkNvIds.HAS_CONFIGURED_ZSTACK3, b"\x55")

    async def _send_zdo_request(
        self, dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
    ):
        """
        Zigpy doesn't send ZDO requests via TI's ZDO_* MT commands,
        so it will never receive a reply because ZNP intercepts ZDO replies, never
        sends a DataConfirm, and instead replies with one of its ZDO_* MT responses.

        This method translates the ZDO_* MT response into one zigpy can handle.
        """

        LOGGER.debug(
            "Intercepted a ZDO request: dst_addr=%s, dst_ep=%s, src_ep=%s, "
            "cluster=%s, sequence=%s, options=%s, radius=%s, data=%s",
            dst_addr,
            dst_ep,
            src_ep,
            cluster,
            sequence,
            options,
            radius,
            data,
        )

        assert dst_ep == ZDO_ENDPOINT

        # Deserialize the ZDO request
        zdo_hdr, data = ZDOHeader.deserialize(cluster, data)
        field_names, field_types = ZDO_CLUSTERS[cluster]
        zdo_args, _ = list_deserialize(data, field_types)
        zdo_kwargs = dict(zip(field_names, zdo_args))

        device = self.get_device(nwk=dst_addr.address)

        if cluster not in ZDO_COMPLEX_CONVERTERS:
            LOGGER.error(
                "ZDO converter for cluster %s has not been implemented!"
                " Please open a GitHub issue and attach a debug log:"
                " https://github.com/zha-ng/zigpy-znp/issues/new",
                cluster,
            )
            return t.Status.FAILURE, "No ZDO converter"

        # Call the converter with the ZDO request's kwargs
        req_factory, rsp_factory, zdo_rsp_factory = ZDO_COMPLEX_CONVERTERS[cluster]
        request = req_factory(dst_addr.address, device, **zdo_kwargs)
        callback = rsp_factory(dst_addr.address)

        LOGGER.debug(
            "Intercepted AP ZDO request %s(%s) and replaced with %s",
            cluster,
            zdo_kwargs,
            request,
        )

        try:
            async with async_timeout.timeout(ZDO_REQUEST_TIMEOUT):
                response = await self._znp.request_callback_rsp(
                    request=request, RspStatus=t.Status.SUCCESS, callback=callback
                )
        except InvalidCommandResponse as e:
            raise DeliveryError(f"Could not send command: {e.response.Status}") from e

        zdo_rsp_cluster, zdo_response_kwargs = zdo_rsp_factory(response)

        self._receive_zdo_message(
            cluster=zdo_rsp_cluster, tsn=sequence, sender=device, **zdo_response_kwargs
        )

        return response.Status, "Request sent successfully"

    async def _send_request(
        self, dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
    ):
        if dst_ep == ZDO_ENDPOINT and not (
            cluster == ZDOCmd.Mgmt_Permit_Joining_req
            and dst_addr.mode == t.AddrMode.Broadcast
        ):
            return await self._send_zdo_request(
                dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
            )

        # Zigpy just sets src == dst, which doesn't work for devices with many endpoints
        # We use endpoint 1 for everything.
        if dst_ep != ZDO_ENDPOINT:
            src_ep = 1

        request = c.AF.DataRequestExt.Req(
            DstAddrModeAddress=dst_addr,
            DstEndpoint=dst_ep,
            DstPanId=0x0000,
            SrcEndpoint=src_ep,
            ClusterId=cluster,
            TSN=sequence,
            Options=options,
            Radius=radius,
            Data=data,
        )

        if dst_addr.mode == t.AddrMode.Broadcast:
            # We won't always get a data confirmation
            response = await self._znp.request(
                request=request, RspStatus=t.Status.SUCCESS
            )
        else:
            async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
                response = await self._znp.request_callback_rsp(
                    request=request,
                    RspStatus=t.Status.SUCCESS,
                    callback=c.AF.DataConfirm.Callback(
                        partial=True, Endpoint=dst_ep, TSN=sequence
                    ),
                )

            LOGGER.debug("Received a data request confirmation: %s", response)

        if response.Status != t.Status.SUCCESS:
            return response.Status, "Invalid response status"

        return response.Status, "Request sent successfully"

    @zigpy.util.retryable_request
    async def request(
        self,
        device,
        profile,
        cluster,
        src_ep,
        dst_ep,
        sequence,
        data,
        expect_reply=True,
        use_ieee=False,
    ):
        tx_options = c.af.TransmitOptions.RouteDiscovery

        if expect_reply:
            tx_options |= c.af.TransmitOptions.APSAck

        if use_ieee:
            destination = t.AddrModeAddress(mode=t.AddrMode.IEEE, address=device.ieee)
        else:
            destination = t.AddrModeAddress(mode=t.AddrMode.NWK, address=device.nwk)

        return await self._send_request(
            dst_addr=destination,
            dst_ep=dst_ep,
            src_ep=src_ep,
            cluster=cluster,
            sequence=sequence,
            options=tx_options,
            radius=30,
            data=data,
        )

    async def broadcast(
        self,
        profile,
        cluster,
        src_ep,
        dst_ep,
        grpid,
        radius,
        sequence,
        data,
        broadcast_address=zigpy.types.BroadcastAddress.RX_ON_WHEN_IDLE,
    ):
        assert grpid == 0

        return await self._send_request(
            dst_addr=t.AddrModeAddress(
                mode=t.AddrMode.Broadcast, address=broadcast_address
            ),
            dst_ep=dst_ep,
            src_ep=src_ep,
            cluster=cluster,
            sequence=sequence,
            options=c.af.TransmitOptions.NONE,
            radius=radius,
            data=data,
        )

    async def mrequest(
        self,
        group_id,
        profile,
        cluster,
        src_ep,
        sequence,
        data,
        *,
        hops=0,
        non_member_radius=3,
    ):
        return await self._send_request(
            dst_addr=t.AddrModeAddress(mode=t.AddrMode.Group, address=group_id),
            dst_ep=src_ep,
            src_ep=src_ep,  # not actually used?
            cluster=cluster,
            sequence=sequence,
            options=c.af.TransmitOptions.NONE,
            radius=hops,
            data=data,
        )

    async def force_remove(self, device) -> None:
        """Forcibly remove device from NCP."""
        leave_rsp = await self._znp.request_callback_rsp(
            request=c.ZDO.MgmtLeaveReq.Req(
                DstAddr=0x0000,  # We handle it
                IEEE=device.ieee,
                RemoveChildren_Rejoin=c.zdo.LeaveOptions.NONE,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtLeaveRsp.Callback(Src=0x0000, partial=True),
        )

        assert leave_rsp.Status == t.ZDOStatus.SUCCESS

        # TODO: see what happens when we forcibly remove a device that isn't our child

    async def permit_ncp(self, time_s: int) -> None:
        response = await self._znp.request_callback_rsp(
            request=c.ZDO.MgmtPermitJoinReq.Req(
                AddrMode=t.AddrMode.NWK,
                Dst=0x0000,
                Duration=time_s,
                # "This field shall always have a value of 1,
                #  indicating a request to change the
                #  Trust Center policy."
                TCSignificance=1,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtPermitJoinRsp.Callback(partial=True),
        )

        if response.Status != t.Status.SUCCESS:
            raise RuntimeError(f"Permit join response failure: {response}")


class ZNPCoordinator(zigpy.device.Device):
    @property
    def manufacturer(self):
        return "Texas Instruments"

    @property
    def model(self):
        return "ZNP Coordinator"
