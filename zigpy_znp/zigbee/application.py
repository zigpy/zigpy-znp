import os
import logging
import async_timeout

from typing import Optional

import zigpy.util
import zigpy.types
import zigpy.application
import zigpy.profiles
from zigpy.zcl.clusters.security import IasZone

import zigpy.zdo.types as zdo_t
from zigpy.types import ExtendedPanId

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.types.nvids import NwkNvIds
from zigpy_znp.commands.types import DeviceState


DATA_CONFIRM_TIMEOUT = 5  # seconds
LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

        self._api.callback_for_response(
            c.AFCommands.IncomingMsg.Callback(partial=True), self.on_af_message
        )

    def on_af_message(self, msg: c.AFCommands.IncomingMsg.Callback) -> None:
        if msg.ClusterId == zdo_t.ZDOCmd.Device_annce and msg.DstEndpoint == 0:
            # [Sequence Number] + [16-bit address] + [64-bit address] + [Capability]
            sequence, data = t.uint8_t.deserialize(msg.Data)
            nwk, data = t.NWK.deserialize(data)
            ieee, data = t.EUI64.deserialize(data)
            capability = data

            LOGGER.info("ZDO Device announce: 0x%04x, %s, %s", nwk, ieee, capability)
            self.handle_join(nwk, ieee, parent_nwk=0x0000)
            return

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
        await self._reset()

        should_form = [False]

        if auto_form and any(should_form):
            await self.form_network()

        await self._api.request(c.ZDOCommands.StartupFromApp.Req(StartDelay=0))

        await self._api.wait_for_response(
            c.ZDOCommands.StateChangeInd.Callback(
                State=DeviceState.StartedAsCoordinator
            )
        )

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

        # Register our own
        await self._api.request(
            c.AFCommands.Register.Req(
                Endpoint=1,
                ProfileId=zigpy.profiles.zha.PROFILE_ID,
                DeviceId=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
                DeviceVersion=0x00,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=t.LVList(t.ClusterId)([]),
                OutputClusters=t.LVList(t.ClusterId)([]),
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
                InputClusters=t.LVList(t.ClusterId)([]),
                OutputClusters=t.LVList(t.ClusterId)([IasZone.cluster_id]),
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
                InputClusters=t.LVList(t.ClusterId)([]),
                OutputClusters=t.LVList(t.ClusterId)([]),
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
                InputClusters=t.LVList(t.ClusterId)([]),
                OutputClusters=t.LVList(t.ClusterId)([]),
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

        await self._api.wait_for_response(
            c.APPConfigCommands.BDBCommissioningNotification.Callback(partial=True)
        )

    async def update_network(
        self,
        *,
        channel: Optional[t.uint8_t] = None,
        channels: Optional[t.Channels] = None,
        pan_id: Optional[t.PanId] = None,
        extended_pan_id: Optional[zigpy.types.ExtendedPanId] = None,
        network_key: Optional[zigpy.types.KeyData] = None,
        reset: bool = True,
    ):
        if channel is None:
            raise NotImplementedError("Cannot set a specific channel")

        if channels is not None:
            await self._api.request(
                c.UtilCommands.SetChannels(Channels=channels),
                RspStatus=t.Status.Success,
            )
            await self._api.request(
                c.APPConfigCommands.BDBSetChannel(IsPrimary=True, Channel=channels),
                RspStatus=t.Status.Success,
            )
            await self._api.request(
                c.APPConfigCommands.BDBSetChannel(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.Success,
            )

        if pan_id is not None:
            await self._api.request(
                c.UtilCommands.SetPanId(PanId=pan_id), RspStatus=t.Status.Success
            )

        if extended_pan_id is not None:
            # There is no Util request to do this
            await self._api.nvram_write(NwkNvIds.EXTENDED_PAN_ID, extended_pan_id)

        if network_key is not None:
            await self._api.request(
                c.UtilCommands.SetPreConfigKey(PreConfigKey=network_key),
                RspStatus=t.Status.Success,
            )

            # XXX: The Util request does not actually write to this NV address
            await self._api.nvram_write(
                NwkNvIds.PRECFGKEYS_ENABLE, zigpy.types.bool(True)
            )

        if reset:
            # We have to reset afterwards
            await self._reset()

    async def _reset(self):
        await self._api.request_callback_rsp(
            request=c.SysCommands.ResetReq.Req(Type=t.ResetType.Soft),
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
            network_key=zigpy.types.KeyData(os.urandom(16)),
            reset=False,
        )

        # Receive verbose callbacks
        await self._api.nvram_write(NwkNvIds.ZDO_DIRECT_CB, t.Bool(True))

        await self._api.request(
            c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=t.BDBCommissioningMode.NetworkFormation
            ),
            RspStatus=t.Status.Success,
        )

        # This may take a while because of some sort of background scanning.
        # This can probably be disabled.
        await self._api.wait_for_response(
            c.ZDOCommands.StateChangeInd.Rsp(State=DeviceState.StartedAsCoordinator)
        )

        await self._api.request(
            c.APPConfigCommands.BDBStartCommissioning.Req(
                Mode=t.BDBCommissioningMode.NetworkSteering
            ),
            RspStatus=t.Status.Success,
        )

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
        """Submit and send data out as an unicast transmission.
        :param device: destination device
        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param dst_ep: destination endpoint id
        :param sequence: transaction sequence number of the message
        :param data: Zigbee message payload
        :param expect_reply: True if this is essentially a request
        :param use_ieee: use EUI64 for destination addressing
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """

        if use_ieee:
            raise ValueError("use_ieee: AFCommands.DataRequestExt is not supported yet")

        tx_options = c.af.TransmitOptions.RouteDiscovery

        # if expect_reply:
        #    tx_options |= c.af.TransmitOptions.APSAck

        # TODO: c.AFCommands.DataRequestSrcRtg

        async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
            response = await self._api.request_callback_rsp(
                request=c.AFCommands.DataRequest.Req(
                    DstAddr=device.nwk,
                    DstEndpoint=dst_ep,
                    SrcEndpoint=src_ep,
                    ClusterId=cluster,
                    TSN=sequence,
                    Options=tx_options,
                    Radius=30,
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
        """Submit and send data out as a multicast transmission.
        :param group_id: destination multicast address
        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param sequence: transaction sequence number of the message
        :param data: Zigbee message payload
        :param hops: the message will be delivered to all nodes within this number of
                     hops of the sender. A value of zero is converted to MAX_HOPS
        :param non_member_radius: the number of hops that the message will be forwarded
                                  by devices that are not members of the group. A value
                                  of 7 or greater is treated as infinite
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """
        raise NotImplementedError()

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
        """Submit and send data out as an broadcast transmission.
        :param profile: Zigbee Profile ID to use for outgoing message
        :param cluster: cluster id where the message is being sent
        :param src_ep: source endpoint id
        :param dst_ep: destination endpoint id
        :param grpid: group id to address the broadcast to
        :param radius: max radius of the broadcast
        :param sequence: transaction sequence number of the message
        :param data: zigbee message payload
        :param broadcast_address: broadcast address.
        :returns: return a tuple of a status and an error_message. Original requestor
                  has more context to provide a more meaningful error message
        """

        raise NotImplementedError()

    async def force_remove(self, device):
        """Forcibly remove device from NCP."""
        await self._api.request(
            c.ZDOCommands.MgmtLeaveReq(
                Dst=device.nwk, IEEE=device.ieee, LeaveOptions=c.zdo.LeaveOptions.NONE
            ),
            RspStatus=t.Status.Success,
        )

        # TODO: do we wait for a c.ZDOCommands.LeaveInd?

    async def permit_ncp(self, time_s):
        await self._api.request(
            c.ZDOCommands.MgmtPermitJoinReq.Req(
                AddrMode=t.AddrMode.Broadcast,
                Dst=zigpy.types.BroadcastAddress.ALL_DEVICES,
                Duration=time_s,
                TCSignificance=0,
            ),
            RspStatus=t.Status.Success,
        )

        await self._api.wait_for_response(
            c.ZDOCommands.MgmtPermitJoinRsp.Callback(partial=True),
            RspStatus=t.Status.Success,
        )
