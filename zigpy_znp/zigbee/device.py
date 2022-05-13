from __future__ import annotations

import asyncio
import logging

import zigpy.zdo
import zigpy.device
import zigpy.zdo.types as zdo_t
import zigpy.application

import zigpy_znp.types as t
import zigpy_znp.commands as c
import zigpy_znp.zigbee.application as znp_app

LOGGER = logging.getLogger(__name__)

NWK_UPDATE_LOOP_DELAY = 1


class ZNPCoordinator(zigpy.device.Device):
    """
    Coordinator zigpy device that keeps track of our endpoints and clusters.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        assert hasattr(self, "zdo")
        self.zdo = ZNPZDOEndpoint(self)
        self.endpoints[0] = self.zdo

    @property
    def manufacturer(self):
        return "Texas Instruments"

    @property
    def model(self):
        if self.application._znp.version > 3.0:
            model = "CC1352/CC2652"
            version = "3.30+"
        else:
            model = "CC2538" if self.application._znp.nvram.align_structs else "CC2531"
            version = "Home 1.2" if self.application._znp.version == 1.2 else "3.0.x"

        return f"{model}, Z-Stack {version} (build {self.application._zstack_build_id})"

    def request(
        self,
        profile,
        cluster,
        src_ep,
        dst_ep,
        sequence,
        data,
        expect_reply=True,
        # Extend the default timeout
        timeout=2 * zigpy.device.APS_REPLY_TIMEOUT,
        use_ieee=False,
    ):
        """
        Normal `zigpy.device.Device:request` except its default timeout is longer.
        """

        return super().request(
            profile,
            cluster,
            src_ep,
            dst_ep,
            sequence,
            data,
            expect_reply=expect_reply,
            timeout=timeout,
            use_ieee=use_ieee,
        )


class ZNPZDOEndpoint(zigpy.zdo.ZDO):
    @property
    def app(self) -> zigpy.application.ControllerApplication:
        return self.device.application

    def _send_loopback_reply(
        self, command_id: zdo_t.ZDOCmd, *, tsn: t.uint8_t, **kwargs
    ):
        """
        Constructs and sends back a loopback ZDO response.
        """

        message = t.uint8_t(tsn).serialize() + self._serialize(
            command_id, *kwargs.values()
        )

        LOGGER.debug("Sending loopback reply %s (%s), tsn=%s", command_id, kwargs, tsn)

        self.app.handle_message(
            sender=self.app._device,
            profile=znp_app.ZDO_PROFILE,
            cluster=command_id,
            src_ep=znp_app.ZDO_ENDPOINT,
            dst_ep=znp_app.ZDO_ENDPOINT,
            message=message,
        )

    def handle_mgmt_nwk_update_req(
        self, hdr: zdo_t.ZDOHeader, NwkUpdate: zdo_t.NwkUpdate, *, dst_addressing
    ):
        """
        Handles ZDO `Mgmt_NWK_Update_req` sent to the coordinator.
        """

        self.create_catching_task(
            self.async_handle_mgmt_nwk_update_req(
                hdr, NwkUpdate, dst_addressing=dst_addressing
            )
        )

    async def async_handle_mgmt_nwk_update_req(
        self, hdr: zdo_t.ZDOHeader, NwkUpdate: zdo_t.NwkUpdate, *, dst_addressing
    ):
        # Energy scans are handled properly by Z-Stack, no need to do anything
        if NwkUpdate.ScanDuration not in (
            zdo_t.NwkUpdate.CHANNEL_CHANGE_REQ,
            zdo_t.NwkUpdate.CHANNEL_MASK_MANAGER_ADDR_CHANGE_REQ,
        ):
            return

        old_network_info = self.app.state.network_info

        if (
            t.Channels.from_channel_list([old_network_info.channel])
            == NwkUpdate.ScanChannels
        ):
            LOGGER.warning("NWK update request is ignored when channel does not change")
            self._send_loopback_reply(
                zdo_t.ZDOCmd.Mgmt_NWK_Update_rsp,
                Status=zdo_t.Status.SUCCESS,
                ScannedChannels=t.Channels.NO_CHANNELS,
                TotalTransmissions=0,
                TransmissionFailures=0,
                EnergyValues=[],
                tsn=hdr.tsn,
            )
            return

        await self.app._znp.request(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=NwkUpdate.ScanChannels,
                ScanDuration=NwkUpdate.ScanDuration,
                # Missing fields in the request cannot be `None` in the Z-Stack command
                ScanCount=NwkUpdate.ScanCount or 0,
                NwkManagerAddr=NwkUpdate.nwkManagerAddr or 0x0000,
            ),
            RspStatus=t.Status.SUCCESS,
        )

        # Wait until the network info changes, it can take ~5s
        while (
            self.app.state.network_info.nwk_update_id == old_network_info.nwk_update_id
        ):
            await self.app.load_network_info(load_devices=False)
            await asyncio.sleep(NWK_UPDATE_LOOP_DELAY)

        # Z-Stack automatically increments the NWK update ID instead of setting it
        # TODO: Directly set it once radio settings API is finalized.
        if NwkUpdate.nwkUpdateId != self.app.state.network_info.nwk_update_id:
            LOGGER.warning(
                f"`nwkUpdateId` was incremented to"
                f" {self.app.state.network_info.nwk_update_id} instead of being"
                f" set to {NwkUpdate.nwkUpdateId}"
            )

        self._send_loopback_reply(
            zdo_t.ZDOCmd.Mgmt_NWK_Update_rsp,
            Status=zdo_t.Status.SUCCESS,
            ScannedChannels=t.Channels.NO_CHANNELS,
            TotalTransmissions=0,
            TransmissionFailures=0,
            EnergyValues=[],
            tsn=hdr.tsn,
        )
