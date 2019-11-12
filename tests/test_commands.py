import zigpy_znp.commands as cmds


def test_error_code():
    data = b"\x03"
    extra = b"the rest of the owl\x00\xff"

    r, rest = cmds.ErrorCode.deserialize(data + extra)
    assert rest == extra
    assert r == 0x03
    assert r.name == "INVALID_PARAMETER"

    r, rest = cmds.ErrorCode.deserialize(b"\xaa" + extra)
    assert rest == extra
    assert r.name == "unknown_0xaa"