import enum

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
