import sys
import asyncio
import logging

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import (
    NWK_NVID_TABLES,
    NWK_NVID_TABLE_KEYS,
    ExNvIds,
    OsalNvIds,
)
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def nvram_reset(znp: ZNP) -> None:
    # The legacy items are shared by all Z-Stack versions
    for nvid in OsalNvIds:
        if nvid in NWK_NVID_TABLES:
            start = nvid
            end = NWK_NVID_TABLES[nvid]

            for nvid in range(start, end + 1):
                deleted = await znp.nvram.osal_delete(nvid)

                if not deleted:
                    break

                LOGGER.info("Cleared %s[%s]", start, nvid - start)
        elif nvid in NWK_NVID_TABLE_KEYS:
            continue
        else:
            if await znp.nvram.osal_delete(nvid):
                LOGGER.info("Cleared %s", nvid)
            else:
                LOGGER.debug("Item does not exist: %s", nvid)

    if znp.version >= 3.30:
        for nvid in ExNvIds:
            # Skip the LEGACY items, we did them above
            if nvid == ExNvIds.LEGACY:
                continue

            for sub_id in range(2**16):
                existed = await znp.nvram.delete(item_id=nvid, sub_id=sub_id)
                LOGGER.info("Cleared %s[0x%04X]", nvid.name, sub_id)

                if not existed:
                    # Once a delete fails, no later reads will succeed
                    break

    LOGGER.info("Resetting...")
    await znp.reset()


async def main(argv):
    parser = setup_parser("Reset a radio's state")
    parser.add_argument(
        "-c",
        "--clear",
        action="store_true",
        default=False,
        help="Deprecated: tries to delete every NVRAM value.",
    )
    args = parser.parse_args(argv)

    if args.clear:
        LOGGER.warning(
            "The -c/--clear command line argument now the default"
            " and will be removed in a future release."
        )

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))

    await znp.connect()
    await nvram_reset(znp)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
