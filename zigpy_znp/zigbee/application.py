import os
import typing
import asyncio
import logging
import itertools
import async_timeout

import zigpy.util
import zigpy.types
import zigpy.config
import zigpy.application
import zigpy.profiles
import zigpy.zcl.foundation

from zigpy.zdo.types import ZDOCmd

from zigpy.types import ExtendedPanId
from zigpy.zcl.clusters.security import IasZone

import zigpy_znp.config as conf
import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.types.nvids import NwkNvIds


ZDO_ENDPOINT = 0
ZDO_REQUEST_TIMEOUT = 15  # seconds
DATA_CONFIRM_TIMEOUT = 5  # seconds
LOGGER = logging.getLogger(__name__)


ZDO_CONVERTERS = {
    ZDOCmd.Node_Desc_req: (
        ZDOCmd.Node_Desc_rsp,
        (
            lambda addr, ep: c.ZDOCommands.NodeDescReq.Req(
                DstAddr=addr, NWKAddrOfInterest=addr
            )
        ),
        (
            lambda addr: c.ZDOCommands.NodeDescRsp.Callback(
                partial=True, Src=addr, Status=t.ZDOStatus.SUCCESS
            )
        ),
        (lambda rsp, dev: [rsp.NodeDescriptor]),
    ),
    ZDOCmd.Active_EP_req: (
        ZDOCmd.Active_EP_rsp,
        (
            lambda addr, ep: c.ZDOCommands.ActiveEpReq.Req(
                DstAddr=addr, NWKAddrOfInterest=addr
            )
        ),
        (
            lambda addr: c.ZDOCommands.ActiveEpRsp.Callback(
                partial=True, Src=addr, Status=t.ZDOStatus.SUCCESS
            )
        ),
        (lambda rsp, dev: [rsp.ActiveEndpoints]),
    ),
    ZDOCmd.Simple_Desc_req: (
        ZDOCmd.Simple_Desc_rsp,
        (
            lambda addr, ep: c.ZDOCommands.SimpleDescReq.Req(
                DstAddr=addr, NWKAddrOfInterest=addr, Endpoint=ep
            )
        ),
        (
            lambda addr: c.ZDOCommands.SimpleDescRsp.Callback(
                partial=True, Src=addr, Status=t.ZDOStatus.SUCCESS
            )
        ),
        (lambda rsp, dev: [rsp.SimpleDescriptor]),
    ),
}


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA
    SCHEMA_DEVICE = conf.SCHEMA_DEVICE

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=conf.CONFIG_SCHEMA(config))

        self._znp = None

        # It's easier to deal with this if it's never None
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

    def on_zdo_relays_message(self, msg: c.ZDOCommands.SrcRtgInd.Callback) -> None:
        LOGGER.info("ZDO device relays: %s", msg)
        device = self.get_device(nwk=msg.DstAddr)
        device.relays = msg.Relays

    def on_zdo_device_announce(
        self, msg: c.ZDOCommands.EndDeviceAnnceInd.Callback
    ) -> None:
        LOGGER.info("ZDO device announce: %s", msg)
        self.handle_join(nwk=msg.NWK, ieee=msg.IEEE, parent_nwk=0x0000)

    def on_zdo_device_join(self, msg: c.ZDOCommands.TCDevInd.Callback) -> None:
        LOGGER.info("ZDO device join: %s", msg)
        self.handle_join(nwk=msg.SrcNwk, ieee=msg.SrcIEEE, parent_nwk=msg.ParentNwk)

    def on_zdo_device_leave(self, msg: c.ZDOCommands.LeaveInd.Callback) -> None:
        LOGGER.info("ZDO device left: %s", msg)
        self.handle_leave(nwk=msg.NWK, ieee=msg.IEEE)

    def on_af_message(self, msg: c.AFCommands.IncomingMsg.Callback) -> None:
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
        self._znp.close()

    def _bind_callbacks(self, api):
        api.callback_for_response(
            c.AFCommands.IncomingMsg.Callback(partial=True), self.on_af_message
        )

        # ZDO requests need to be handled explicitly
        api.callback_for_response(
            c.ZDOCommands.EndDeviceAnnceInd.Callback(partial=True),
            self.on_zdo_device_announce,
        )

        api.callback_for_response(
            c.ZDOCommands.TCDevInd.Callback.Callback(partial=True),
            self.on_zdo_device_join,
        )

        api.callback_for_response(
            c.ZDOCommands.LeaveInd.Callback(partial=True), self.on_zdo_device_leave
        )

        api.callback_for_response(
            c.ZDOCommands.SrcRtgInd.Callback(partial=True), self.on_zdo_relays_message
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
        device_version=0x00,
        latency_req=c.af.LatencyReq.NoLatencyReqs,
        input_clusters=[],
        output_clusters=[],
    ):
        return await self._znp.request(
            c.AFCommands.Register.Req(
                Endpoint=endpoint,
                ProfileId=profile_id,
                DeviceId=device_id,
                DeviceVersion=device_version,
                LatencyReq=latency_req,
                InputClusters=input_clusters,
                OutputClusters=output_clusters,
            ),
            RspStatus=t.Status.Success,
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

        await self._reset()

        if auto_form and False:
            # XXX: actually form a network
            await self.form_network()

        if self.config[conf.CONF_ZNP_CONFIG][conf.CONF_TX_POWER] is not None:
            dbm = self.config[conf.CONF_ZNP_CONFIG][conf.CONF_TX_POWER]

            await self._znp.request(
                c.SysCommands.SetTxPower.Req(TXPower=dbm), RspStatus=t.Status.Success
            )

        """
        # Get our active endpoints
        endpoints = await self._znp.request_callback_rsp(
            request=c.ZDOCommands.ActiveEpReq.Req(
                DstAddr=0x0000, NWKAddrOfInterest=0x0000
            ),
            RspStatus=t.Status.Success,
            callback=c.ZDOCommands.ActiveEpRsp.Callback(partial=True),
        )

        # Clear out the list of active endpoints
        for endpoint in endpoints.ActiveEndpoints:
            await self._znp.request(
                c.AFCommands.Delete(Endpoint=endpoint), RspStatus=t.Status.Success
            )
        """

        # Register our endpoints
        await self._register_endpoint(endpoint=1)
        await self._register_endpoint(
            endpoint=8,
            device_id=zigpy.profiles.zha.DeviceType.IAS_CONTROL,
            output_clusters=[IasZone.cluster_id],
        )
        await self._register_endpoint(endpoint=11)
        await self._register_endpoint(endpoint=12)
        await self._register_endpoint(
            endpoint=100, profile_id=zigpy.profiles.zll.PROFILE_ID, device_id=0x0005
        )

        # Start commissioning and wait until it's done
        comm_notification = await self._znp.request_callback_rsp(
            request=c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NetworkFormation
            ),
            RspStatus=t.Status.Success,
            callback=c.APPConfigCommands.BDBCommissioningNotification.Callback(
                partial=True,
                RemainingModes=c.app_config.BDBRemainingCommissioningModes.NONE,
            ),
        )

        # XXX: Commissioning fails for me yet I experience no issues
        if comm_notification.Status != c.app_config.BDBCommissioningStatus.Success:
            LOGGER.warning(
                "BDB commissioning did not succeed: %s", comm_notification.Status
            )

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

        if channel is not None:
            LOGGER.warning("Cannot set a specific channel in config: %d", channel)

        if tc_link_key is not None:
            LOGGER.warning("Trust center link key in config is not yet supported")

        if tc_address is not None:
            LOGGER.warning("Trust center address in config is not yet supported")

        if channels is not None:
            await self._znp.request(
                c.UtilCommands.SetChannels.Req(Channels=channels),
                RspStatus=t.Status.Success,
            )
            await self._znp.request(
                c.APPConfigCommands.BDBSetChannel.Req(IsPrimary=True, Channel=channels),
                RspStatus=t.Status.Success,
            )
            await self._znp.request(
                c.APPConfigCommands.BDBSetChannel.Req(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.Success,
            )

            self._channels = channels

        if pan_id is not None:
            await self._znp.request(
                c.UtilCommands.SetPanId.Req(PanId=pan_id), RspStatus=t.Status.Success
            )

            self._pan_id = pan_id

        if extended_pan_id is not None:
            # There is no Util request to do this
            await self._znp.nvram_write(NwkNvIds.EXTENDED_PAN_ID, extended_pan_id)

            self._ext_pan_id = extended_pan_id

        if network_key is not None:
            await self._znp.request(
                c.UtilCommands.SetPreConfigKey.Req(PreConfigKey=network_key),
                RspStatus=t.Status.Success,
            )

            # XXX: The Util request does not actually write to this NV address
            await self._znp.nvram_write(NwkNvIds.PRECFGKEYS_ENABLE, t.Bool(True))

        if reset:
            # We have to reset afterwards
            await self._reset()

    async def _reset(self):
        await self._znp.request_callback_rsp(
            request=c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft),
            callback=c.SysCommands.ResetInd.Callback(partial=True),
        )

    async def form_network(self):
        # These options are read only on startup so we perform a soft reset right after
        await self._znp.nvram_write(
            NwkNvIds.STARTUP_OPTION, t.StartupOptions.ClearState
        )

        # XXX: the undocumented `znpBasicCfg` request can do this
        await self._znp.nvram_write(
            NwkNvIds.LOGICAL_TYPE, t.DeviceLogicalType.Coordinator
        )
        await self._reset()

        # If zgPreConfigKeys is set to TRUE, all devices should use the same
        # pre-configured security key. If zgPreConfigKeys is set to FALSE, the
        # pre-configured key is set only on the coordinator device, and is handed to
        # joining devices. The key is sent in the clear over the last hop. Upon reset,
        # the device will retrieve the pre-configured key from NV memory if the NV_INIT
        # compile option is defined (the NV item is called ZCD_NV_PRECFGKEY).

        pan_id = self.config[conf.SCHEMA_NETWORK][conf.CONF_NWK_PAN_ID]
        extended_pan_id = self.config[conf.SCHEMA_NETWORK][
            conf.CONF_NWK_EXTENDED_PAN_ID
        ]

        await self.update_network(
            channels=self.config[conf.SCHEMA_NETWORK][conf.CONF_NWK_CHANNELS],
            pan_id=0xFFFF if pan_id is None else pan_id,
            extended_pan_id=ExtendedPanId(os.urandom(8))
            if extended_pan_id is None
            else extended_pan_id,
            network_key=t.KeyData([os.urandom(16)]),
            reset=False,
        )

        # We want to receive all ZDO callbacks to proxy them back go zipgy
        await self._znp.nvram_write(NwkNvIds.ZDO_DIRECT_CB, t.Bool(True))

        await self._znp.request(
            c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NetworkFormation
            ),
            RspStatus=t.Status.Success,
        )

        # This may take a while because of some sort of background scanning.
        # This can probably be disabled.
        await self._znp.wait_for_response(
            c.ZDOCommands.StateChangeInd.Callback(
                State=t.DeviceState.StartedAsCoordinator
            )
        )

        await self._znp.request(
            c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NetworkSteering
            ),
            RspStatus=t.Status.Success,
        )

    async def _send_zdo_request(
        self, dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
    ):
        """
        Zigpy doesn't send ZDO requests via TI's ZDO_* MT commands,
        so it will never receive a reply because ZNP intercepts ZDO replies, never
        sends a DataConfirm, and instead replies with one of its ZDO_* MT responses.

        This method translates the ZDO_* MT response into one zigpy can handle.
        """

        LOGGER.trace(
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

        rsp_cluster, req_factory, callback_factory, converter = ZDO_CONVERTERS[cluster]
        request = req_factory(dst_addr.address, ep=src_ep)
        callback = callback_factory(dst_addr.address)

        LOGGER.debug(
            "Intercepted AP ZDO request and replaced with %s - %s", request, callback
        )

        async with async_timeout.timeout(ZDO_REQUEST_TIMEOUT):
            response = await self._znp.request_callback_rsp(
                request=request, RspStatus=t.Status.Success, callback=callback
            )

        device = self.get_device(nwk=dst_addr.address)

        # Build up a ZDO response
        message = t.serialize_list(
            [t.uint8_t(sequence), response.Status, response.NWK]
            + converter(response, device)
        )
        LOGGER.trace("Pretending we received a ZDO message: %s", message)

        # We do not get any LQI info here
        self.handle_message(
            sender=device,
            profile=zigpy.profiles.zha.PROFILE_ID,
            cluster=rsp_cluster,
            src_ep=dst_ep,
            dst_ep=src_ep,
            message=message,
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

        async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
            response = await self._znp.request_callback_rsp(
                request=c.AFCommands.DataRequestExt.Req(
                    DstAddrModeAddress=dst_addr,
                    DstEndpoint=dst_ep,
                    DstPanId=0x0000,
                    SrcEndpoint=src_ep,
                    ClusterId=cluster,
                    TSN=sequence,
                    Options=options,
                    Radius=radius,
                    Data=data,
                ),
                RspStatus=t.Status.Success,
                callback=c.AFCommands.DataConfirm.Callback(
                    partial=True, Endpoint=dst_ep, TSN=sequence
                ),
            )

        LOGGER.debug("Received a data request confirmation: %s", response)

        if response.Status != t.Status.Success:
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

        # if expect_reply:
        #    tx_options |= c.af.TransmitOptions.APSAck

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
        raise NotImplementedError()  # pragma: no cover

    async def force_remove(self, device) -> None:
        """Forcibly remove device from NCP."""
        await self._znp.request(
            c.ZDOCommands.MgmtLeaveReq.Req(
                DstAddr=device.nwk,
                IEEE=device.ieee,
                LeaveOptions=c.zdo.LeaveOptions.NONE,
            ),
            RspStatus=t.Status.Success,
        )

    async def permit_ncp(self, time_s: int) -> None:
        response = await self._znp.request_callback_rsp(
            request=c.ZDOCommands.MgmtPermitJoinReq.Req(
                AddrMode=t.AddrMode.Broadcast,
                Dst=zigpy.types.BroadcastAddress.ALL_DEVICES,
                Duration=time_s,
                TCSignificance=0,  # not used in Z-Stack
            ),
            RspStatus=t.Status.Success,
            callback=c.ZDOCommands.MgmtPermitJoinRsp.Callback(partial=True),
        )

        if response.Status != t.Status.Success:
            raise RuntimeError(f"Permit join response failure: {response}")
