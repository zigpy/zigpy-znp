import os
import typing
import logging
import async_timeout

import zigpy.util
import zigpy.types
import zigpy.application
import zigpy.profiles
import zigpy.zcl.foundation
from zigpy.zdo.types import ZDOCmd

from zigpy.types import ExtendedPanId
from zigpy.zcl.clusters.security import IasZone

import zigpy_znp.types as t
import zigpy_znp.commands as c

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
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

        self._api.callback_for_response(
            c.AFCommands.IncomingMsg.Callback(partial=True), self.on_af_message
        )

        # ZDO requests need to be handled explicitly
        self._api.callback_for_response(
            c.ZDOCommands.EndDeviceAnnceInd.Callback(partial=True),
            self.on_zdo_device_announce,
        )

        self._api.callback_for_response(
            c.ZDOCommands.TCDevInd.Callback.Callback(partial=True),
            self.on_zdo_device_join,
        )

        self._api.callback_for_response(
            c.ZDOCommands.LeaveInd.Callback(partial=True), self.on_zdo_device_leave
        )

        self._api.callback_for_response(
            c.ZDOCommands.SrcRtgInd.Callback(partial=True), self.on_zdo_relays_message
        )

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
        self._api.close()

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""

        await self._reset(t.ResetType.Soft)

        should_form = [False]

        if auto_form and any(should_form):
            await self.form_network()

        """
        # Get our active endpoints
        endpoints = await self._api.request_callback_rsp(
            request=c.ZDOCommands.ActiveEpReq.Req(
                DstAddr=0x0000, NWKAddrOfInterest=0x0000
            ),
            RspStatus=t.Status.Success,
            callback=c.ZDOCommands.ActiveEpRsp.Callback(partial=True),
        )

        # Clear out the list of active endpoints
        for endpoint in endpoints.ActiveEndpoints:
            await self._api.request(
                c.AFCommands.Delete(Endpoint=endpoint), RspStatus=t.Status.Success
            )
        """

        # Register our endpoints
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=1,
                ProfileId=zigpy.profiles.zha.PROFILE_ID,
                DeviceId=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=[],
                OutputClusters=[],
            ),
            RspStatus=t.Status.Success,
        )
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=8,
                ProfileId=zigpy.profiles.zha.PROFILE_ID,
                DeviceId=zigpy.profiles.zha.DeviceType.IAS_CONTROL,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=[],
                OutputClusters=[IasZone.cluster_id],
            ),
            RspStatus=t.Status.Success,
        )
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=11,
                ProfileId=zigpy.profiles.zha.PROFILE_ID,
                DeviceId=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=[],
                OutputClusters=[],
            ),
            RspStatus=t.Status.Success,
        )
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=12,
                ProfileId=zigpy.profiles.zha.PROFILE_ID,
                DeviceId=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=[],
                OutputClusters=[],
            ),
            RspStatus=t.Status.Success,
        )
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=100,
                ProfileId=zigpy.profiles.zll.PROFILE_ID,
                DeviceId=0x0005,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=[],
                OutputClusters=[],
            ),
            RspStatus=t.Status.Success,
        )

        # Start commissioning and wait until it's done
        comm_notification = await self._api.request_callback_rsp(
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
        pan_id: typing.Optional[t.PanId] = None,
        extended_pan_id: typing.Optional[t.ExtendedPanId] = None,
        network_key: typing.Optional[t.KeyData] = None,
        reset: bool = True,
    ):
        if channel is not None:
            raise NotImplementedError("Cannot set a specific channel")

        if channels is not None:
            await self._api.request(
                c.UtilCommands.SetChannels.Req(Channels=channels),
                RspStatus=t.Status.Success,
            )
            await self._api.request(
                c.APPConfigCommands.BDBSetChannel.Req(IsPrimary=True, Channel=channels),
                RspStatus=t.Status.Success,
            )
            await self._api.request(
                c.APPConfigCommands.BDBSetChannel.Req(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.Success,
            )

            self._channels = channels

        if pan_id is not None:
            await self._api.request(
                c.UtilCommands.SetPanId.Req(PanId=pan_id), RspStatus=t.Status.Success
            )

            self._pan_id = pan_id

        if extended_pan_id is not None:
            # There is no Util request to do this
            await self._api.nvram_write(NwkNvIds.EXTENDED_PAN_ID, extended_pan_id)

            self._extended_pan_id = extended_pan_id

        if network_key is not None:
            await self._api.request(
                c.UtilCommands.SetPreConfigKey.Req(PreConfigKey=network_key),
                RspStatus=t.Status.Success,
            )

            # XXX: The Util request does not actually write to this NV address
            await self._api.nvram_write(
                NwkNvIds.PRECFGKEYS_ENABLE, zigpy.types.bool(True)
            )

        if reset:
            # We have to reset afterwards
            await self._reset()

    async def _reset(self, reset_type: t.ResetType = t.ResetType.Soft):
        await self._api.request_callback_rsp(
            request=c.SysCommands.ResetReq.Req(Type=reset_type),
            callback=c.SysCommands.ResetInd.Callback(partial=True),
        )

    async def form_network(self, channels=[15], pan_id=None, extended_pan_id=None):
        # These options are read only on startup so we perform a soft reset right after
        await self._api.nvram_write(
            NwkNvIds.STARTUP_OPTION, t.StartupOptions.ClearState
        )

        # XXX: the undocumented `znpBasicCfg` request can do this
        await self._api.nvram_write(
            NwkNvIds.LOGICAL_TYPE, t.DeviceLogicalType.Coordinator
        )
        await self._reset()

        # If zgPreConfigKeys is set to TRUE, all devices should use the same
        # pre-configured security key. If zgPreConfigKeys is set to FALSE, the
        # pre-configured key is set only on the coordinator device, and is handed to
        # joining devices. The key is sent in the clear over the last hop. Upon reset,
        # the device will retrieve the pre-configured key from NV memory if the NV_INIT
        # compile option is defined (the NV item is called ZCD_NV_PRECFGKEY).

        await self.update_network(
            channel=None,
            channels=t.Channels.from_channel_list(channels),
            pan_id=0xFFFF if pan_id is None else pan_id,
            extended_pan_id=ExtendedPanId(
                os.urandom(8) if extended_pan_id is None else extended_pan_id
            ),
            network_key=t.KeyData(os.urandom(16)),
            reset=False,
        )

        # We do not want to receive verbose ZDO callbacks
        # Just pass ZDO callbacks back to Zigpy
        await self._api.nvram_write(NwkNvIds.ZDO_DIRECT_CB, t.Bool(True))

        await self._api.request(
            c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NetworkFormation
            ),
            RspStatus=t.Status.Success,
        )

        # This may take a while because of some sort of background scanning.
        # This can probably be disabled.
        await self._api.wait_for_response(
            c.ZDOCommands.StateChangeInd.Callback(
                State=t.DeviceState.StartedAsCoordinator
            )
        )

        await self._api.request(
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

        response_cluster, request_factory, callback_factory, converter = ZDO_CONVERTERS[
            cluster
        ]
        request = request_factory(dst_addr.address, ep=src_ep)
        callback = callback_factory(dst_addr.address)

        LOGGER.debug(
            "Intercepted AP ZDO request and replaced with %s - %s", request, callback
        )

        async with async_timeout.timeout(ZDO_REQUEST_TIMEOUT):
            response = await self._api.request_callback_rsp(
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
            cluster=response_cluster,
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
            response = await self._api.request_callback_rsp(
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
        raise NotImplementedError()

    async def force_remove(self, device) -> None:
        """Forcibly remove device from NCP."""
        await self._api.request(
            c.ZDOCommands.MgmtLeaveReq.Req(
                DstAddr=device.nwk,
                IEEE=device.ieee,
                LeaveOptions=c.zdo.LeaveOptions.NONE,
            ),
            RspStatus=t.Status.Success,
        )

    async def permit_ncp(self, time_s: int) -> None:
        response = await self._api.request_callback_rsp(
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

    async def set_tx_power(self, dbm: int) -> None:
        assert -22 <= dbm <= 19

        await self._api.request(
            c.SysCommands.SetTxPower.Req(TXPower=dbm), RspStatus=t.Status.Success
        )
