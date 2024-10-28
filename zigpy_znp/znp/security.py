from __future__ import annotations

import typing
import logging
import dataclasses

import zigpy.state
import zigpy.zdo.types as zdo_t

import zigpy_znp.const as const
import zigpy_znp.types as t
from zigpy_znp.api import ZNP
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class StoredDevice:
    node_info: zigpy.state.NodeInfo
    key: zigpy.state.Key | None
    is_child: bool = False

    def replace(self, **kwargs) -> StoredDevice:
        return dataclasses.replace(self, **kwargs)


def rotate(lst: list, n: int) -> list:
    return lst[n:] + lst[:n]


def compute_key(ieee: t.EUI64, tclk_seed: t.KeyData, shift: int) -> t.KeyData:
    rotated_tclk_seed = rotate(tclk_seed, n=shift)
    return t.KeyData([a ^ b for a, b in zip(rotated_tclk_seed, 2 * ieee.serialize())])


def compute_tclk_seed(ieee: t.EUI64, key: t.KeyData, shift: int) -> t.KeyData:
    rotated_tclk_seed = bytes(a ^ b for a, b in zip(key, 2 * ieee.serialize()))
    return t.KeyData(rotate(rotated_tclk_seed, n=-shift))


def find_key_shift(ieee: t.EUI64, key: t.KeyData, tclk_seed: t.KeyData) -> int | None:
    for shift in range(0x00, 0x0F + 1):
        if tclk_seed == compute_tclk_seed(ieee, key, shift):
            return shift

    return None


def count_seed_matches(
    keys: typing.Sequence[zigpy.state.Key], tclk_seed: t.KeyData
) -> int:
    count = 0

    for key in keys:
        if find_key_shift(key.partner_ieee, key.key, tclk_seed) is not None:
            count += 1

    return count


def iter_seed_candidates(
    keys: typing.Sequence[zigpy.state.Key],
) -> typing.Iterable[tuple[int, t.KeyData]]:
    for key in keys:
        # Derive a seed from each candidate. All rotations of a seed are equivalent.
        tclk_seed = compute_tclk_seed(key.partner_ieee, key.key, 0)

        # And see how many other keys share this same seed
        count = count_seed_matches(keys, tclk_seed)

        yield count, tclk_seed


async def read_nwk_frame_counter(znp: ZNP, *, ext_pan_id: t.EUI64 = None) -> t.uint32_t:
    if ext_pan_id is None and znp.network_info is not None:
        ext_pan_id = znp.network_info.extended_pan_id

    if znp.version == 1.2:
        key_info = await znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )

        return key_info.FrameCounter

    global_entry = None

    if znp.version == 3.0:
        entries = znp.nvram.osal_read_table(
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            item_type=t.NwkSecMaterialDesc,
        )
    else:
        entries = znp.nvram.read_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            item_type=t.NwkSecMaterialDesc,
        )

    async for entry in entries:
        if entry.ExtendedPanID == ext_pan_id:
            # Always prefer the entry for our current network
            return entry.FrameCounter
        elif entry.ExtendedPanID == t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
            # But keep track of the global entry if it already exists
            global_entry = entry

    if global_entry is None:
        raise KeyError("No security material entry was found for this network")

    return global_entry.FrameCounter


async def write_nwk_frame_counter(
    znp: ZNP, counter: t.uint32_t, *, ext_pan_id: t.EUI64 = None
) -> None:
    if znp.version == 1.2:
        key_info = await znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )
        key_info.FrameCounter = counter

        await znp.nvram.osal_write(OsalNvIds.NWKKEY, key_info)

        return

    if ext_pan_id is None:
        ext_pan_id = znp.network_info.extended_pan_id

    entry = t.NwkSecMaterialDesc(
        FrameCounter=counter,
        ExtendedPanID=ext_pan_id,
    )

    fill_entry = t.NwkSecMaterialDesc(
        FrameCounter=0x00000000,
        ExtendedPanID=t.EUI64.convert("00:00:00:00:00:00:00:00"),
    )

    # The security material tables are quite small (4 values) so it's simpler to just
    # write them completely when updating the frame counter.
    if znp.version == 3.0:
        await znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_END,
            values=[entry],
            fill_value=fill_entry,
        )
    else:
        await znp.nvram.write_table(
            item_id=ExNvIds.NWK_SEC_MATERIAL_TABLE,
            values=[entry],
            fill_value=fill_entry,
        )


async def read_addr_manager_entries(znp: ZNP) -> typing.Sequence[t.AddrMgrEntry]:
    if znp.version >= 3.30:
        entries = [
            entry
            async for entry in znp.nvram.read_table(
                item_id=ExNvIds.ADDRMGR,
                item_type=t.AddrMgrEntry,
            )
        ]
    else:
        entries = list(
            await znp.nvram.osal_read(
                OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
            )
        )

    return entries


async def read_hashed_link_keys(  # type:ignore[misc]
    znp: ZNP, tclk_seed: t.KeyData
) -> typing.AsyncGenerator[zigpy.state.Key, None]:
    if znp.version >= 3.30:
        entries = znp.nvram.read_table(
            item_id=ExNvIds.TCLK_TABLE,
            item_type=t.TCLKDevEntry,
        )
    else:
        entries = znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            item_type=t.TCLKDevEntry,
        )

    async for entry in entries:
        if entry.extAddr == t.EUI64.convert("00:00:00:00:00:00:00:00"):
            continue

        # XXX: why do both of these types appear?
        # assert entry.keyType == t.KeyType.NWK
        # assert entry.keyType == t.KeyType.NONE

        yield zigpy.state.Key(
            key=compute_key(entry.extAddr, tclk_seed, entry.SeedShift_IcIndex),
            tx_counter=entry.txFrmCntr,
            rx_counter=entry.rxFrmCntr,
            partner_ieee=entry.extAddr,
            seq=0,
        )


async def read_unhashed_link_keys(
    znp: ZNP, addr_mgr_entries: typing.Sequence[t.AddrMgrEntry]
) -> typing.AsyncGenerator[zigpy.state.Key, None]:
    if znp.version == 3.30:
        link_key_offset_base = 0x0000
        table = znp.nvram.read_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            item_type=t.APSKeyDataTableEntry,
        )
    elif znp.version == 3.0:
        link_key_offset_base = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START
        table = znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            item_type=t.APSKeyDataTableEntry,
        )
    else:
        return

    aps_key_data_table = [entry async for entry in table]

    # The link key table's size is dynamic so it has junk at the end
    link_key_table_raw = await znp.nvram.osal_read(
        OsalNvIds.APS_LINK_KEY_TABLE, item_type=t.Bytes
    )
    link_key_table = znp.nvram.deserialize(
        link_key_table_raw, item_type=t.APSLinkKeyTable, allow_trailing=True
    )

    LOGGER.debug("Read APS link key table: %s", link_key_table)

    for entry in link_key_table:
        if entry.AuthenticationState != t.AuthenticationOption.AuthenticatedCBCK:
            continue

        key_table_entry = aps_key_data_table[entry.LinkKeyNvId - link_key_offset_base]
        addr_mgr_entry = addr_mgr_entries[entry.AddressManagerIndex]

        assert addr_mgr_entry.type & t.AddrMgrUserType.Security

        yield zigpy.state.Key(
            partner_ieee=addr_mgr_entry.extAddr,
            key=key_table_entry.Key,
            tx_counter=key_table_entry.TxFrameCounter,
            rx_counter=key_table_entry.RxFrameCounter,
            seq=0,
        )


async def read_devices(
    znp: ZNP, *, tclk_seed: t.KeyData | None
) -> typing.Sequence[StoredDevice]:
    addr_mgr = await read_addr_manager_entries(znp)
    devices = {}

    for entry in addr_mgr:
        if entry.extAddr in (
            t.EUI64.convert("00:00:00:00:00:00:00:00"),
            t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
        ):
            continue
        elif entry.type in (
            t.AddrMgrUserType.Default,
            t.AddrMgrUserType.Binding,
        ):
            continue
        elif entry.type in (
            t.AddrMgrUserType.Assoc,
            t.AddrMgrUserType.Assoc | t.AddrMgrUserType.Security,
            t.AddrMgrUserType.Security,
        ):
            is_child = bool(entry.type & t.AddrMgrUserType.Assoc)

            devices[entry.extAddr] = StoredDevice(
                node_info=zigpy.state.NodeInfo(
                    nwk=entry.nwkAddr,
                    ieee=entry.extAddr,
                    logical_type=(
                        zdo_t.LogicalType.EndDevice
                        if is_child
                        else zdo_t.LogicalType.Router
                    ),
                ),
                key=None,
                is_child=is_child,
            )
        else:
            raise ValueError(f"Unexpected entry type: {entry.type}")

    async for key in read_hashed_link_keys(znp, tclk_seed):
        if key.partner_ieee not in devices:
            LOGGER.warning(
                "Skipping hashed link key %s (tx: %s, rx: %s) for unknown device %s",
                ":".join(f"{b:02x}" for b in key.key),
                key.tx_counter,
                key.rx_counter,
                key.partner_ieee,
            )
            continue

        devices[key.partner_ieee] = devices[key.partner_ieee].replace(key=key)

    async for key in read_unhashed_link_keys(znp, addr_mgr):
        if key.partner_ieee not in devices:
            LOGGER.warning(
                "Skipping unhashed link key %s (tx: %s, rx: %s) for unknown device %s",
                ":".join(f"{b:02x}" for b in key.key),
                key.tx_counter,
                key.rx_counter,
                key.partner_ieee,
            )
            continue

        devices[key.partner_ieee] = devices[key.partner_ieee].replace(key=key)

    return list(devices.values())


async def write_addr_manager_entries(
    znp: ZNP, entries: typing.Sequence[t.AddrMgrEntry]
) -> None:
    if znp.version >= 3.30:
        await znp.nvram.write_table(
            item_id=ExNvIds.ADDRMGR,
            values=entries,
            fill_value=const.EMPTY_ADDR_MGR_ENTRY_ZSTACK3,
        )
        return

    # On older devices this "table" is a single array in NVRAM whose size is dependent
    # on compile-time constants
    old_entries = await znp.nvram.osal_read(
        OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
    )

    if znp.version >= 3.30:
        new_entries = len(old_entries) * [const.EMPTY_ADDR_MGR_ENTRY_ZSTACK3]
    else:
        new_entries = len(old_entries) * [const.EMPTY_ADDR_MGR_ENTRY_ZSTACK1]

    # Purposefully throw an `IndexError` if we are trying to write too many entries
    for index, entry in enumerate(entries):
        new_entries[index] = entry

    await znp.nvram.osal_write(OsalNvIds.ADDRMGR, t.AddressManagerTable(new_entries))


def find_optimal_tclk_seed(
    devices: typing.Sequence[StoredDevice], tclk_seed: t.KeyData
) -> t.KeyData:
    keys = [d.key for d in devices if d.key]

    if not keys:
        return tclk_seed

    best_count, best_seed = max(sorted(iter_seed_candidates(keys)))
    tclk_count = count_seed_matches(keys, tclk_seed)
    assert tclk_count <= best_count

    # Prefer the existing TCLK seed if it's as good as the others
    if tclk_count == best_count:
        return tclk_seed

    return best_seed


async def write_devices(
    znp: ZNP,
    devices: typing.Sequence[StoredDevice],
    counter_increment: t.uint32_t = 2500,
    tclk_seed: t.KeyData = None,
) -> t.KeyData:
    hashed_link_key_table = []
    aps_key_data_table = []
    link_key_table = t.APSLinkKeyTable()

    for index, dev in enumerate(devices):
        if dev.key is None:
            continue

        shift = find_key_shift(dev.node_info.ieee, dev.key.key, tclk_seed)

        if shift is not None:
            # Hashed link keys can be written into the TCLK table
            hashed_link_key_table.append(
                t.TCLKDevEntry(
                    txFrmCntr=dev.key.tx_counter + counter_increment,
                    rxFrmCntr=dev.key.rx_counter,
                    extAddr=dev.node_info.ieee,
                    keyAttributes=t.KeyAttributes.VERIFIED_KEY,
                    keyType=t.KeyType.NONE,
                    SeedShift_IcIndex=shift,
                )
            )
        else:
            # Unhashed link keys are written to another table
            aps_key_data_table.append(
                t.APSKeyDataTableEntry(
                    Key=dev.key.key,
                    TxFrameCounter=dev.key.tx_counter + counter_increment,
                    RxFrameCounter=dev.key.rx_counter,
                )
            )

            if znp.version >= 3.30:
                start = 0x0000
            else:
                start = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START

            offset = len(aps_key_data_table) - 1

            # And their position within the above table is stored in this table
            link_key_table.append(
                t.APSLinkKeyTableEntry(
                    AddressManagerIndex=index,
                    LinkKeyNvId=start + offset,
                    AuthenticationState=t.AuthenticationOption.AuthenticatedCBCK,
                )
            )

    addr_mgr_entries = []

    for dev in devices:
        entry = t.AddrMgrEntry(
            type=t.AddrMgrUserType.Default,
            nwkAddr=dev.node_info.nwk,
            extAddr=dev.node_info.ieee,
        )

        if dev.key is not None:
            entry.type |= t.AddrMgrUserType.Security

        if dev.is_child:
            entry.type |= t.AddrMgrUserType.Assoc

        addr_mgr_entries.append(entry)

    await write_addr_manager_entries(znp, addr_mgr_entries)

    # Z-Stack Home 1.2 does not store keys
    if znp.version < 3.0:
        return

    # Make sure the new table is the same size as the old table. Because this type is
    # prefixed by the number of entries, the trailing table bytes are not kept track of
    # but still necessary, as the table has a static maximum capacity.
    old_link_key_table = await znp.nvram.osal_read(
        OsalNvIds.APS_LINK_KEY_TABLE, item_type=t.Bytes
    )

    unpadded_link_key_table = znp.nvram.serialize(link_key_table)
    new_link_key_table_value = unpadded_link_key_table.ljust(
        len(old_link_key_table), b"\x00"
    )

    if len(new_link_key_table_value) > len(old_link_key_table):
        raise RuntimeError("New link key table is larger than the current one")

    await znp.nvram.osal_write(OsalNvIds.APS_LINK_KEY_TABLE, new_link_key_table_value)

    tclk_fill_value = t.TCLKDevEntry(
        txFrmCntr=0,
        rxFrmCntr=0,
        extAddr=t.EUI64.convert("00:00:00:00:00:00:00:00"),
        keyAttributes=t.KeyAttributes.DEFAULT_KEY,
        keyType=t.KeyType.NONE,
        SeedShift_IcIndex=0,
    )

    aps_key_data_fill_value = t.APSKeyDataTableEntry(
        Key=t.KeyData.convert("00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"),
        TxFrameCounter=0,
        RxFrameCounter=0,
    )

    if znp.version > 3.0:
        await znp.nvram.write_table(
            item_id=ExNvIds.TCLK_TABLE,
            values=hashed_link_key_table,
            fill_value=tclk_fill_value,
        )

        await znp.nvram.write_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            values=aps_key_data_table,
            fill_value=aps_key_data_fill_value,
        )
    else:
        await znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_TCLK_TABLE_START,
            end_nvid=OsalNvIds.LEGACY_TCLK_TABLE_END,
            values=hashed_link_key_table,
            fill_value=tclk_fill_value,
        )

        await znp.nvram.osal_write_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            values=aps_key_data_table,
            fill_value=aps_key_data_fill_value,
        )
