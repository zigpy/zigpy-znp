import attr

import zigpy_znp.types as t


def test_struct_serialize():
    @attr.s
    class TS(t.Struct):
        field_1 = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
        field_2 = attr.ib(factory=t.EUI64, type=t.EUI64, converter=t.EUI64)

    a = TS(0xAA, range(8))
    d = a.serialize()
    assert d == b"\xaa\x00\x01\x02\x03\x04\x05\x06\x07"


def test_struct_serialize_nested():
    @attr.s
    class TS(t.Struct):
        field_1 = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
        field_2 = attr.ib(factory=t.EUI64, type=t.EUI64, converter=t.EUI64)

    @attr.s
    class Nested(t.Struct):
        field_1 = attr.ib(factory=t.uint16_t, type=t.uint16_t, converter=t.uint16_t)
        field_2 = attr.ib(factory=TS, type=TS)

    a = TS(0xAA, range(8))

    n = Nested(0xAA55, a)

    assert n.serialize() == b"\x55\xaa\xaa\x00\x01\x02\x03\x04\x05\x06\x07"


def test_struct_deserialize():
    @attr.s
    class TS(t.Struct):
        field_1 = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
        field_2 = attr.ib(factory=t.EUI64, type=t.EUI64, converter=t.EUI64)

    data = b"\xaa\x00\x01\x02\x03\x04\x05\x06\x07"
    extra = b"the rest of the owl"

    r, rest = TS.deserialize(data + extra)
    assert rest == extra
    assert r.field_1 == 0xAA
    assert r.field_2 == list(range(8))


def test_struct_deserialize_nested():
    @attr.s
    class TS(t.Struct):
        field_1 = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
        field_2 = attr.ib(factory=t.EUI64, type=t.EUI64, converter=t.EUI64)

    @attr.s
    class Nested(t.Struct):
        field_1 = attr.ib(factory=t.uint16_t, type=t.uint16_t, converter=t.uint16_t)
        field_2 = attr.ib(factory=TS, type=TS)

    data = b"\x55\xaa\xaa\x00\x01\x02\x03\x04\x05\x06\x07"
    extra = b"the rest of the owl\x00\xff"

    r, rest = Nested.deserialize(data + extra)
    assert rest == extra
    assert r.field_1 == 0xAA55
    assert isinstance(r.field_2, TS)
    assert r.field_2.field_1 == 0xAA
    assert r.field_2.field_2 == list(range(8))
