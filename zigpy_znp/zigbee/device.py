import asyncio
import logging

import zigpy.zdo
import zigpy.device
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c

LOGGER = logging.getLogger(__name__)


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


class ZNPZDOEndpoint(zigpy.zdo.ZDO):
    @property
    def app(self):
        return self.device.application

    def handle_mgmt_permit_joining_req(
        self,
        hdr: zdo_t.ZDOHeader,
        PermitDuration: t.uint8_t,
        TC_Significant: t.Bool,
        *,
        dst_addressing,
    ):
        """
        Handles ZDO `Mgmt_Permit_Joining_req` sent to the coordinator.
        """

        self.create_catching_task(
            self.async_handle_mgmt_permit_joining_req(
                hdr, PermitDuration, TC_Significant, dst_addressing=dst_addressing
            )
        )

    async def async_handle_mgmt_permit_joining_req(
        self,
        hdr: zdo_t.ZDOHeader,
        PermitDuration: t.uint8_t,
        TC_Significant: t.Bool,
        *,
        dst_addressing,
    ):
        # Joins *must* be sent via a ZDO command. Otherwise, Z-Stack will not actually
        # permit the coordinator to send the network key while routers will.
        await self.app._znp.request_callback_rsp(
            request=c.ZDO.MgmtPermitJoinReq.Req(
                AddrMode=t.AddrMode.NWK,
                Dst=0x0000,
                Duration=PermitDuration,
                TCSignificance=TC_Significant,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtPermitJoinRsp.Callback(Src=0x0000, partial=True),
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
        # Energy scans are handled properly by Z-Stack
        if NwkUpdate.ScanDuration not in (
            zdo_t.NwkUpdate.CHANNEL_CHANGE_REQ,
            zdo_t.NwkUpdate.CHANNEL_MASK_MANAGER_ADDR_CHANGE_REQ,
        ):
            return

        old_network_info = self.app.state.network_information

        if (
            t.Channels.from_channel_list([old_network_info.channel])
            == NwkUpdate.ScanChannels
        ):
            LOGGER.info("NWK update request is ignored when channel does not change")
            return

        await self.app._znp.request(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=NwkUpdate.ScanChannels,
                ScanDuration=NwkUpdate.ScanDuration,
                ScanCount=NwkUpdate.ScanCount or 0,
                NwkManagerAddr=NwkUpdate.nwkManagerAddr or 0x0000,
            ),
            RspStatus=t.Status.SUCCESS,
        )

        # Wait until the network info changes, it can take ~5s
        while (
            self.app.state.network_information.nwk_update_id
            == old_network_info.nwk_update_id
        ):
            await self.app.load_network_info(load_devices=False)
            await asyncio.sleep(1)

        # Z-Stack automatically increments the NWK update ID instead of setting it
        # TODO: Directly set it once radio settings API is finalized.
        if NwkUpdate.nwkUpdateId != self.app.state.network_information.nwk_update_id:
            LOGGER.warning(
                f"`nwkUpdateId` was incremented to"
                f" {self.app.state.network_information.nwk_update_id} instead of being"
                f" set to {NwkUpdate.nwkUpdateId}"
            )
