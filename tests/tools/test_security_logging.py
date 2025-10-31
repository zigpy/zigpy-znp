"""Test coverage for security.py logging statements."""
import logging


import zigpy_znp.types as t
from zigpy_znp.znp import security
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

from ..conftest import BaseZStack3CC2531


async def test_read_devices_skips_unknown_link_keys(make_connected_znp, caplog):
    """Test that read_devices logs debug messages for link keys without matching devices.
    
    This test covers the debug logging statements in read_devices():
    - "Skipping hashed link key ... for unknown device"
    - "Skipping unhashed link key ... for unknown device"
    
    These occur when link keys exist in NVRAM but don't have corresponding
    entries in the address manager table.
    """
    znp, znp_server = await make_connected_znp(BaseZStack3CC2531)
    
    # Initialize LEGACY section if not exists
    if ExNvIds.LEGACY not in znp_server._nvram:
        znp_server._nvram[ExNvIds.LEGACY] = {}
    
    # Set up IEEEs for test
    known_ieee = t.EUI64.convert("11:22:33:44:55:66:77:88")
    unknown_hashed_ieee = t.EUI64.convert("aa:bb:cc:dd:ee:ff:00:11")
    
    # Set up address manager with only the known device - must be serialized
    addr_mgr_table = t.AddressManagerTable([
        t.AddrMgrEntry(
            type=t.AddrMgrUserType.Security,
            nwkAddr=t.NWK(0x1234),
            extAddr=known_ieee,
        ),
        # Fill with empty entries
        *[t.AddrMgrEntry(
            type=t.AddrMgrUserType.Default,
            nwkAddr=t.NWK(0xFFFF),
            extAddr=t.EUI64.convert("00:00:00:00:00:00:00:00"),
        ) for _ in range(15)],
    ])
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.ADDRMGR] = addr_mgr_table.serialize()
    
    # Add a hashed link key for an unknown device (not in address manager)
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.LEGACY_TCLK_TABLE_START] = (
        t.TCLKDevEntry(
            extAddr=unknown_hashed_ieee,
            txFrmCntr=100,
            rxFrmCntr=200,
            keyAttributes=t.KeyAttributes.VERIFIED_KEY,
            keyType=t.KeyType.NONE,
            SeedShift_IcIndex=0,
        ).serialize()
    )
    
    # Add another hashed link key for a second unknown device to verify logging
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.LEGACY_TCLK_TABLE_START + 1] = (
        t.TCLKDevEntry(
            extAddr=t.EUI64.convert("bb:bb:bb:bb:bb:bb:bb:bb"),
            txFrmCntr=150,
            rxFrmCntr=250,
            keyAttributes=t.KeyAttributes.VERIFIED_KEY,
            keyType=t.KeyType.NONE,
            SeedShift_IcIndex=1,
        ).serialize()
    )
    
    # For ZStack 3.0, also need APS link key table (even if empty)
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.APS_LINK_KEY_TABLE] = b"\x00" * 16

    tclk_seed = t.KeyData(b"\xAA" * 16)
    
    # Capture debug logs
    caplog.set_level(logging.DEBUG, logger="zigpy_znp.znp.security")
    
    # Call read_devices - should log debug messages for unknown devices
    devices = await security.read_devices(znp, tclk_seed=tclk_seed)
    
    # Verify that debug messages were logged for hashed keys
    assert "Skipping hashed link key" in caplog.text
    assert str(unknown_hashed_ieee) in caplog.text
    
    # Verify messages are at DEBUG level
    debug_records = [r for r in caplog.records if "Skipping" in r.message and "link key" in r.message]
    assert len(debug_records) >= 2  # At least 2 unknown devices
    assert all(r.levelname == "DEBUG" for r in debug_records)
    
    # Verify that only the known device is returned (no orphan keys)
    assert len(devices) == 1
    assert devices[0].node_info.ieee == known_ieee
    
    # For ZStack 3.0, also need APS link key table (even if empty)
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.APS_LINK_KEY_TABLE] = b"\x00" * 16
