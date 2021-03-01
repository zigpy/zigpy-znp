import json

import pytest

import zigpy_znp.types as t
import zigpy_znp.config as conf
from zigpy_znp.api import ZNP
from zigpy_znp.znp.utils import NetworkInfo
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.znp.security import StoredDevice
from zigpy_znp.tools.energy_scan import channels_from_channel_mask
from zigpy_znp.zigbee.application import ControllerApplication
from zigpy_znp.tools.network_backup import main as network_backup
from zigpy_znp.tools.network_restore import main as network_restore

from ..conftest import (
    ALL_DEVICES,
    EMPTY_DEVICES,
    FORMED_DEVICES,
    CoroutineMock,
    BaseZStack1CC2531,
)

pytestmark = [pytest.mark.asyncio]


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_network_backup_formed(device, make_znp_server, tmp_path):
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


@pytest.mark.parametrize("device", EMPTY_DEVICES)
async def test_network_backup_empty(device, make_znp_server):
    znp_server = make_znp_server(server_cls=device)

    with pytest.raises(RuntimeError):
        await network_backup([znp_server._port_path, "-o", "-"])


TEST_BACKUP = {
    "metadata": {
        "format": "zigpy/open-coordinator-backup",
        "internal": {
            "creation_time": "2021-02-16T22:29:28+00:00",
            "zstack": {"version": 3.3},
        },
        "source": "zigpy-znp@0.3.0",
        "version": 1,
    },
    "stack_specific": {"zstack": {"tclk_seed": "c04884427c8a1ed7bb8412815ccce7aa"}},
    "channel": 25,
    "channel_mask": [15, 20, 25],
    "pan_id": "feed",
    "extended_pan_id": "abdefabcdefabcde",
    "coordinator_ieee": "0123456780123456",
    "nwk_update_id": 2,
    "security_level": 5,
    "network_key": {
        "frame_counter": 66781,
        "key": "37668fd64e35e03342e5ef9f35ccf4ab",
        "sequence_number": 1,
    },
    "devices": [
        {"ieee_address": "000b57fffe36b9a0", "nwk_address": "f319"},  # No key
        {
            "ieee_address": "000b57fffe38b212",
            "link_key": {
                "key": "d2fabcbc83dd15d7a9362a7fa39becaa",  # Derived from seed
                "rx_counter": 123,
                "tx_counter": 456,
            },
            "nwk_address": "9672",
        },
        {
            "ieee_address": "aabbccddeeff0011",
            "link_key": {
                "key": "01234567801234567801234567801234",  # Not derived from seed
                "rx_counter": 112233,
                "tx_counter": 445566,
            },
            "nwk_address": "abcd",
        },
    ],
}


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_network_restore(device, make_znp_server, tmp_path, mocker):
    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(TEST_BACKUP))

    znp_server = make_znp_server(server_cls=device)

    async def mock_startup(self, *, force_form):
        assert force_form

        config = self.config[conf.CONF_NWK]

        assert config[conf.CONF_NWK_KEY] == t.KeyData(
            bytes.fromhex("37668fd64e35e03342e5ef9f35ccf4ab")
        )
        assert config[conf.CONF_NWK_PAN_ID] == 0xFEED
        assert config[conf.CONF_NWK_CHANNEL] == 25
        assert config[conf.CONF_NWK_EXTENDED_PAN_ID] == t.EUI64.convert(
            "ab:de:fa:bc:de:fa:bc:de"
        )

        znp = ZNP(self.config)
        await znp.connect()

        if OsalNvIds.APS_LINK_KEY_TABLE not in znp_server._nvram[ExNvIds.LEGACY]:
            znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.APS_LINK_KEY_TABLE] = (
                b"\x00" * 1000
            )

        if OsalNvIds.NIB not in znp_server._nvram[ExNvIds.LEGACY]:
            znp_server._nvram[ExNvIds.LEGACY][
                OsalNvIds.NIB
            ] = znp_server.nvram_serialize(znp_server._default_nib())

        self._znp = znp
        self._znp.set_application(self)

        self._bind_callbacks()

    startup_mock = mocker.patch.object(
        ControllerApplication, "startup", side_effect=mock_startup, autospec=True
    )

    load_nwk_info_mock = mocker.patch(
        "zigpy_znp.api.load_network_info",
        new=CoroutineMock(
            return_value=NetworkInfo(
                extended_pan_id=t.EUI64.convert("ab:de:fa:bc:de:fa:bc:de"),
                ieee=None,
                nwk=None,
                channel=None,
                channels=None,
                pan_id=None,
                nwk_update_id=None,
                security_level=None,
                network_key=None,
                network_key_seq=None,
            )
        ),
    )

    write_tc_counter_mock = mocker.patch(
        "zigpy_znp.tools.network_restore.write_tc_frame_counter", new=CoroutineMock()
    )
    write_devices_mock = mocker.patch(
        "zigpy_znp.tools.network_restore.write_devices", new=CoroutineMock()
    )

    # Perform the "restore"
    await network_restore([znp_server._port_path, "-i", str(backup_file), "-c", "2500"])

    # The NIB should contain correct values
    nib = znp_server.nvram_deserialize(
        znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.NIB], t.NIB
    )
    assert nib.channelList == t.Channels.from_channel_list([15, 20, 25])
    assert nib.nwkUpdateId == 2
    assert nib.SecurityLevel == 5

    # And validate that the low-level functions were called appropriately
    assert startup_mock.call_count == 1
    assert startup_mock.mock_calls[0][2]["force_form"] is True

    assert load_nwk_info_mock.call_count == 1

    assert write_tc_counter_mock.call_count == 1
    assert write_tc_counter_mock.mock_calls[0][1][1] == 66781 + 2500

    assert write_devices_mock.call_count == 1
    write_devices_call = write_devices_mock.mock_calls[0]

    assert write_devices_call[2]["counter_increment"] == 2500

    if issubclass(device, BaseZStack1CC2531):
        assert write_devices_call[2]["seed"] is None
    else:
        assert write_devices_call[2]["seed"] == bytes.fromhex(
            "c04884427c8a1ed7bb8412815ccce7aa"
        )

    assert sorted(write_devices_call[1][1], key=lambda d: d.nwk) == [
        StoredDevice(
            ieee=t.EUI64.convert("00:0b:57:ff:fe:38:b2:12"),
            nwk=0x9672,
            aps_link_key=t.KeyData.deserialize(
                bytes.fromhex("d2fabcbc83dd15d7a9362a7fa39becaa")
            )[0],
            rx_counter=123,
            tx_counter=456,
        ),
        StoredDevice(
            ieee=t.EUI64.convert("aa:bb:cc:dd:ee:ff:00:11"),
            nwk=0xABCD,
            aps_link_key=t.KeyData.deserialize(
                bytes.fromhex("01234567801234567801234567801234")
            )[0],
            rx_counter=112233,
            tx_counter=445566,
        ),
        StoredDevice(
            ieee=t.EUI64.convert("00:0b:57:ff:fe:36:b9:a0"),
            nwk=0xF319,
        ),
    ]
