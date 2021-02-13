import sys
import json
import typing
import asyncio
import logging
import datetime

import zigpy_znp
import zigpy_znp.types as t
from zigpy_znp.exceptions import SecurityError
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.tools.common import setup_parser
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


def rotate(lst, n):
    return lst[n:] + lst[:n]


async def get_tc_frame_counter(app: ControllerApplication) -> t.uint32_t:
    # Older Z-Stack devices are simple
    if app._znp.version == 1.2:
        nwkkey = await app._znp.nvram.osal_read(OsalNvIds.NWKKEY)
        key_info, _ = t.NwkActiveKeyItems.deserialize(nwkkey)

        return key_info.FrameCounter

    global_entry = None

    if app._znp.version == 3.0:
        entries = app._znp.nvram.osal_read_table(
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            item_type=t.NwkSecMaterialDesc,
        )
    else:
        entries = app._znp.nvram.read_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            item_type=t.NwkSecMaterialDesc,
        )

    async for entry in entries:
        if entry.ExtendedPanID == app.extended_pan_id:
            # Always prefer the entry for our current network
            return entry.FrameCounter
        elif entry.ExtendedPanID == t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
            # But keep track of the global entry if it already exists
            global_entry = entry

    if global_entry is None:
        raise RuntimeError("No security material entry was found for this network")

    return global_entry.FrameCounter


async def get_hashed_link_keys(app: ControllerApplication):
    if app._znp.version == 1.2:
        return

    seed = await app._znp.nvram.osal_read(OsalNvIds.TCLK_SEED)

    if app._znp.version == 3.30:
        table = app._znp.nvram.read_table(
            item_id=ExNvIds.TCLK_TABLE,
            item_type=t.TCLKDevEntry,
        )
    else:
        table = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            item_type=t.TCLKDevEntry,
        )

    async for entry in table:
        if entry.extAddr == t.EUI64.convert("00:00:00:00:00:00:00:00"):
            continue

        if entry.keyAttributes != t.KeyAttributes.VERIFIED_KEY:
            continue

        LOGGER.debug("Read hashed link key: %s", entry)

        ieee = entry.extAddr.serialize()
        rotated_seed = rotate(seed, n=entry.SeedShift_IcIndex)
        link_key_data = bytes(a ^ b for a, b in zip(rotated_seed, ieee + ieee))
        link_key, _ = t.KeyData.deserialize(link_key_data)

        yield entry.extAddr, entry.txFrmCntr, entry.rxFrmCntr, link_key


async def get_unhashed_link_keys(app: ControllerApplication, addr_mgr_entries):
    if app._znp.version == 3.30:
        link_key_offset_base = 0x0000
        table = app._znp.nvram.read_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            item_type=t.LinkKeyTableEntry,
        )
    else:
        link_key_offset_base = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START
        table = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            item_type=t.LinkKeyTableEntry,
        )

    try:
        aps_key_data_table = [entry async for entry in table]
    except SecurityError:
        # CC2531 with Z-Stack Home 1.2 just doesn't let you read this data out
        return

    link_key_table, _ = t.APSLinkKeyTable.deserialize(
        await app._znp.nvram.osal_read(OsalNvIds.APS_LINK_KEY_TABLE)
    )

    for entry in link_key_table:
        if not entry.AuthenticationState & t.AuthenticationOption.AuthenticatedCBCK:
            continue

        key_table_entry = aps_key_data_table[
            entry.LinkKeyTableOffset - link_key_offset_base
        ]
        addr_mgr_entry = addr_mgr_entries[entry.AddressManagerIndex]

        assert addr_mgr_entry.type & t.AddrMgrUserType.Assoc
        assert addr_mgr_entry.type & t.AddrMgrUserType.Security

        yield (
            addr_mgr_entry.extAddr,
            key_table_entry.TxFrameCounter,
            key_table_entry.RxFrameCounter,
            key_table_entry.Key,
        )


async def get_link_keys(app: ControllerApplication, addr_mgr_entries):
    keys = {}

    async for ieee, tx_ctr, rx_ctr, key in get_unhashed_link_keys(
        app, addr_mgr_entries
    ):
        keys[ieee] = tx_ctr, rx_ctr, key

    async for ieee, tx_ctr, rx_ctr, key in get_hashed_link_keys(app):
        if ieee in keys and key != keys[ieee][2]:
            LOGGER.error(
                "Hashed link key for %s conflicts with full key: %s != %s",
                ieee,
                key,
                keys[ieee][2],
            )
            continue

        keys[ieee] = tx_ctr, rx_ctr, key

    return keys


async def get_addr_manager_entries(app: ControllerApplication):
    if app._znp.version < 3.30:
        table = await app._znp.nvram.osal_read(
            OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
        )
    else:
        table = [
            entry
            async for entry in app._znp.nvram.read_table(
                item_id=ExNvIds.ADDRMGR,
                item_type=t.AddrMgrEntry,
            )
        ]

    return table


async def get_devices(app: ControllerApplication):
    addr_mgr_entries = await get_addr_manager_entries(app)
    link_keys = await get_link_keys(app, addr_mgr_entries)

    for entry in addr_mgr_entries:
        if entry.nwkAddr == 0xFFFF:
            continue

        obj = {
            "nwk": entry.nwkAddr.serialize()[::-1].hex(),
            "ieee": entry.extAddr.serialize()[::-1].hex(),
        }

        if entry.extAddr in link_keys:
            tx_ctr, rx_ctr, key = link_keys[entry.extAddr]

            obj["link_key"] = {
                "tx_counter": tx_ctr,
                "rx_counter": rx_ctr,
                "key": key.serialize().hex(),
            }

        yield obj


async def backup_network(
    radio_path: str,
) -> typing.Dict[str, typing.Any]:
    LOGGER.info("Starting up zigpy-znp")

    config = ControllerApplication.SCHEMA({"device": {"path": radio_path}})
    app = ControllerApplication(config)
    await app.startup(read_only=True)

    devices = [d async for d in get_devices(app)]
    devices.sort(key=lambda d: d["nwk"])

    now = datetime.datetime.now().astimezone()

    obj = {
        "metadata": {
            "version": 1,
            "format": "zigpy/open-coordinator-backup",
            "source": f"zigpy-znp@{zigpy_znp.__version__}",
            "internal": {
                "creation_time": now.isoformat(timespec="seconds"),
                "zstack": {
                    "version": app._znp.version,
                },
            },
        },
        "coordinator_ieee": app.ieee.serialize()[::-1].hex(),
        "pan_id": app.pan_id.serialize()[::-1].hex(),
        "extended_pan_id": app.extended_pan_id.serialize()[::-1].hex(),
        "nwk_update_id": app._nib.nwkUpdateId,
        "security_level": app._nib.SecurityLevel,
        "channel": app.channel,
        "channel_mask": [
            c
            for c in range(11, 26 + 1)
            if t.Channels.from_channel_list([c]) | app._nib.channelList
        ],
        "network_key": {
            "key": app.network_key.serialize().hex(),
            "sequence_number": app.network_key_seq,
            "frame_counter": await get_tc_frame_counter(app),
        },
        "devices": devices,
    }

    if app._znp.version > 1.2:
        tclk_seed = await app._znp.nvram.osal_read(OsalNvIds.TCLK_SEED)
        LOGGER.info("TCLK seed: %s", tclk_seed.hex())

        obj["stack_specific"] = {"zstack": {"tclk_seed": tclk_seed.hex()}}

    await app._reset()

    return obj


async def main(argv):
    parser = setup_parser("Backup adapter network settings")
    args = parser.parse_args(argv)

    backup_obj = await backup_network(
        radio_path=args.serial,
    )

    print(json.dumps(backup_obj, indent=4))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
