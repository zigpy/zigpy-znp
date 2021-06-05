import sys
import json
import asyncio
import logging

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.tools.common import ClosableFileType, setup_parser

LOGGER = logging.getLogger(__name__)


async def nvram_write(znp: ZNP, backup):
    # First write the NVRAM items common to all radios
    for nwk_nvid, value in backup["LEGACY"].items():
        if "+" in nwk_nvid:
            nwk_nvid, _, offset = nwk_nvid.partition("+")
            offset = int(offset)
            nvid = OsalNvIds[nwk_nvid] + offset
        else:
            nvid = OsalNvIds[nwk_nvid]
            offset = None

        if offset is not None:
            LOGGER.info("%s+%s = %r", OsalNvIds[nwk_nvid].name, offset, value)
        else:
            LOGGER.info("%s = %r", OsalNvIds[nwk_nvid].name, value)

        await znp.nvram.osal_write(nvid, bytes.fromhex(value), create=True)

    for item_name, sub_ids in backup.items():
        item_id = ExNvIds[item_name]

        if item_id == ExNvIds.LEGACY:
            continue

        for sub_id, value in sub_ids.items():
            sub_id = int(sub_id, 16)
            LOGGER.info("%s[0x%04X] = %r", item_id.name, sub_id, value)

            await znp.nvram.write(
                item_id=item_id,
                sub_id=sub_id,
                value=bytes.fromhex(value),
                create=True,
            )

    # Reset afterwards to have the new values take effect
    await znp.reset()


async def main(argv):
    parser = setup_parser("Restore a radio's NVRAM from a previous backup")
    parser.add_argument(
        "--input", "-i", type=ClosableFileType("r"), help="Input file", required=True
    )

    args = parser.parse_args(argv)

    with args.input as f:
        backup = json.load(f)

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))
    await znp.connect()

    await nvram_write(znp, backup)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
