import pytest

import zigpy_znp.commands as c
import zigpy_znp.types as t


def test_status():
    """Test Status enum."""

    assert t.Status.SUCCESS == 0
    assert t.Status.FAILURE == 1

    extra = b"the rest of the owl\xaa\x55\x00\xff"

    r, rest = t.Status.deserialize(b"\x00" + extra)
    assert rest == extra
    assert r == 0
    assert r == t.Status.SUCCESS
    assert r.name == "SUCCESS"

    r, rest = t.Status.deserialize(b"\x33" + extra)
    assert rest == extra
    assert r == 0x33
    assert r.value == 0x33
    assert r.name == "unknown_0x33"


def test_addr_mode_address():
    """Test Addr mode address."""

    data = b"\x03\x00\x01\x02\x03\x04\x05\x06\x07"
    extra = b"The rest of the data\x55\xaa"

    # IEEE
    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.IEEE
    assert r.address == t.EUI64(range(8))
    assert r.serialize() == data

    # NWK
    data = b"\x02\xaa\x55\x02\x03\x04\x05\x06\x07"
    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.NWK
    assert r.address == t.NWK(0x55AA)
    assert r.serialize()[:3] == data[:3]
    assert len(r.serialize()) == 9

    # Group
    data = b"\x01\xcd\xab\x02\x03\x04\x05\x06\x07"
    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.Group
    assert r.address == t.NWK(0xABCD)
    assert r.serialize()[:3] == data[:3]
    assert len(r.serialize()) == 9

    # Broadcast
    data = b"\x0f\xfe\xff\x02\x03\x04\x05\x06\x07"
    r, rest = t.AddrModeAddress.deserialize(data + extra)
    assert rest == extra
    assert r.mode == t.AddrMode.Broadcast
    assert r.address == t.NWK(0xFFFE)
    assert r.serialize()[:3] == data[:3]
    assert len(r.serialize()) == 9

    with pytest.raises(ValueError):
        # 0xab is not a valid mode
        data = b"\xAB\xaa\x55\x02\x03\x04\x05\x06\x07"
        t.AddrModeAddress.deserialize(data)

    with pytest.raises(ValueError):
        # NOT_PRESENT is a valid AddrMode member but it is not a valid AddrModeAddress
        data = b"\x00\xaa\x55\x02\x03\x04\x05\x06\x07"
        t.AddrModeAddress.deserialize(data)

    # Bytes at the end for NWK address mode are ignored
    data1 = b"\x02\x0E\xAD" + b"\xC0\x8C\x97\x83\xB0\x20\x33"
    data2 = b"\x02\x0E\xAD" + b"\x3F\xB9\x5B\x64\x20\x86\xD6"

    r1, _ = t.AddrModeAddress.deserialize(data1)
    r2, _ = t.AddrModeAddress.deserialize(data2)

    assert r1 == r2

    # All of the bytes are used for IEEE address mode
    data1 = b"\x02\x0E\xAD\xC0\x8C\x97\x83\xB0\x20\x33"
    data2 = b"\x02\x0E\xAD\x3F\xB9\x5B\x64\x20\x86\xD6"

    r3, _ = t.AddrModeAddress.deserialize(b"\x03" + data1[1:])
    r4, _ = t.AddrModeAddress.deserialize(b"\x03" + data2[1:])

    assert r3 != r4


def test_missing_status_enum():
    class TestEnum(t.MissingEnumMixin, t.enum_uint8):
        Member = 0x00

    assert 0xFF not in list(TestEnum)
    assert isinstance(TestEnum(0xFF), TestEnum)
    assert TestEnum(0xFF).value == 0xFF
    assert type(TestEnum(0xFF).value) is t.uint8_t

    # Missing members that don't fit can't be created
    with pytest.raises(ValueError):
        TestEnum(0xFF + 1)

    # Missing members that aren't integers can't be created
    with pytest.raises(ValueError):
        TestEnum("0xFF")


def test_zdo_nullable_node_descriptor():
    desc1, data = c.zdo.NullableNodeDescriptor.deserialize(b"\x00")

    # Old-style zigpy structs
    if hasattr(desc1, "_fields"):
        assert all(getattr(desc1, f) is None for f, _ in desc1._fields)
    else:
        assert all(value is None for field, value in desc1.assigned_fields())

    assert not data
    assert desc1.serialize() == b"\x00"

    desc2 = c.zdo.NullableNodeDescriptor(1, 2, 3, 4, 5, 6, 7, 8, 9)
    desc3, data = c.zdo.NullableNodeDescriptor.deserialize(desc2.serialize())

    assert not data
    assert desc2.serialize() == desc3.serialize()


def test_missing_enum_mixin():
    class TestEnum(t.MissingEnumMixin, t.enum_uint8):
        FOO = 0x01

    assert TestEnum(0x01) == 0x01 == TestEnum.FOO
    assert TestEnum(0x02) == 0x02
    assert 0x02 not in TestEnum._value2member_map_
