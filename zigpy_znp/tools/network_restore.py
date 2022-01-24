from __future__ import annotations

import sys
import json
import asyncio

import zigpy.state
import zigpy.zdo.types as zdo_t

import zigpy_znp.const as const
import zigpy_znp.types as t
from zigpy_znp.api import ZNP
from zigpy_znp.tools.common import ClosableFileType, setup_parser, validate_backup_json
from zigpy_znp.zigbee.application import ControllerApplication


def json_backup_to_zigpy_state(
    backup: t.JSONType,
) -> tuple[zigpy.state.NetworkInfo, zigpy.state.NodeInfo]:
    """
    Converts a JSON backup into a zigpy network and node info tuple.
    """

    node_info = zigpy.state.NodeInfo()
    node_info.nwk = 0x0000
    node_info.logical_type = zdo_t.LogicalType.Coordinator
    node_info.ieee, _ = t.EUI64.deserialize(
        bytes.fromhex(backup["coordinator_ieee"])[::-1]
    )

    network_info = zigpy.state.NetworkInfo()
    network_info.pan_id, _ = t.NWK.deserialize(bytes.fromhex(backup["pan_id"])[::-1])
    network_info.extended_pan_id, _ = t.EUI64.deserialize(
        bytes.fromhex(backup["extended_pan_id"])[::-1]
    )
    network_info.nwk_update_id = backup["nwk_update_id"]
    network_info.nwk_manager_id = 0x0000
    network_info.channel = backup["channel"]
    network_info.channel_mask = t.Channels.from_channel_list(backup["channel_mask"])
    network_info.security_level = backup["security_level"]
    network_info.stack_specific = backup.get("stack_specific")
    network_info.tc_link_key = zigpy.state.Key()
    network_info.tc_link_key.key = const.DEFAULT_TC_LINK_KEY

    network_info.network_key = zigpy.state.Key()
    network_info.network_key.key, _ = t.KeyData.deserialize(
        bytes.fromhex(backup["network_key"]["key"])
    )
    network_info.network_key.tx_counter = backup["network_key"]["frame_counter"]
    network_info.network_key.rx_counter = 0
    network_info.network_key.partner_ieee = None
    network_info.network_key.seq = backup["network_key"]["sequence_number"]

    network_info.children = []
    network_info.nwk_addresses = {}

    for obj in backup["devices"]:
        node = zigpy.state.NodeInfo()

        if obj["nwk_address"] is not None:
            node.nwk, _ = t.NWK.deserialize(bytes.fromhex(obj["nwk_address"])[::-1])
        else:
            node.nwk = None

        node.ieee, _ = t.EUI64.deserialize(bytes.fromhex(obj["ieee_address"])[::-1])
        node.logical_type = None

        # The `is_child` key is currently optional
        if obj.get("is_child", True):
            network_info.children.append(node.ieee)

        if node.nwk is not None:
            network_info.nwk_addresses[node.ieee] = node.nwk

        if "link_key" in obj:
            key = zigpy.state.Key()
            key.key, _ = t.KeyData.deserialize(bytes.fromhex(obj["link_key"]["key"]))
            key.tx_counter = obj["link_key"]["tx_counter"]
            key.rx_counter = obj["link_key"]["rx_counter"]
            key.partner_ieee = node.ieee
            key.seq = 0

            network_info.key_table.append(key)

        # XXX: Devices that are not children, have no NWK address, and have no link key
        #      are effectively ignored, since there is no place to write them

    return network_info, node_info


async def restore_network(
    radio_path: str,
    backup: t.JSONType,
    counter_increment: int,
) -> None:
    network_info, node_info = json_backup_to_zigpy_state(backup)
    network_info.network_key.tx_counter += counter_increment

    znp = ZNP(ControllerApplication.SCHEMA({"device": {"path": radio_path}}))
    await znp.connect()
    await znp.write_network_info(network_info=network_info, node_info=node_info)
    await znp.reset()
    znp.close()


async def main(argv: list[str]) -> None:
    parser = setup_parser("Restore adapter network settings")
    parser.add_argument(
        "--input", "-i", type=ClosableFileType("r"), help="Input file", required=True
    )
    parser.add_argument(
        "--counter-increment",
        "-c",
        type=t.uint32_t,
        help="Counter increment",
        default=2500,
    )
    args = parser.parse_args(argv)

    with args.input as f:
        backup = json.load(f)

    validate_backup_json(backup)

    await restore_network(
        radio_path=args.serial,
        backup=backup,
        counter_increment=args.counter_increment,
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
