import ast
import pytest

import zigpy_znp.types as t


def test_serialize_list():
    class TestList(t.LVList, item_type=t.uint8_t, length_type=t.uint8_t):
        pass

    assert (
        t.serialize_list([t.uint8_t(0xF0), t.Bytes(b"asd"), TestList([0xAB, 0xCD])])
        == b"\xF0asd\x02\xAB\xCD"
    )

    assert t.serialize_list([]) == b""


def test_enum_uint():
    class TE(t.enum_flag_uint16):
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


def test_abstract_ints():
    assert issubclass(t.uint8_t, t.uint_t)
    assert not issubclass(t.uint8_t, t.int_t)
    assert t.int_t._signed is True
    assert t.uint_t._signed is False

    with pytest.raises(TypeError):
        t.int_t(0)

    with pytest.raises(TypeError):
        t.FixedIntType(0)


def test_int_too_short():
    with pytest.raises(ValueError):
        t.uint8_t.deserialize(b"")

    with pytest.raises(ValueError):
        t.uint16_t.deserialize(b"\x00")


def test_int_out_of_bounds():
    with pytest.raises(ValueError):
        t.uint8_t(-1)

    with pytest.raises(ValueError):
        t.uint8_t(0xFF + 1)


def test_bytes():
    data = b"abcde\x00\xff"

    r, rest = t.Bytes.deserialize(data)
    assert rest == b""
    assert r == data

    assert r.serialize() == data

    assert str(r) == repr(r) == "b'\\x61\\x62\\x63\\x64\\x65\\x00\\xFF'"

    # Ensure we don't make any mistakes formatting the bytes
    all_bytes = t.Bytes(bytes(range(0, 255 + 1)))
    long_repr = repr(all_bytes)
    assert ast.literal_eval(long_repr) == ast.literal_eval(bytes.__repr__(all_bytes))
    assert all_bytes == ast.literal_eval(long_repr)


def test_longbytes():
    data = b"abcde\x00\xff" * 50
    extra = b"\xffrest of the data\x00"

    r, rest = t.LongBytes.deserialize(len(data).to_bytes(2, "little") + data + extra)
    assert rest == extra
    assert r == data

    assert r.serialize() == len(data).to_bytes(2, "little") + data

    with pytest.raises(ValueError):
        t.LongBytes.deserialize(b"\x01")

    with pytest.raises(ValueError):
        t.LongBytes.deserialize(b"\x01\x00")

    with pytest.raises(ValueError):
        t.LongBytes.deserialize(len(data).to_bytes(2, "little") + data[:-1])


def test_lvlist():
    class TestList(t.LVList, item_type=t.uint8_t, length_type=t.uint8_t):
        pass

    d, r = TestList.deserialize(b"\x0412345")
    assert r == b"5"
    assert d == list(map(ord, "1234"))
    assert TestList.serialize(d) == b"\x041234"

    assert isinstance(d, TestList)

    with pytest.raises(ValueError):
        TestList([1, 2, 0xFFFF, 4]).serialize()


def test_lvlist_too_short():
    class TestList(t.LVList, item_type=t.uint8_t, length_type=t.uint8_t):
        pass

    with pytest.raises(ValueError):
        TestList.deserialize(b"")

    with pytest.raises(ValueError):
        TestList.deserialize(b"\x04123")


def test_hex_repr():
    class NwkAsHex(t.uint16_t, hex_repr=True):
        pass

    nwk = NwkAsHex(0x123A)
    assert str(nwk) == "0x123A"
    assert repr(nwk) == "0x123A"

    assert str([nwk]) == "[0x123A]"
    assert repr([nwk]) == "[0x123A]"

    # You can turn it off as well
    class NwkWithoutHex(NwkAsHex, hex_repr=False):
        pass

    nwk = NwkWithoutHex(1234)
    assert str(nwk) == "1234"
    assert repr(nwk) == "1234"

    assert str([nwk]) == "[1234]"
    assert repr([nwk]) == "[1234]"


def test_fixed_list():
    class TestList(t.FixedList, item_type=t.uint16_t, length=3):
        pass

    with pytest.raises(ValueError):
        r = TestList([1, 2, 3, 0x55AA])
        r.serialize()

    with pytest.raises(ValueError):
        r = TestList([1, 2])
        r.serialize()

    r = TestList([1, 2, 3])

    assert r.serialize() == b"\x01\x00\x02\x00\x03\x00"


def test_fixed_list_deserialize():
    class TestList(t.FixedList, length=3, item_type=t.uint16_t):
        pass

    data = b"\x34\x12\x55\xaa\x89\xab"
    extra = b"\x00\xff"

    r, rest = TestList.deserialize(data + extra)
    assert rest == extra
    assert r[0] == 0x1234
    assert r[1] == 0xAA55
    assert r[2] == 0xAB89


def test_enum_instance_types():
    class TestEnum(t.enum_uint8):
        Member = 0x00

    assert TestEnum._member_type_ is t.uint8_t
    assert type(TestEnum.Member.value) is t.uint8_t
