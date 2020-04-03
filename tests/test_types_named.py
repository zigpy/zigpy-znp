import pytest

from zigpy_znp import types as t


def test_status():
    """Test Status enum."""

    assert t.Status.Success == 0
    assert t.Status.Failure == 1

    extra = b"the rest of the owl\xaa\x55\x00\xff"

    r, rest = t.Status.deserialize(b"\x00" + extra)
    assert rest == extra
    assert r == 0
    assert r == t.Status.Success
    assert r.name == "Success"

    r, rest = t.Status.deserialize(b"\xff" + extra)
    assert rest == extra
    assert r == 0xFF
    assert r.value == 0xFF
    assert r.name.startswith("unknown")


def test_addr_mode_address():
    """Test Addr mode address."""

    data = b"\x03\x00\x01\x02\x03\x04\x05\x06\x07"
    extra = b"The rest of the data\x55\xaa"

    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.IEEE
    assert r.address == t.EUI64(range(8))
    assert r.serialize() == data

    data = b"\x02\xaa\x55\x02\x03\x04\x05\x06\x07"
    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.NWK
    assert r.address == t.NWK(0x55AA)
    assert r.serialize()[:3] == data[:3]
    assert len(r.serialize()) == 9

    with pytest.raises(ValueError):
        # 0x0f is broadcast mode
        data = b"\x0f\xaa\x55\x02\x03\x04\x05\x06\x07"
        t.AddrModeAddress.deserialize(data)

    with pytest.raises(ValueError):
        # 0xab is not a valid mode
        data = b"\xAB\xaa\x55\x02\x03\x04\x05\x06\x07"
        t.AddrModeAddress.deserialize(data)

    data1 = b"\x02\x0E\xAD" + b"\xC0\x8C\x97\x83\xB0\x20\x33"
    data2 = b"\x02\x0E\xAD" + b"\x3F\xB9\x5B\x64\x20\x86\xD6"

    r1, _ = t.AddrModeAddress.deserialize(data1)
    r2, _ = t.AddrModeAddress.deserialize(data2)

    # Bytes at the end for NWK address mode are ignored
    assert r1 == r2

    data1 = b"\x02\x0E\xAD\xC0\x8C\x97\x83\xB0\x20\x33"
    data2 = b"\x02\x0E\xAD\x3F\xB9\x5B\x64\x20\x86\xD6"

    r3, _ = t.AddrModeAddress.deserialize(b"\x03" + data1[1:])
    r4, _ = t.AddrModeAddress.deserialize(b"\x03" + data2[1:])

    # All of the bytes are used for IEEE address mode
    assert r3 != r4


def test_channels():
    """Test Channel enum."""

    assert t.Channels.from_channel_list([]) == t.Channels.NO_CHANNELS
    assert t.Channels.from_channel_list(range(11, 26 + 1)) == t.Channels.ALL_CHANNELS
    assert (
        t.Channels.from_channel_list([11, 21])
        == t.Channels.CHANNEL_11 | t.Channels.CHANNEL_21
    )

    with pytest.raises(ValueError):
        t.Channels.from_channel_list([11, 13, 10])  # 10 is not a valid channel

    with pytest.raises(ValueError):
        t.Channels.from_channel_list([27, 13, 15, 18])  # 27 is not a valid channel


def test_missing_status_enum():
    assert 0xFF not in list(t.Status)
    assert isinstance(t.Status(0xFF), t.Status)
    assert t.Status(0xFF).value == 0xFF

    # Status values that don't fit can't be created
    with pytest.raises(ValueError):
        t.Status(0xFF + 1)
