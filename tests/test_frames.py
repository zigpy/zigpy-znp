import pytest

import zigpy_znp.types as t
import zigpy_znp.api.frames as frames


def test_general_frame():
    data = b"\xaa\55\xccdata goes in here\x00\x00"
    length = t.uint8_t(len(data)).serialize()
    cmd = 0x23

    frame = frames.GeneralFrame(0, cmd, data)
    assert frame.serialize() == length + b"\x23\x00" + data

    with pytest.raises(ValueError):
        frames.GeneralFrame(0, 0, b"\x00" * 251)

    extra = b"the rest of the owl\x00\x00"
    r, rest = frames.GeneralFrame.deserialize(length + b"\x23\x00" + data + extra)
    assert rest == extra


def test_general_frame_wrong_data():
    # wrong length
    data = b"\xfb" + b"\x00" * 258
    with pytest.raises(ValueError):
        frames.GeneralFrame.deserialize(data)

    # data too short
    data = b"\x04\x00\x00"
    with pytest.raises(ValueError):
        frames.GeneralFrame.deserialize(data)
