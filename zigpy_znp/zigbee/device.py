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
    def manufacturer(self) -> str:
        return "Texas Instruments"

    @manufacturer.setter
    def manufacturer(self, value: str) -> None:
        # Setter for parent class interface; no-op (hardware-determined)
        pass

    @property
    def model(self) -> str:
        return "Coordinator"

    @model.setter
    def model(self, value: str) -> None:
        # Setter for parent class interface; no-op (hardware-determined)
        pass

    async def request(
        self,
        *args,
        timeout=2 * zigpy.device.APS_REPLY_TIMEOUT,
        **kwargs,
    ):
        """
        Normal `zigpy.device.Device.request` except its default timeout is longer.
        """

        return await super().request(*args, timeout=timeout, **kwargs)
