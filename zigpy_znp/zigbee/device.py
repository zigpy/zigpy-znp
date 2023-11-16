from __future__ import annotations

import logging

import zigpy.zdo
import zigpy.device
import zigpy.application

LOGGER = logging.getLogger(__name__)


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
