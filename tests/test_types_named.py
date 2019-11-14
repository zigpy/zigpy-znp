from unittest import mock

from zigpy_znp import types as t


def test_fake_enum():
    """Test fake enum."""

    fake_enum = t.FakeEnum("test_enum")
    r = fake_enum("test_member", mock.sentinel.value)
    assert r == mock.sentinel.value
    assert mock.sentinel.wrong != r
