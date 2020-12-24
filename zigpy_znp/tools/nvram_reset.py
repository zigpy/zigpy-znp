import sys
import asyncio
import logging

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import (
    NWK_NVID_TABLES,
    NWK_NVID_TABLE_KEYS,
    ExNvIds,
    NvSysIds,
    OsalNvIds,
)
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def nvram_reset(znp: ZNP, clear: bool = False) -> None:
    if clear:
        nvids = OsalNvIds
    else:
        nvids = [OsalNvIds.HAS_CONFIGURED_ZSTACK1, OsalNvIds.HAS_CONFIGURED_ZSTACK3]

    # The legacy items are shared by all Z-Stack versions
    for nvid in nvids:
        if nvid in NWK_NVID_TABLES:
            start = nvid
            end = NWK_NVID_TABLES[nvid]

            for nvid in range(start, end + 1):
                deleted = await znp.nvram.osal_delete(nvid)
                LOGGER.info("Cleared %s[%s]", start, nvid - start)

                if not deleted:
                    break
        elif nvid in NWK_NVID_TABLE_KEYS:
            continue
        else:
            if await znp.nvram.osal_delete(nvid):
                LOGGER.info("Cleared %s", nvid)
            else:
                LOGGER.debug("Item does not exist: %s", nvid)

    if clear and znp.version >= 3.30:
        for nvid in ExNvIds:
            # Skip the LEGACY items, we did them above
            if nvid == ExNvIds.LEGACY:
                continue

            for sub_id in range(2 ** 16):
                existed = await znp.nvram.delete(
                    sys_id=NvSysIds.ZSTACK, item_id=nvid, sub_id=sub_id
                )
                LOGGER.info("Cleared %s[0x%04X]", nvid.name, sub_id)

                if not existed:
                    # Once a delete fails, no later reads will succeed
                    break

    # Even though we cleared NVRAM, some data is inaccessible and Z-Stack needs to do it
    LOGGER.info("Clearing config and state on next start")
    await znp.nvram.osal_write(
        OsalNvIds.STARTUP_OPTION,
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

    await znp.connect()
    await nvram_reset(znp, clear=args.clear)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
