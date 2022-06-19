import pytest

import zigpy_znp.const as const
import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

from ..conftest import FORMED_DEVICES, FormedZStack3CC2531


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_addrmgr_empty_entries(make_connected_znp, device):
    znp, znp_server = await make_connected_znp(server_cls=device)

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

    num_empty = 0

    for entry in entries:
        if entry.extAddr != t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
            continue

        num_empty += 1

        if znp.version >= 3.30:
            assert entry == const.EMPTY_ADDR_MGR_ENTRY_ZSTACK3
        else:
            assert entry == const.EMPTY_ADDR_MGR_ENTRY_ZSTACK1

    assert num_empty > 0


@pytest.mark.parametrize("device", [FormedZStack3CC2531])
async def test_addrmgr_rewrite_fix(device, make_connected_znp):
    # Keep track of reads
    addrmgr_reads = []

    correct_entry = t.AddrMgrEntry(
        type=t.AddrMgrUserType.Default,
        nwkAddr=0xFFFF,
        extAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
    )

    bad_entry = t.AddrMgrEntry(
        type=t.AddrMgrUserType(0xFF),
        nwkAddr=0xFFFF,
        extAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
    )

    znp, znp_server = await make_connected_znp(server_cls=device)
    znp_server.callback_for_response(
        c.SYS.OSALNVReadExt.Req(Id=OsalNvIds.ADDRMGR, Offset=0), addrmgr_reads.append
    )

    nvram = znp_server._nvram[ExNvIds.LEGACY]
    old_addrmgr, _ = t.AddressManagerTable.deserialize(nvram[OsalNvIds.ADDRMGR])

    # Ensure the table looks the way we expect
    assert old_addrmgr.count(correct_entry) == 58
    assert old_addrmgr.count(bad_entry) == 0

    assert nvram[OsalNvIds.ADDRMGR] == b"".join([e.serialize() for e in old_addrmgr])

    # Purposefully corrupt the empty entries
    nvram[OsalNvIds.ADDRMGR] = b"".join(
        [(bad_entry if e == correct_entry else e).serialize() for e in old_addrmgr]
    )
    assert old_addrmgr != nvram[OsalNvIds.ADDRMGR]

    assert len(addrmgr_reads) == 0
    await znp.migrate_nvram()
    assert len(addrmgr_reads) == 2

    # Bad entries have been fixed
    new_addrmgr, _ = t.AddressManagerTable.deserialize(nvram[OsalNvIds.ADDRMGR])
    assert new_addrmgr == old_addrmgr

    # Migration has been created
    assert t.uint8_t.deserialize(nvram[OsalNvIds.ZIGPY_ZNP_MIGRATION_ID])[0] >= 1

    # Will not be read again
    assert len(addrmgr_reads) == 2
    await znp.migrate_nvram()
    assert len(addrmgr_reads) == 2

    # Will be migrated again if the migration NVID is deleted
    del nvram[OsalNvIds.ZIGPY_ZNP_MIGRATION_ID]

    old_addrmgr2 = nvram[OsalNvIds.ADDRMGR]

    assert len(addrmgr_reads) == 2
    await znp.migrate_nvram()
    assert len(addrmgr_reads) == 3

    # But nothing will change
    assert nvram[OsalNvIds.ADDRMGR] == old_addrmgr2
