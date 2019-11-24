import enum

import pytest

import zigpy_znp.types as t


def test_enum_uint():
    class TE(t.enum_uint16, enum.IntFlag):
        ALL = 0xFFFF
        CH_1 = 0x0001
        CH_2 = 0x0002
        CH_3 = 0x0004
        CH_5 = 0x0008
        CH_6 = 0x0010
        CH_Z = 0x8000

    extra = b"The rest of the data\x55\xaa"
    data = b"\x12\x80"

    r, rest = TE.deserialize(data + extra)
    assert rest == extra
    assert r == 0x8012
    assert r == (TE.CH_2 | TE.CH_6 | TE.CH_Z)

    assert r.serialize() == data
    assert TE(0x8012).serialize() == data


def test_serialize():
    data = [1, 3, 4]
    schema = (t.Status, t.uint16_t, t.uint32_t)
    assert t.serialize(data, schema) == b"\x01\x03\x00\x04\x00\x00\x00"


def test_int_too_short():
    with pytest.raises(ValueError):
        t.uint8_t.deserialize(b"")

    with pytest.raises(ValueError):
        t.uint16_t.deserialize(b"\x00")


def test_bytes():
    data = b"abcde\x00\xff"

    r, rest = t.Bytes.deserialize(data)
    assert rest == b""
    assert r == data

    assert r.serialize() == data


def test_lvbytes():
    data = b"abcde\x00\xff"
    extra = b"\xffrest of the data\x00"

    r, rest = t.LVBytes.deserialize(len(data).to_bytes(2, "little") + data + extra)
    assert rest == extra
    assert r == data

    assert r.serialize() == len(data).to_bytes(2, "little") + data


def test_list():
    class TestList(t.List):
        _itemtype = t.uint16_t

    r = TestList([1, 2, 3, 0x55AA])
    assert r.serialize() == b"\x01\x00\x02\x00\x03\x00\xaa\x55"


def test_list_deserialize():
    class TestList(t.List):
        _itemtype = t.uint16_t

    data = b"\x34\x12\x55\xaa\x89\xab"
    extra = b"\x00\xff"

    r, rest = TestList.deserialize(data + extra)
    assert rest == b""
    assert r[0] == 0x1234
    assert r[1] == 0xAA55
    assert r[2] == 0xAB89
    assert r[3] == 0xFF00


def test_lvlist():
    d, r = t.LVList(t.uint8_t).deserialize(b"\x0412345")
    assert r == b"5"
    assert d == list(map(ord, "1234"))
    assert t.LVList(t.uint8_t).serialize(d) == b"\x041234"


def test_lvlist_too_short():
    with pytest.raises(ValueError):
        t.LVList(t.uint8_t).deserialize(b"")

    with pytest.raises(ValueError):
        t.LVList(t.uint8_t).deserialize(b"\x04123")


def test_hex_repr():
    class NwkAsHex(t.HexRepr, t.uint16_t):
        _hex_len = 4

    nwk = NwkAsHex(0x1234)
    assert str(nwk) == "0x1234"
    assert repr(nwk) == "0x1234"


def test_fixed_list():
    class TestList(t.FixedList):
        _length = 3
        _itemtype = t.uint16_t

    with pytest.raises(AssertionError):
        r = TestList([1, 2, 3, 0x55AA])
        r.serialize()

    with pytest.raises(AssertionError):
        r = TestList([1, 2])
        r.serialize()

    r = TestList([1, 2, 3])

    assert r.serialize() == b"\x01\x00\x02\x00\x03\x00"


def test_fixed_list_deserialize():
    class TestList(t.FixedList):
        _length = 3
        _itemtype = t.uint16_t

    data = b"\x34\x12\x55\xaa\x89\xab"
    extra = b"\x00\xff"

    r, rest = TestList.deserialize(data + extra)
    assert rest == extra
    assert r[0] == 0x1234
    assert r[1] == 0xAA55
    assert r[2] == 0xAB89
