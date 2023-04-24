from __future__ import annotations

import logging

import zigpy.zdo
import zigpy.device
import zigpy.application

LOGGER = logging.getLogger(__name__)

NWK_UPDATE_LOOP_DELAY = 1


class ZNPCoordinator(zigpy.device.Device):
    """
    Coordinator zigpy device that keeps track of our endpoints and clusters.
    """

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
