from __future__ import annotations

import typing
import logging
import dataclasses

import zigpy_znp.types as t
from zigpy_znp.api import ZNP
from zigpy_znp.exceptions import SecurityError
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

KeyInfo = typing.Tuple[t.EUI64, t.uint32_t, t.uint32_t, t.KeyData]

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class StoredDevice:
    ieee: t.EUI64
    nwk: t.NWK

    hashed_link_key_shift: t.uint8_t = None
    aps_link_key: t.KeyData = None

    tx_counter: t.uint32_t = None
    rx_counter: t.uint32_t = None

    def replace(self, **kwargs) -> StoredDevice:
        return dataclasses.replace(self, **kwargs)


def rotate(lst: typing.Sequence, n: int) -> typing.Sequence:
    return lst[n:] + lst[:n]


def compute_key(ieee: t.EUI64, tclk_seed: bytes, shift: int) -> t.KeyData:
    rotated_tclk_seed = rotate(tclk_seed, n=shift)
    return t.KeyData([a ^ b for a, b in zip(rotated_tclk_seed, 2 * ieee.serialize())])


def compute_tclk_seed(ieee: t.EUI64, key: t.KeyData, shift: int) -> bytes:
    rotated_tclk_seed = bytes(a ^ b for a, b in zip(key, 2 * ieee.serialize()))
    return rotate(rotated_tclk_seed, n=-shift)


def find_key_shift(ieee: t.EUI64, key: t.KeyData, tclk_seed: bytes) -> int | None:
    for shift in range(0x00, 0x0F + 1):
        if tclk_seed == compute_tclk_seed(ieee, key, shift):
            return shift

    return None


def count_seed_matches(
    ieees_and_keys: typing.Sequence[tuple[t.EUI64, t.KeyData]], tclk_seed: bytes
) -> int:
    return sum(find_key_shift(i, k, tclk_seed) is not None for i, k in ieees_and_keys)


def iter_seed_candidates(
    ieees_and_keys: typing.Sequence[tuple[t.EUI64, t.KeyData]]
) -> typing.Iterable[tuple[int, t.KeyData]]:
    for ieee, key in ieees_and_keys:
        # Derive a seed from each candidate. All rotations of a seed are equivalent.
        tclk_seed = compute_tclk_seed(ieee, key, 0)

        # And see how many other keys share this same seed
        count = count_seed_matches(ieees_and_keys, tclk_seed)

        yield count, tclk_seed


async def read_tc_frame_counter(znp: ZNP) -> t.uint32_t:
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
        if entry.ExtendedPanID == znp.network_info.extended_pan_id:
            # Always prefer the entry for our current network
            return entry.FrameCounter
        elif entry.ExtendedPanID == t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
            # But keep track of the global entry if it already exists
            global_entry = entry

    if global_entry is None:
        raise ValueError("No security material entry was found for this network")

    return global_entry.FrameCounter


async def write_tc_frame_counter(znp: ZNP, counter: t.uint32_t) -> None:
    if znp.version == 1.2:
        key_info = await znp.nvram.osal_read(
            OsalNvIds.NWKKEY, item_type=t.NwkActiveKeyItems
        )
        key_info.FrameCounter = counter

        await znp.nvram.osal_write(OsalNvIds.NWKKEY, key_info)

        return

    entry = t.NwkSecMaterialDesc(
        FrameCounter=counter,
        ExtendedPanID=znp.network_info.extended_pan_id,
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


async def read_addr_mgr_entries(znp: ZNP) -> typing.Sequence[t.AddrMgrEntry]:
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


async def read_hashed_link_keys(znp: ZNP, tclk_seed: bytes) -> typing.Iterable[KeyInfo]:
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

        yield (
            entry.extAddr,
            entry.txFrmCntr,
            entry.rxFrmCntr,
            compute_key(entry.extAddr, tclk_seed, entry.SeedShift_IcIndex),
        )


async def read_unhashed_link_keys(
    znp: ZNP, addr_mgr_entries: typing.Sequence[t.AddrMgrEntry]
) -> typing.Iterable[KeyInfo]:
    if znp.version == 3.30:
        link_key_offset_base = 0x0000
        table = znp.nvram.read_table(
            item_id=ExNvIds.APS_KEY_DATA_TABLE,
            item_type=t.APSKeyDataTableEntry,
        )
    else:
        link_key_offset_base = OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START
        table = znp.nvram.osal_read_table(
            start_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_START,
            end_nvid=OsalNvIds.LEGACY_APS_LINK_KEY_DATA_END,
            item_type=t.APSKeyDataTableEntry,
        )

    try:
        aps_key_data_table = [entry async for entry in table]
    except SecurityError:
        # CC2531 with Z-Stack Home 1.2 just doesn't let you read this data out
        return

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

        yield (
            addr_mgr_entry.extAddr,
            key_table_entry.TxFrameCounter,
            key_table_entry.RxFrameCounter,
            key_table_entry.Key,
        )


async def read_devices(znp: ZNP) -> typing.Sequence[StoredDevice]:
    tclk_seed = None

    if znp.version > 1.2:
        tclk_seed = await znp.nvram.osal_read(OsalNvIds.TCLK_SEED, item_type=t.KeyData)

    addr_mgr = await read_addr_mgr_entries(znp)
    devices = {}

    for entry in addr_mgr:
        if entry.extAddr in (
            t.EUI64.convert("00:00:00:00:00:00:00:00"),
            t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
        ):
            continue
        elif entry.type == t.AddrMgrUserType.Default:
            continue
        elif entry.type in (
            t.AddrMgrUserType.Assoc,
            t.AddrMgrUserType.Assoc | t.AddrMgrUserType.Security,
            t.AddrMgrUserType.Security,
        ):
            if not 0x0000 <= entry.nwkAddr <= 0xFFF7:
                LOGGER.warning("Ignoring invalid address manager entry: %s", entry)
                continue

            devices[entry.extAddr] = StoredDevice(
                ieee=entry.extAddr,
                nwk=entry.nwkAddr,
            )
        else:
            raise ValueError(f"Unexpected entry type: {entry.type}")

    async for ieee, tx_ctr, rx_ctr, key in read_hashed_link_keys(znp, tclk_seed):
        if ieee not in devices:
            LOGGER.warning(
                "Skipping hashed link key %s (tx: %s, rx: %s) for unknown device %s",
                ":".join(f"{b:02x}" for b in key),
                tx_ctr,
                rx_ctr,
                ieee,
            )
            continue

        devices[ieee] = devices[ieee].replace(
            tx_counter=tx_ctr,
            rx_counter=rx_ctr,
            aps_link_key=key,
            hashed_link_key_shift=find_key_shift(ieee, key, tclk_seed),
        )

    async for ieee, tx_ctr, rx_ctr, key in read_unhashed_link_keys(znp, addr_mgr):
        if ieee not in devices:
            LOGGER.warning(
                "Skipping unhashed link key %s (tx: %s, rx: %s) for unknown device %s",
                ":".join(f"{b:02x}" for b in key),
                tx_ctr,
                rx_ctr,
                ieee,
            )
            continue

        devices[ieee] = devices[ieee].replace(
            tx_counter=tx_ctr,
            rx_counter=rx_ctr,
            aps_link_key=key,
        )

    return list(devices.values())


async def write_addr_manager_entries(
    znp: ZNP, devices: typing.Sequence[StoredDevice]
) -> None:
    entries = [
        t.AddrMgrEntry(
            type=(
                t.AddrMgrUserType.Security
                if d.aps_link_key
                else t.AddrMgrUserType.Assoc
            ),
            nwkAddr=d.nwk,
            extAddr=d.ieee,
        )
        for d in devices
    ]

    if znp.version >= 3.30:
        await znp.nvram.write_table(
            item_id=ExNvIds.ADDRMGR,
            values=entries,
            fill_value=t.EMPTY_ADDR_MGR_ENTRY,
        )
        return

    # On older devices this "table" is a single array in NVRAM whose size is dependent
    # on compile-time constants
    old_entries = await znp.nvram.osal_read(
        OsalNvIds.ADDRMGR, item_type=t.AddressManagerTable
    )
    new_entries = len(old_entries) * [t.EMPTY_ADDR_MGR_ENTRY]

    # Purposefully throw an `IndexError` if we are trying to write too many entries
    for index, entry in enumerate(entries):
        new_entries[index] = entry

    await znp.nvram.osal_write(OsalNvIds.ADDRMGR, t.AddressManagerTable(new_entries))


async def write_devices(
    znp: ZNP,
    devices: typing.Sequence[StoredDevice],
    counter_increment: t.uint32_t = 2500,
    tclk_seed: bytes = None,
) -> None:
    ieees_and_keys = [(d.ieee, d.aps_link_key) for d in devices if d.aps_link_key]

    # Find the tclk_seed that maximizes the number of keys that can be derived from it
    if ieees_and_keys:
        best_count, best_seed = max(iter_seed_candidates(ieees_and_keys))

        # Check to see if the provided tclk_seed is also optimal
        if tclk_seed is not None:
            tclk_count = count_seed_matches(ieees_and_keys, tclk_seed)
            assert tclk_count <= best_count

            if tclk_count < best_count:
                LOGGER.warning(
                    "Provided TCLK seed %s only generates %d keys, but computed seed"
                    " %s generates %d keys. Picking computed seed.",
                    tclk_seed,
                    tclk_count,
                    best_seed,
                    best_count,
                )
            else:
                best_seed = tclk_seed

        tclk_seed = best_seed

    hashed_link_key_table = []
    aps_key_data_table = []
    link_key_table = t.APSLinkKeyTable()

    for index, device in enumerate(devices):
        if not device.aps_link_key:
            continue

        shift = find_key_shift(device.ieee, device.aps_link_key, tclk_seed)

        if shift is not None:
            # Hashed link keys can be written into the TCLK table
            hashed_link_key_table.append(
                t.TCLKDevEntry(
                    txFrmCntr=device.tx_counter + counter_increment,
                    rxFrmCntr=device.rx_counter,
                    extAddr=device.ieee,
                    keyAttributes=t.KeyAttributes.VERIFIED_KEY,
                    keyType=t.KeyType.NONE,
                    SeedShift_IcIndex=shift,
                )
            )
        else:
            # Unhashed link keys are written to another table
            aps_key_data_table.append(
                t.APSKeyDataTableEntry(
                    Key=device.aps_link_key,
                    TxFrameCounter=device.tx_counter + counter_increment,
                    RxFrameCounter=device.rx_counter,
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

    # Postpone writes until all of the table entries have been created
    await write_addr_manager_entries(znp, devices)
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
        Key=t.KeyData([0x00] * 16),
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
