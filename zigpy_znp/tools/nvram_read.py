import sys
import json
import asyncio
import logging
import argparse

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.exceptions import SecurityError, CommandNotRecognized
from zigpy_znp.types.nvids import NWK_NVID_TABLES, ExNvIds, NvSysIds, OsalNvIds
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def backup(radio_path: str):
    znp = ZNP(CONFIG_SCHEMA({"device": {"path": radio_path}}))
    await znp.connect()

    data = {}
    data["LEGACY"] = {}

    # Legacy items need to be handled first, since they are named
    for nwk_nvid in OsalNvIds:
        if nwk_nvid == OsalNvIds.INVALID_INDEX:
            continue

        # Tables span ranges of items. Naming them properly is useful.
        if nwk_nvid in NWK_NVID_TABLES:
            start = nwk_nvid
            end = NWK_NVID_TABLES[nwk_nvid]

            for offset in range(0, end - start):
                key = f"{nwk_nvid.name}+{offset}"

                try:
                    value = await znp.nvram.osal_read(nwk_nvid + offset)
                except SecurityError:
                    LOGGER.error("Read not allowed for %s", key)
                    continue
                except KeyError:
                    break

                LOGGER.info("%s = %s", key, value)
                data["LEGACY"][key] = value.hex()
        else:
            try:
                value = await znp.nvram.osal_read(nwk_nvid)
            except KeyError:
                LOGGER.warning("Read failed for %s", nwk_nvid)
                continue
            except SecurityError:
                LOGGER.error("Read not allowed for %s", nwk_nvid)
                continue

            LOGGER.info("%s = %s", nwk_nvid, value)
            data["LEGACY"][nwk_nvid.name] = value.hex()

    for nvid in ExNvIds:
        # Skip the LEGACY items, we did them above
        if nvid == ExNvIds.LEGACY:
            continue

        for sub_id in range(2 ** 16):
            try:
                value = await znp.nvram.read(
                    sys_id=NvSysIds.ZSTACK, item_id=nvid, sub_id=sub_id
                )
            except CommandNotRecognized:
                # CC2531 only supports the legacy NVRAM interface, even on Z-Stack 3
                return data
            except KeyError:
                # Once a read fails, no later reads will succeed
                break

            LOGGER.info("%s[0x%04X] = %s", nvid.name, sub_id, value)
            data.setdefault(nvid.name, {})[f"0x{sub_id:04X}"] = value.hex()

    return data


async def main(argv):
    parser = setup_parser("Backup a radio's NVRAM")
    parser.add_argument(
        "--output", "-o", type=argparse.FileType("w"), help="Output file", default="-"
    )

    args = parser.parse_args(argv)

    obj = await backup(args.serial)
    args.output.write(json.dumps(obj, indent=4))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
