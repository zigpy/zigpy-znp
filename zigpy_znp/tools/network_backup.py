from __future__ import annotations

import sys
import json
import asyncio
import logging
import datetime

import zigpy_znp
import zigpy_znp.types as t
from zigpy_znp.api import ZNP
from zigpy_znp.types.nvids import OsalNvIds
from zigpy_znp.tools.common import ClosableFileType, setup_parser, validate_backup_json
from zigpy_znp.znp.security import read_devices, read_tc_frame_counter
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


async def backup_network(znp: ZNP) -> t.JSONType:
    try:
        await znp.load_network_info()
    except ValueError as e:
        raise RuntimeError("Failed to load network info") from e

    devices = []

    for device in await read_devices(znp):
        obj = {
            "nwk_address": device.nwk.serialize()[::-1].hex(),
            "ieee_address": device.ieee.serialize()[::-1].hex(),
        }

        if device.aps_link_key:
            obj["link_key"] = {
                "tx_counter": device.tx_counter,
                "rx_counter": device.rx_counter,
                "key": device.aps_link_key.serialize().hex(),
            }

        devices.append(obj)

    devices.sort(key=lambda d: d["ieee_address"])

    now = datetime.datetime.now().astimezone()

    obj = {
        "metadata": {
            "version": 1,
            "format": "zigpy/open-coordinator-backup",
            "source": f"zigpy-znp@{zigpy_znp.__version__}",
            "internal": {
                "creation_time": now.isoformat(timespec="seconds"),
                "zstack": {
                    "version": znp.version,
                },
            },
        },
        "coordinator_ieee": znp.network_info.ieee.serialize()[::-1].hex(),
        "pan_id": znp.network_info.pan_id.serialize()[::-1].hex(),
        "extended_pan_id": znp.network_info.extended_pan_id.serialize()[::-1].hex(),
        "nwk_update_id": znp.network_info.nwk_update_id,
        "security_level": znp.network_info.security_level,
        "channel": znp.network_info.channel,
        "channel_mask": list(znp.network_info.channels),
        "network_key": {
            "key": znp.network_info.network_key.serialize().hex(),
            "sequence_number": znp.network_info.network_key_seq,
            "frame_counter": await read_tc_frame_counter(znp),
        },
        "devices": devices,
    }

    if znp.version > 1.2:
        tclk_seed = await znp.nvram.osal_read(OsalNvIds.TCLK_SEED, item_type=t.Bytes)
        LOGGER.info("TCLK seed: %s", tclk_seed.hex())

        obj["stack_specific"] = {"zstack": {"tclk_seed": tclk_seed.hex()}}

    # Ensure our generated backup is valid
    validate_backup_json(obj)

    return obj


async def main(argv: list[str]) -> None:
    parser = setup_parser("Backup adapter network settings")
    parser.add_argument(
        "--output", "-o", type=ClosableFileType("w"), help="Output file", default="-"
    )
    args = parser.parse_args(argv)

    with args.output as f:
        znp = ZNP(ControllerApplication.SCHEMA({"device": {"path": args.serial}}))
        await znp.connect()

        backup_obj = await backup_network(znp)
        znp.close()

        f.write(json.dumps(backup_obj, indent=4))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
