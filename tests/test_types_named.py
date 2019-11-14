import pytest

from unittest import mock

from zigpy_znp import types as t


def test_fake_enum():
    """Test fake enum."""

    fake_enum = t.FakeEnum("test_enum")
    r = fake_enum("test_member", mock.sentinel.value)
    assert r == mock.sentinel.value
    assert mock.sentinel.wrong != r


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
        data = b"\x0f\xaa\x55\x02\x03\x04\x05\x06\x07"
        t.AddrModeAddress.deserialize(data)
