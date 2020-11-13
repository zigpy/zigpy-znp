import sys
import json
import asyncio
import logging
import argparse

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import ExNvIds, NvSysIds, OsalNvIds
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def restore(radio_path, backup):
    znp = ZNP(CONFIG_SCHEMA({"device": {"path": radio_path}}))

    await znp.connect()

    # First write the NVRAM items common to all radios
    for nwk_nvid, value in backup["LEGACY"].items():
        if "+" in nwk_nvid:
            nwk_nvid, _, offset = nwk_nvid.partition("+")
            offset = int(offset)
            nvid = OsalNvIds[nwk_nvid] + offset
        else:
            nvid = OsalNvIds[nwk_nvid]

        value = bytes.fromhex(value)
        await znp.nvram.osal_write(nvid, value, create=True)

    for item_name, sub_ids in backup.items():
        item_id = ExNvIds[item_name]

        if item_id == ExNvIds.LEGACY:
            continue

        for sub_id, value in sub_ids.items():
            sub_id = int(sub_id, 16)
            value = bytes.fromhex(value)

            await znp.nvram.write(
                sys_id=NvSysIds.ZSTACK,
                item_id=item_id,
                sub_id=sub_id,
                value=value,
                create=True,
            )

    # Reset afterwards to have the new values take effect
    await znp.request_callback_rsp(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        callback=c.SYS.ResetInd.Callback(partial=True),
    )


async def main(argv):
    parser = setup_parser("Restore a radio's NVRAM from a previous backup")
    parser.add_argument(
        "--input", "-i", type=argparse.FileType("r"), help="Input file", required=True
    )

    args = parser.parse_args(argv)
    backup = json.load(args.input)
    await restore(args.serial, backup)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
