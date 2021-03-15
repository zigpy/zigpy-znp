import json

import pytest
from jsonschema import ValidationError

import zigpy_znp.types as t
import zigpy_znp.config as conf
from zigpy_znp.api import ZNP
from zigpy_znp.znp import security
from zigpy_znp.znp.utils import NetworkInfo
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.tools.common import validate_backup_json
from zigpy_znp.zigbee.application import ControllerApplication
from zigpy_znp.tools.network_backup import main as network_backup
from zigpy_znp.tools.network_restore import main as network_restore

from ..conftest import (
    ALL_DEVICES,
    EMPTY_DEVICES,
    FORMED_DEVICES,
    CoroutineMock,
    BaseZStack1CC2531,
    BaseZStack3CC2531,
    BaseLaunchpadCC26X2R1,
)
from ..application.test_startup import DEV_NETWORK_SETTINGS

BARE_NETWORK_INFO = NetworkInfo(
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


@pytest.fixture
def backup_json():
    return {
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


def test_schema_validation(backup_json):
    validate_backup_json(backup_json)


def test_schema_validation_counters(backup_json):
    backup_json["devices"][1]["link_key"]["tx_counter"] = 0xFFFFFFFF
    validate_backup_json(backup_json)
    backup_json["devices"][1]["link_key"]["tx_counter"] = 0xFFFFFFFF + 1

    with pytest.raises(ValidationError):
        validate_backup_json(backup_json)


def test_schema_validation_device_key_info(backup_json):
    validate_backup_json(backup_json)
    backup_json["devices"][1]["link_key"]["key"] = None

    with pytest.raises(ValidationError):
        validate_backup_json(backup_json)


@pytest.mark.parametrize("device", EMPTY_DEVICES)
@pytest.mark.asyncio
async def test_network_backup_empty(device, make_znp_server):
    znp_server = make_znp_server(server_cls=device)

    with pytest.raises(RuntimeError):
        await network_backup([znp_server._port_path, "-o", "-"])


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.asyncio
async def test_network_backup_formed(device, make_znp_server, tmp_path):
    znp_server = make_znp_server(server_cls=device)

    # We verified these settings with Wireshark
    _, channel, channels, pan_id, ext_pan_id, network_key = DEV_NETWORK_SETTINGS[device]

    backup_file = tmp_path / "backup.json"
    await network_backup([znp_server._port_path, "-o", str(backup_file)])

    backup = json.loads(backup_file.read_text())

    # XXX: actually test that the values match up with what the device NVRAM contains
    assert backup["metadata"]["version"] == 1
    assert backup["metadata"]["format"] == "zigpy/open-coordinator-backup"
    assert backup["metadata"]["source"].startswith("zigpy-znp@")

    assert len(bytes.fromhex(backup["coordinator_ieee"])) == 8
    assert t.NWK.deserialize(bytes.fromhex(backup["pan_id"])[::-1])[0] == pan_id
    assert (
        t.EUI64.deserialize(bytes.fromhex(backup["extended_pan_id"])[::-1])[0]
        == ext_pan_id
    )
    assert backup["nwk_update_id"] == 0
    assert backup["security_level"] == 5
    assert backup["channel"] == channel
    assert t.Channels.from_channel_list(backup["channel_mask"]) == channels

    assert t.KeyData(bytes.fromhex(backup["network_key"]["key"])) == network_key
    assert backup["network_key"]["sequence_number"] == 0
    assert 0x00000000 <= backup["network_key"]["frame_counter"] <= 0xFFFFFFFF

    assert isinstance(backup["devices"], list)
    assert len(backup["devices"]) > 1


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.asyncio
async def test_network_restore_full(
    device, make_znp_server, backup_json, tmp_path, mocker
):
    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup_json))

    znp_server = make_znp_server(server_cls=device)

    # Perform the "restore"
    await network_restore([znp_server._port_path, "-i", str(backup_file), "-c", "2500"])


@pytest.mark.parametrize("device", ALL_DEVICES)
@pytest.mark.asyncio
async def test_network_restore(device, make_znp_server, backup_json, tmp_path, mocker):
    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup_json))

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
        new=CoroutineMock(return_value=BARE_NETWORK_INFO),
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
        assert write_devices_call[2]["tclk_seed"] is None
    else:
        assert write_devices_call[2]["tclk_seed"] == bytes.fromhex(
            "c04884427c8a1ed7bb8412815ccce7aa"
        )

    assert sorted(write_devices_call[1][1], key=lambda d: d.nwk) == [
        security.StoredDevice(
            ieee=t.EUI64.convert("00:0b:57:ff:fe:38:b2:12"),
            nwk=0x9672,
            aps_link_key=t.KeyData.deserialize(
                bytes.fromhex("d2fabcbc83dd15d7a9362a7fa39becaa")
            )[0],
            rx_counter=123,
            tx_counter=456,
        ),
        security.StoredDevice(
            ieee=t.EUI64.convert("aa:bb:cc:dd:ee:ff:00:11"),
            nwk=0xABCD,
            aps_link_key=t.KeyData.deserialize(
                bytes.fromhex("01234567801234567801234567801234")
            )[0],
            rx_counter=112233,
            tx_counter=445566,
        ),
        security.StoredDevice(
            ieee=t.EUI64.convert("00:0b:57:ff:fe:36:b9:a0"),
            nwk=0xF319,
        ),
    ]


@pytest.mark.asyncio
async def test_tc_frame_counter_zstack1(make_connected_znp):
    znp, znp_server = await make_connected_znp(BaseZStack1CC2531)
    znp_server._nvram[ExNvIds.LEGACY] = {
        OsalNvIds.NWKKEY: b"\x01" + b"\xAB" * 16 + b"\x78\x56\x34\x12"
    }

    assert (await security.read_tc_frame_counter(znp)) == 0x12345678

    await security.write_tc_frame_counter(znp, 0xAABBCCDD)
    assert (await security.read_tc_frame_counter(znp)) == 0xAABBCCDD


@pytest.mark.asyncio
async def test_tc_frame_counter_zstack30(make_connected_znp):
    znp, znp_server = await make_connected_znp(BaseZStack3CC2531)
    znp.network_info = BARE_NETWORK_INFO
    znp_server._nvram[ExNvIds.LEGACY] = {
        # This value is ignored
        OsalNvIds.NWKKEY: b"\x01" + b"\xAB" * 16 + b"\x78\x56\x34\x12",
        # Wrong EPID, ignored
        OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START: bytes.fromhex(
            "0f000000058eea0f004b1200"
        ),
        # Exact EPID match, used
        (OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START + 1): bytes.fromhex("01000000")
        + BARE_NETWORK_INFO.extended_pan_id.serialize(),
        # Generic EPID but ignored since EPID matches
        (OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START + 2): bytes.fromhex("02000000")
        + b"\xFF" * 8,
    }

    assert (await security.read_tc_frame_counter(znp)) == 0x00000001

    # If we change the EPID, the generic entry will be used
    old_nwk_info = znp.network_info
    znp.network_info = znp.network_info.replace(
        extended_pan_id=t.EUI64.convert("11:22:33:44:55:66:77:88")
    )
    assert (await security.read_tc_frame_counter(znp)) == 0x00000002

    # Changing the frame counter will always change the global entry in this case
    await security.write_tc_frame_counter(znp, 0xAABBCCDD)
    assert (await security.read_tc_frame_counter(znp)) == 0xAABBCCDD
    assert znp_server._nvram[ExNvIds.LEGACY][
        OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START + 2
    ].startswith(t.uint32_t(0xAABBCCDD).serialize())

    # Global entry is ignored if the EPID matches
    znp.network_info = old_nwk_info
    assert (await security.read_tc_frame_counter(znp)) == 0x00000001
    await security.write_tc_frame_counter(znp, 0xABCDABCD)
    assert znp_server._nvram[ExNvIds.LEGACY][
        OsalNvIds.LEGACY_NWK_SEC_MATERIAL_TABLE_START + 1
    ].startswith(t.uint32_t(0xABCDABCD).serialize())


@pytest.mark.asyncio
async def test_tc_frame_counter_zstack33(make_connected_znp):
    znp, znp_server = await make_connected_znp(BaseLaunchpadCC26X2R1)
    znp.network_info = BARE_NETWORK_INFO
    znp_server._nvram = {
        ExNvIds.LEGACY: {
            # This value is ignored
            OsalNvIds.NWKKEY: bytes.fromhex(
                "00c927e9ce1544c9aa42340e4d5dc4c257e4010001000000"
            )
        },
        ExNvIds.NWK_SEC_MATERIAL_TABLE: {
            # Wrong EPID, ignored
            0x0000: bytes.fromhex("0100000037a7479777d7a224"),
            # Right EPID, used
            0x0001: bytes.fromhex("02000000")
            + BARE_NETWORK_INFO.extended_pan_id.serialize(),
        },
    }

    assert (await security.read_tc_frame_counter(znp)) == 0x00000002

    # If we change the EPID, the generic entry will be used. It doesn't exist.
    old_nwk_info = znp.network_info
    znp.network_info = znp.network_info.replace(
        extended_pan_id=t.EUI64.convert("11:22:33:44:55:66:77:88")
    )

    with pytest.raises(ValueError):
        await security.read_tc_frame_counter(znp)

    # Writes similarly will fail
    old_nvram_state = repr(znp_server._nvram)

    with pytest.raises(ValueError):
        await security.write_tc_frame_counter(znp, 0x98765432)

    # And the NVRAM will be untouched
    assert repr(znp_server._nvram) == old_nvram_state

    # The correct entry will be updated
    znp.network_info = old_nwk_info
    assert (await security.read_tc_frame_counter(znp)) == 0x00000002
    await security.write_tc_frame_counter(znp, 0xABCDABCD)
    assert znp_server._nvram[ExNvIds.NWK_SEC_MATERIAL_TABLE][0x0001].startswith(
        t.uint32_t(0xABCDABCD).serialize()
    )


def ieee_and_key(text):
    ieee, key = text.replace(":", "").split("|")

    return t.EUI64(bytes.fromhex(ieee)[::-1]), t.KeyData(bytes.fromhex(key))


def test_seed_candidate_finding_simple():
    ieee1, key1 = ieee_and_key("0011223344556677|000102030405060708090a0b0c0d0e0f")
    ieee2, key2 = ieee_and_key("1111223344556677|101112131415161718191a1b1c1d1e1f")

    (c1, s1), (c2, s2) = security.iter_seed_candidates([(ieee1, key1), (ieee2, key2)])

    assert c1 == c2 == 1

    sh1 = security.find_key_shift(ieee1, key1, s1)
    sh2 = security.find_key_shift(ieee2, key2, s2)
    assert sh1 is not None and sh2 is not None

    assert security.compute_key(ieee1, s1, sh1) == key1
    assert security.compute_key(ieee2, s2, sh2) == key2


def min_rotate(lst):
    return min(security.rotate(lst, i) for i in range(len(lst)))


def test_seed_candidate_finding_complex():
    ieees_and_keys = [
        # Real network
        ieee_and_key("000b57fffe36b9a0|0a797e7abd2b811e7702b2ec7e0bc7e7"),
        ieee_and_key("000b57fffe38b212|d2fabcbc83dd15d7a9362a7fa39becaa"),
        ieee_and_key("000b57fffe877774|360b0de028ec8f12f52b4b1955974384"),
        ieee_and_key("000b57fffe8d4f83|9d98367aedd657cc64e54db67b15778a"),
        ieee_and_key("000b57fffe8e8c44|c09e0fa233b0a1c00c08cc827549dcbb"),
        ieee_and_key("000b57fffe8e92a3|ff5e69543f1f8f42df18902944d31981"),
        ieee_and_key("000b57fffe8e935f|decf4219559743841def04e028ec8f12"),
        ieee_and_key("000b57fffebd5ad1|8d965a543f1f8f42add0a32944d31981"),
        ieee_and_key("000b57fffed53765|19bdcb2944d3198139fb32543f1f8f42"),
        ieee_and_key("000b57fffedd4954|fe89957abd2b811e83f259ec7e0bc7e7"),
        ieee_and_key("000b57fffedd50be|acd1813218fdcb483a12a174e180b084"),
        ieee_and_key("000d6ffffe2ee3cc|b069302944eb1f81902fc9543f278942"),
        ieee_and_key("000d6ffffe3066d5|19819a3eb7eb4f7c5f78e7457b7d8c5c"),
        ieee_and_key("000d6ffffe7a84a9|1200687fa3a3eaaa69ccfebc83e513d7"),
        ieee_and_key("000d6ffffe7bc266|ecdcac457b7d8c5caa25d13eb7eb4f7c"),
        ieee_and_key("000d6ffffe7bfac1|40a6b71955af45848386f1e028d48912"),
        ieee_and_key("000d6ffffea4f10b|ec5b64b67b2d718a15261f7aedee51cc"),
        ieee_and_key("000d6ffffea5b793|19a972457b7d8c5c5f500f3eb7eb4f7c"),
        ieee_and_key("000d6ffffea6117a|6890fa3218c5cd48fe53da74e1b8b684"),
        ieee_and_key("90fd9ffffe2bbbdd|3a11ebb67bdd811ac36c907aed1ea15c"),
        ieee_and_key("90fd9ffffe329a0b|8ac6fe19555fb51449e6b8e028247982"),
        ieee_and_key("ccccccfffeeec02a|ea886abc8346d21b9144fc7fa3002b66"),
        ieee_and_key("d0cf5efffeda9bbb|115b927abd2245ce6c205eec7e020337"),
        ieee_and_key("ec1bbdfffe544f40|8007d0bc8337053bfbcb467fa371fc46"),
        # Bogus entry
        ieee_and_key("0011223344556677|000102030405060708090a0b0c0d0e0f"),
    ]

    candidates = list(security.iter_seed_candidates(ieees_and_keys))
    assert len(candidates) == 24 + 1

    # One seed generated all but one of the keys, so there are 24 equally valid seeds.
    # They are all really rotations of the same seed.
    assert [c for c, s in candidates].count(24) == 24
    assert len({min_rotate(s) for c, s in candidates if c == 24}) == 1

    # And one just for the bogus entry
    assert [c[0] for c in candidates].count(1) == 1
