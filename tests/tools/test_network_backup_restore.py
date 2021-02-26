import json

import pytest

import zigpy_znp.types as t
from zigpy_znp.tools.energy_scan import channels_from_channel_mask
from zigpy_znp.tools.network_backup import main as network_backup

from ..conftest import FORMED_DEVICES


@pytest.mark.asyncio
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_network_backup(device, make_znp_server, tmp_path):
    znp_server = make_znp_server(server_cls=device)

    backup_file = tmp_path / "backup.json"
    await network_backup([znp_server._port_path, "-o", str(backup_file)])

    backup = json.loads(backup_file.read_text())

    # XXX: actually test that the values match up with what the device NVRAM contains
    assert backup["metadata"]["version"] == 1
    assert backup["metadata"]["format"] == "zigpy/open-coordinator-backup"
    assert backup["metadata"]["source"].startswith("zigpy-znp@")

    assert len(bytes.fromhex(backup["coordinator_ieee"])) == 8
    assert len(bytes.fromhex(backup["pan_id"])) == 2
    assert len(bytes.fromhex(backup["extended_pan_id"])) == 8
    assert 0 <= backup["nwk_update_id"] <= 0xFF
    assert 0 <= backup["security_level"] <= 7
    assert backup["channel"] in list(range(11, 26 + 1))

    channel_mask = t.Channels.from_channel_list(backup["channel_mask"])
    assert backup["channel"] in channels_from_channel_mask(channel_mask)

    assert len(bytes.fromhex(backup["network_key"]["key"])) == 16
    assert 0x00 <= backup["network_key"]["sequence_number"] <= 0xFF
    assert 0x00000000 <= backup["network_key"]["frame_counter"] <= 0xFFFFFFFF

    assert isinstance(backup["devices"], list)
