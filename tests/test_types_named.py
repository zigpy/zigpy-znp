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
