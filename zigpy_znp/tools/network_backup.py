from __future__ import annotations

import sys
import json
import asyncio
import logging
import datetime

import zigpy.state

import zigpy_znp
import zigpy_znp.types as t
from zigpy_znp.api import ZNP
from zigpy_znp.tools.common import ClosableFileType, setup_parser, validate_backup_json
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


def zigpy_state_to_json_backup(
    network_info: zigpy.state.NetworkInfo, node_info: zigpy.state.NodeInfo
) -> t.JSONType:
    devices = {}

    for ieee, nwk in network_info.nwk_addresses.items():
        devices[ieee] = {
            "ieee_address": ieee.serialize()[::-1].hex(),
            "nwk_address": nwk.serialize()[::-1].hex(),
            "is_child": False,
        }

    for ieee in network_info.children:
        nwk = network_info.nwk_addresses.get(ieee, None)
        devices[ieee] = {
            "ieee_address": ieee.serialize()[::-1].hex(),
            "nwk_address": nwk.serialize()[::-1].hex() if nwk is not None else None,
            "is_child": True,
        }

    for key in network_info.key_table:
        if key.partner_ieee not in devices:
            devices[key.partner_ieee] = {
                "ieee_address": key.partner_ieee.serialize()[::-1].hex(),
                "nwk_address": None,
                "is_child": False,
            }

        devices[key.partner_ieee]["link_key"] = {
            "key": key.key.serialize().hex(),
            "tx_counter": key.tx_counter,
            "rx_counter": key.rx_counter,
        }

    return {
        "metadata": {
            "version": 1,
            "format": "zigpy/open-coordinator-backup",
            "source": None,
            "internal": None,
        },
        "coordinator_ieee": node_info.ieee.serialize()[::-1].hex(),
        "pan_id": network_info.pan_id.serialize()[::-1].hex(),
        "extended_pan_id": network_info.extended_pan_id.serialize()[::-1].hex(),
        "nwk_update_id": network_info.nwk_update_id,
        "security_level": network_info.security_level,
        "channel": network_info.channel,
        "channel_mask": list(network_info.channel_mask),
        "network_key": {
            "key": network_info.network_key.key.serialize().hex(),
            "sequence_number": network_info.network_key.seq,
            "frame_counter": network_info.network_key.tx_counter,
        },
        "devices": sorted(devices.values(), key=lambda d: d["ieee_address"]),
    }


async def backup_network(znp: ZNP) -> t.JSONType:
    await znp.load_network_info(load_devices=True)

    obj = zigpy_state_to_json_backup(
        network_info=znp.network_info,
        node_info=znp.node_info,
    )

    now = datetime.datetime.now().astimezone()

    obj["metadata"]["source"] = f"zigpy-znp@{zigpy_znp.__version__}"
    obj["metadata"]["internal"] = {
        "creation_time": now.isoformat(timespec="seconds"),
        "zstack": {
            "version": znp.version,
        },
    }

    if znp.network_info.stack_specific:
        obj["stack_specific"] = znp.network_info.stack_specific

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
