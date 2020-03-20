import os
import logging

import zigpy.types
import zigpy.application
from zigpy.types import ExtendedPanId

import zigpy_znp.types as t

from zigpy_znp.types.nvids import NvIds
from zigpy_znp.commands.types import DeviceState
from zigpy_znp.commands.zdo import ZDOCommands, StartupState
from zigpy_znp.commands.app_config import APPConfigCommands
from zigpy_znp.commands.sys import SysCommands


LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    def __init__(self, api, database_file=None):
        super().__init__(database_file=database_file)
        self._api = api
        api.set_application(self)

    async def shutdown(self):
        """Shutdown application."""
        self._api.close()

    async def startup(self, auto_form=False):
        """Perform a complete application startup"""
        should_form = [False]

        if auto_form and any(should_form):
            await self.form_network()

        await self._api.wait_for_response(
            ZDOCommands.StateChangeInd.Rsp(State=DeviceState.StartedAsCoordinator)
        )
        startup_rsp = await self._api.command(
            ZDOCommands.StartupFromApp(StartupDelay=100)
        )

        if startup_rsp.State == StartupState.NotStarted:
            raise RuntimeError("Network failed to start")

    async def form_network(self, channel=15, pan_id=None, extended_pan_id=None):
        # These options are read only on startup so we perform a soft reset right after
        await self._api.nvram_write(NvIds.STARTUP_OPTION, t.StartupOptions.ClearState)
        await self._api.nvram_write(NvIds.LOGICAL_TYPE, t.DeviceLogicalType.Coordinator)
        await self._api.command(SysCommands.ResetReq.Req(Type=t.ResetType.Soft))

        # If zgPreConfigKeys is set to TRUE, all devices should use the same
        # pre-configured security key. If zgPreConfigKeys is set to FALSE, the
        # pre-configured key is set only on the coordinator device, and is handed to
        # joining devices. The key is sent in the clear over the last hop. Upon reset,
        # the device will retrieve the pre-configured key from NV memory if the NV_INIT
        # compile option is defined (the NV item is called ZCD_NV_PRECFGKEY).
        network_key = zigpy.types.KeyData(os.urandom(16))
        await self._api.nvram_write(NvIds.PRECFGKEY, network_key)
        await self._api.nvram_write(NvIds.PRECFGKEYS_ENABLE, zigpy.types.bool(True))

        channel_mask = t.Channels.from_channels([channel])
        await self._api.nvram_write(NvIds.CHANLIST, channel_mask)

        # Receive verbose callbacks
        await self._api.nvram_write(NvIds.ZDO_DIRECT_CB, zigpy.types.bool(True))

        # 0xFFFF means "don't care", according to the documentation
        pan_id = t.PanId(0xFFFF if pan_id is None else pan_id)
        await self._api.nvram_write(NvIds.PANID, pan_id)

        extended_pan_id = ExtendedPanId(
            os.urandom(8) if extended_pan_id is None else extended_pan_id
        )
        await self._api.nvram_write(NvIds.EXTENDED_PAN_ID, extended_pan_id)

        await self._api.command(
            APPConfigCommands.BDBSetChannel(IsPrimary=True, Channel=channel_mask)
        )
        await self._api.command(
            APPConfigCommands.BDBSetChannel(
                IsPrimary=False, Channel=t.Channels.NO_CHANNELS
            )
        )

        await self._api.command(
            APPConfigCommands.BDBStartCommissioning(
                Mode=t.BDBCommissioningMode.NetworkFormation
            )
        )

        # This may take a while because of some sort of background scanning.
        # This can probably be disabled.
        await self._api.wait_for_response(
            ZDOCommands.StateChangeInd.Rsp(State=DeviceState.StartedAsCoordinator)
        )

        await self._api.command(
            APPConfigCommands.BDBStartCommissioning(
                Mode=t.BDBCommissioningMode.NetworkSteering
            )
        )

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
        raise NotImplementedError()

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
        non_member_radius=3
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

    async def force_remove(self, dev):
        """Forcibly remove device from NCP."""
        raise NotImplementedError()

    async def permit_ncp(self, time_s=60):
        assert 0 <= time_s <= 254
        raise NotImplementedError()
