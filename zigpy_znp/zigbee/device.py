from __future__ import annotations

import logging
from typing import Any, Coroutine
from zigpy.zcl.foundation import Status as ZCLStatus, Status

import zigpy.zdo
import zigpy.endpoint
import zigpy.device
import zigpy.application
from zigpy_znp.api import ZNP
import zigpy_znp.commands as c
import zigpy_znp.types as t

LOGGER = logging.getLogger(__name__)

class ZNPEndpoint(zigpy.endpoint.Endpoint):
    async def add_to_group(self, grp_id: int, name: str | None = None) -> ZCLStatus:
        znp: ZNP = self.device.application._znp
        if name is None:
            name = ""

        result = await znp.request(c.ZDO.ExtFindGroup.Req(Endpoint=self.endpoint_id, GroupId=grp_id))
        if result.Status == t.Status.FAILURE:
            result = await znp.request(c.ZDO.ExtAddGroup.Req(Endpoint=self.endpoint_id, GroupId=grp_id, GroupName=t.CharacterString(name)))
        if result.Status == t.Status.FAILURE:
            return ZCLStatus.FAILURE
        group = self.device.application.groups.add_group(grp_id, name)
        group.add_member(self)
        return ZCLStatus.SUCCESS
        
    async def remove_from_group(self, grp_id: int) -> ZCLStatus:
        znp: ZNP = self.device.application._znp
        result = await znp.request(c.ZDO.ExtRemoveGroup.Req(Endpoint=self.endpoint_id, GroupId=grp_id))
        if result.Status == t.Status.FAILURE:
            return ZCLStatus.FAILURE
        if grp_id in self.device.application.groups:
            self.device.application.groups[grp_id].remove_member(self)
        return ZCLStatus.SUCCESS

    
class ZNPCoordinator(zigpy.device.Device):
    """
    Coordinator zigpy device that keeps track of our endpoints and clusters.
    """
    @property
    def manufacturer(self):
        return "Texas Instruments"

    @property
    def model(self):
        return "Coordinator"

    def add_endpoint(self, endpoint_id) -> zigpy.endpoint.Endpoint:
        ep = ZNPEndpoint(self, endpoint_id)
        self.endpoints[endpoint_id] = ep
        return ep

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
