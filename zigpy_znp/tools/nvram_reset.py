import sys
import asyncio
import logging

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import NwkNvIds
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def nvram_reset(znp: ZNP) -> None:
    LOGGER.info("Clearing config and state on next start")
    await znp.nvram_write(
        NwkNvIds.STARTUP_OPTION,
        t.StartupOptions.ClearConfig | t.StartupOptions.ClearState,
    )

    delete_rsp1 = await znp.request(
        c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK1, ItemLen=1)
    )

    if delete_rsp1.Status != t.Status.SUCCESS:
        LOGGER.warning(
            "Failed to clear %s: %s",
            NwkNvIds.HAS_CONFIGURED_ZSTACK1,
            delete_rsp1.Status,
        )

    delete_rsp2 = await znp.request(
        c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1)
    )

    if delete_rsp2.Status != t.Status.SUCCESS:
        LOGGER.warning(
            "Failed to clear %s: %s",
            NwkNvIds.HAS_CONFIGURED_ZSTACK3,
            delete_rsp2.Status,
        )

    LOGGER.info("Resetting...")
    await znp.request_callback_rsp(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        callback=c.SYS.ResetInd.Callback(partial=True),
    )


async def main(argv):
    parser = setup_parser("Reset a radio's state")

    args = parser.parse_args(argv)

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))

    await znp.connect(check_version=False)
    await nvram_reset(znp)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
