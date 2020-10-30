import sys
import asyncio
import logging

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.exceptions import CommandNotRecognized
from zigpy_znp.types.nvids import (
    NWK_NVID_TABLES,
    NWK_NVID_TABLE_KEYS,
    NvSysIds,
    NwkNvIds,
    OsalExNvIds,
)
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def nvram_reset(znp: ZNP, clear: bool = False) -> None:
    if clear:
        nvids = NwkNvIds
    else:
        nvids = [NwkNvIds.HAS_CONFIGURED_ZSTACK1, NwkNvIds.HAS_CONFIGURED_ZSTACK3]

    for nvid in nvids:
        if nvid in NWK_NVID_TABLES:
            start = nvid
            end = NWK_NVID_TABLES[nvid]

            for nvid in range(start, end + 1):
                try:
                    deleted = await znp.nvram.osal_delete(nvid)
                    LOGGER.info("Cleared %s[%s]", start, nvid - start)

                    if not deleted:
                        break
                except KeyError:
                    break
        elif nvid in NWK_NVID_TABLE_KEYS:
            continue
        else:
            if await znp.nvram.osal_delete(nvid):
                LOGGER.info("Cleared %s", nvid)
            else:
                LOGGER.debug("Item does not exist: %s", nvid)

    if clear:
        for nvid in OsalExNvIds:
            # Skip the LEGACY items, we did them above
            if nvid == OsalExNvIds.LEGACY:
                continue

            for sub_id in range(2 ** 16):
                try:
                    await znp.nvram.read(
                        sys_id=NvSysIds.ZSTACK, item_id=nvid, sub_id=sub_id
                    )
                    await znp.nvram.delete(
                        sys_id=NvSysIds.ZSTACK, item_id=nvid, sub_id=sub_id
                    )
                except CommandNotRecognized:
                    # CC2531 only supports the legacy NVRAM interface, even on Z-Stack 3
                    return
                except KeyError:
                    # Once a delete fails, no later reads will succeed
                    break

                LOGGER.info("Cleared %s[0x%04X]", nvid.name, sub_id)
    else:
        LOGGER.info("Clearing config and state on next start")
        await znp.nvram.osal_write(
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
