import sys
import json
import typing
import asyncio
import logging
import argparse

import zigpy_znp.types as t
import zigpy_znp.config as conf
from zigpy_znp.znp.nib import NIB
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.tools.common import setup_parser
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


async def set_tc_frame_counter(app: ControllerApplication, counter: t.uint32_t):
    if app._znp.version == 1.2:
        # Older Z-Stack devices are simpler
        key_info = await app._znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )
        key_info.FrameCounter = counter

        await app._znp.nvram.osal_write(OsalNvIds.NWKKEY, key_info)

        return

    best_entry = None
    best_address = None

    if app._znp.version == 3.0:
        address = OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START
        entries = app._znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            item_type=t.NwkSecMaterialDesc,
        )
    else:
        address = 0x0000
        entries = app._znp.nvram.read_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            item_type=t.NwkSecMaterialDesc,
        )

    async for entry in entries:
        if entry.ExtendedPanID == app.extended_pan_id:
            best_entry = entry
            best_address = address
            break
        elif best_entry is None and entry.ExtendedPanID == t.EUI64.convert(
            "FF:FF:FF:FF:FF:FF:FF:FF"
        ):
            best_entry = entry
            best_address = address

        address += 1
    else:
        raise RuntimeError("Failed to find open slot for security material entry")

    best_entry.FrameCounter = counter

    if app._znp.version == 3.0:
        await app._znp.nvram.osal_write(best_address, best_entry)
    else:
        await app._znp.nvram.write(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            sub_id=best_address,
            value=best_entry,
        )


def rotate(lst, n):
    return lst[n:] + lst[:n]


def compute_key(ieee, seed, shift):
    rotated_seed = rotate(seed, n=shift)
    return t.KeyData([a ^ b for a, b in zip(rotated_seed, 2 * ieee.serialize())])


def compute_seed(ieee, key, shift):
    rotated_seed = bytes(a ^ b for a, b in zip(key, 2 * ieee.serialize()))
    return rotate(rotated_seed, n=-shift)


def find_key_shift(ieee, key, seed):
    for shift in range(0x00, 0x0F):
        if seed == compute_seed(ieee, key, shift):
            return shift

    return None


def iter_seed_candidates(ieees_and_keys):
    for ieee, key in ieees_and_keys:
        # Derive a seed from each candidate
        seed = compute_seed(ieee, key, 0)

        # And see how many other keys share this same seed
        count = sum(find_key_shift(i, k, seed) is not None for i, k in ieees_and_keys)

        yield count, seed

        # If all of the keys are derived from this seed, we can stop searching
        if count == len(ieees_and_keys):
            break


async def write_addr_manager_entries(
    app: ControllerApplication, entries: typing.Iterable[t.AddrMgrEntry]
):
    if app._znp.version >= 3.30:
        await app._znp.nvram.write_table(
            item_id=ExNvIds.ADDRMGR,
            values=entries,
            fill_value=t.EMPTY_ADDR_MGR_ENTRY,
        )
        return

    old_entries = await app._znp.nvram.osal_read(
        OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
    )
    new_entries = len(old_entries) * [t.EMPTY_ADDR_MGR_ENTRY]

    for index, entry in enumerate(entries):
        new_entries[index] = entry

    await app._znp.nvram.osal_write(
        OsalNvIds.ADDRMGR, t.AddressManagerTable(new_entries)
    )


async def add_devices(
    app: ControllerApplication, devices: typing.Iterable[typing.Dict], seed=None
):
    # Make sure we prioritize the devices with keys if there is no room
    # devices = sorted(devices, key=lambda e: e.get("link_key") is None)

    ieees_and_keys = []

    for device in devices:
        if device.get("link_key"):
            key, _ = t.KeyData.deserialize(bytes.fromhex(device["link_key"]["key"]))
            device["link_key"]["key"] = key

            ieees_and_keys.append((device["ieee"], key))

    # Find the seed that maximizes the number of keys that can be derived from it
    if seed is None and ieees_and_keys:
        _, seed = max(iter_seed_candidates(ieees_and_keys))

    addr_mgr_entries = []
    tclk_table = []
    aps_key_data_table = []

    old_link_key_table = await app._znp.nvram.osal_read(OsalNvIds.APS_LINK_KEY_TABLE)
    link_key_table = t.APSLinkKeyTable()

    for index, device in enumerate(devices):
        entry_type = t.AddrMgrUserType.Assoc

        if device.get("link_key"):
            entry_type |= t.AddrMgrUserType.Security

        addr_mgr_entries.append(
            t.AddrMgrEntry(
                type=entry_type,
                nwkAddr=device["nwk"],
                extAddr=device["ieee"],
            )
        )

        if not device.get("link_key"):
            continue

        key = device["link_key"]["key"]
        shift = find_key_shift(device["ieee"], key, seed)

        if shift is None:
            aps_key_data_table.append(
                t.LinkKeyTableEntry(
                    Key=key,
                    TxFrameCounter=device["link_key"]["tx_counter"],
                    RxFrameCounter=device["link_key"]["rx_counter"],
                )
            )

            if app._znp.version < 3.30:
                start = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START
            else:
                start = 0

            offset = len(aps_key_data_table) - 1

            link_key_table.append(
                t.APSLinkKeyTableEntry(
                    AddressManagerIndex=index,
                    LinkKeyTableOffset=start + offset,
                    AuthenticationState=t.AuthenticationOption.AuthenticatedCBCK,
                )
            )
        else:
            tclk_table.append(
                t.TCLKDevEntry(
                    txFrmCntr=device["link_key"]["tx_counter"],
                    rxFrmCntr=device["link_key"]["rx_counter"],
                    extAddr=device["ieee"],
                    keyAttributes=t.KeyAttributes.VERIFIED_KEY,
                    keyType=t.KeyType.NONE,
                    SeedShift_IcIndex=shift,
                )
            )

    if len(link_key_table.serialize()) > len(old_link_key_table):
        raise RuntimeError("New link key table is larger than the current one")

    link_key_table_value = link_key_table.serialize().ljust(
        len(old_link_key_table), b"\x00"
    )
    await app._znp.nvram.osal_write(OsalNvIds.APS_LINK_KEY_TABLE, link_key_table_value)

    await write_addr_manager_entries(app, addr_mgr_entries)

    tclk_fill_value = t.TCLKDevEntry(
        txFrmCntr=0,
        rxFrmCntr=0,
        extAddr=t.EUI64.convert("00:00:00:00:00:00:00:00"),
        keyAttributes=t.KeyAttributes.PROVISIONAL_KEY,
        keyType=t.KeyType.NONE,
        SeedShift_IcIndex=0,
    )

    if app._znp.version == 3.30:
        await app._znp.nvram.write_table(
            item_id=ExNvIds.TCLK_TABLE,
            values=tclk_table,
            fill_value=tclk_fill_value,
        )

        await app._znp.nvram.write_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            values=aps_key_data_table,
            fill_value=t.LinkKeyTableEntry(
                Key=t.KeyData([0x00] * 16),
                TxFrameCounter=0,
                RxFrameCounter=0,
            ),
        )
    else:
        await app._znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            values=tclk_table,
            fill_value=tclk_fill_value,
        )

        await app._znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            values=aps_key_data_table,
            fill_value=t.LinkKeyTableEntry(
                Key=t.KeyData([0x00] * 16),
                TxFrameCounter=0,
                RxFrameCounter=0,
            ),
        )


async def restore_network(
    radio_path: str,
    backup: typing.Dict[str, typing.Any],
):
    LOGGER.info("Starting up zigpy-znp")

    pan_id, _ = t.NWK.deserialize(bytes.fromhex(backup["pan_id"])[::-1])
    extended_pan_id, _ = t.EUI64.deserialize(
        bytes.fromhex(backup["extended_pan_id"])[::-1]
    )
    coordinator_ieee, _ = t.EUI64.deserialize(
        bytes.fromhex(backup["coordinator_ieee"])[::-1]
    )
    nwk_key, _ = t.KeyData.deserialize(bytes.fromhex(backup["network_key"]["key"]))

    config = ControllerApplication.SCHEMA({"device": {"path": radio_path}})
    app = ControllerApplication(config)

    app.config[conf.CONF_NWK][conf.CONF_NWK_KEY] = nwk_key
    app.config[conf.CONF_NWK][conf.CONF_NWK_PAN_ID] = pan_id
    app.config[conf.CONF_NWK][conf.CONF_NWK_CHANNEL] = backup["channel"]
    app.config[conf.CONF_NWK][conf.CONF_NWK_EXTENDED_PAN_ID] = extended_pan_id

    await app.startup(force_form=True)
    await app._reset()

    await app._znp.nvram.osal_write(OsalNvIds.EXTADDR, coordinator_ieee)

    nib = await app._znp.nvram.osal_read(OsalNvIds.NIB, item_type=NIB)
    nib.channelList = t.Channels.from_channel_list(backup["channel_mask"])
    nib.nwkUpdateId = backup["nwk_update_id"]
    nib.SecurityLevel = backup["security_level"]
    await app._znp.nvram.osal_write(OsalNvIds.NIB, nib)

    tclk_seed = None

    if app._znp.version > 1.20:
        if backup.get("stack_specific", {}).get("zstack", {}).get("tclk_seed"):
            tclk_seed = bytes.fromhex(backup["stack_specific"]["zstack"]["tclk_seed"])
            await app._znp.nvram.osal_write(OsalNvIds.TCLK_SEED, tclk_seed)

    nwk_frame_counter = backup["network_key"]["frame_counter"]

    key_info = t.NwkActiveKeyItems(
        Active=t.NwkKeyDesc(
            KeySeqNum=backup["network_key"]["sequence_number"],
            Key=nwk_key,
        ),
        FrameCounter=nwk_frame_counter,
    )

    await app._znp.nvram.osal_write(OsalNvIds.NWKKEY, key_info)
    await app._znp.nvram.osal_write(OsalNvIds.NWK_ACTIVE_KEY_INFO, key_info.Active)
    await app._znp.nvram.osal_write(OsalNvIds.NWK_ALTERN_KEY_INFO, key_info.Active)
    await set_tc_frame_counter(app, nwk_frame_counter)

    for device in backup["devices"]:
        device["nwk"], _ = t.NWK.deserialize(bytes.fromhex(device["nwk"])[::-1])
        device["ieee"], _ = t.EUI64.deserialize(bytes.fromhex(device["ieee"])[::-1])

    await add_devices(app, backup["devices"], seed=tclk_seed)

    await app._reset()


async def main(argv):
    parser = setup_parser("Restore adapter network settings")
    parser.add_argument(
        "--input", "-i", type=argparse.FileType("r"), help="Input file", required=True
    )
    args = parser.parse_args(argv)

    backup = json.load(args.input)

    await restore_network(
        radio_path=args.serial,
        backup=backup,
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
