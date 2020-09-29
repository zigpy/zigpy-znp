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


async def nvram_reset(znp: ZNP, clear: bool = False) -> None:
    if clear:
        nvids = NwkNvIds
    else:
        nvids = [NwkNvIds.HAS_CONFIGURED_ZSTACK1, NwkNvIds.HAS_CONFIGURED_ZSTACK3]

    for nvid in nvids:
        if await znp.nvram_delete(nvid):
            LOGGER.info("Cleared %s", nvid)
        else:
            LOGGER.debug("Item does not exist: %s", nvid)

    LOGGER.info("Clearing config and state on next start")
    await znp.nvram_write(
        NwkNvIds.STARTUP_OPTION,
        t.StartupOptions.ClearConfig | t.StartupOptions.ClearState,
        create=True,
    )

    LOGGER.info("Resetting...")
    await znp.request_callback_rsp(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        callback=c.SYS.ResetInd.Callback(partial=True),
    )


async def main(argv):
    parser = setup_parser("Reset a radio's state")
    parser.add_argument(
        "-c",
        "--clear",
        action="store_true",
        default=False,
        help="Tries to delete every NVRAM value.",
    )

    args = parser.parse_args(argv)

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))

    await znp.connect(check_version=False)
    await nvram_reset(znp, clear=args.clear)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
