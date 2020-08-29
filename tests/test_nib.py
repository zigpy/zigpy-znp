import pytest

import zigpy_znp.types as t

from zigpy_znp.znp.nib import (
    NIB,
    OldNIB,
    parse_nib,
    NwkState8,
    NwkState16,
    PaddingByte,
    Empty,
)


NEW_NIB = bytes.fromhex(
    """
    790502331433001e0000000105018f00070002051e000000190000000000000000000000958608000080
    10020f0f0400010000000100000000a860ca53db3bc0a801000000000000000000000000000000000000
    0000000000000000000000000000000000000f030001780a0100000020470000"""
)

OLD_NIB = bytes.fromhex(
    """
    5f0502101410001e0000000105018f070002051e0000140000000000000000000085d208000010020f0f
    05000100000001000000008533ce1c004b12000100000000000000000000000000000000000000000000
    00000000000000000000000000003c030001780a010000170000"""
)


def test_nwk_state():
    assert NwkState8._member_type_ == t.uint8_t
    assert NwkState16._member_type_ == t.uint16_t

    # They should be otherwise identical
    assert NwkState8._value2member_map_ == NwkState16._value2member_map_


def test_padding_byte():
    with pytest.raises(ValueError):
        PaddingByte.deserialize(b"")

    with pytest.raises(ValueError):
        PaddingByte(b"ab")

    with pytest.raises(ValueError):
        PaddingByte(b"")

    assert PaddingByte.deserialize(b"abc") == (PaddingByte(b"a"), b"bc")
    assert PaddingByte.deserialize(b"a") == (PaddingByte(b"a"), b"")


def test_empty():
    with pytest.raises(ValueError):
        Empty(b"a")

    assert Empty.deserialize(b"abc") == (Empty(), b"abc")
    assert Empty.deserialize(b"") == (Empty(), b"")


def test_nib_classes():
    old_nib_nwk_state = next(a for a in OldNIB.fields() if a.type == NwkState8)

    # The old NIB should be the new NIB, without padding and with a shorter struct
    # integer type.
    fixed_new_nib = [
        a if a.type != NwkState16 else old_nib_nwk_state
        for a in NIB.fields()
        if a.type is not PaddingByte
    ]

    assert fixed_new_nib == list(OldNIB.fields())


def test_nib_detection():
    assert isinstance(parse_nib(NEW_NIB), NIB)
    assert isinstance(parse_nib(OLD_NIB), OldNIB)

    with pytest.raises(ValueError):
        parse_nib(NEW_NIB + b"\x00")

    with pytest.raises(ValueError):
        parse_nib(OLD_NIB + b"\x00")


def test_nib_parsing():
    new_nib, remaining = NIB.deserialize(NEW_NIB)
    assert not remaining

    old_nib, remaining = OldNIB.deserialize(OLD_NIB)
    assert not remaining

    assert new_nib.serialize() == NEW_NIB
    assert old_nib.serialize() == OLD_NIB

    # Superficially validate that the NIBs were parsed correctly
    for nib in (new_nib, old_nib):
        assert nib.nwkProtocolVersion == 2

        # Make sure the channel list is valid
        assert nib.channelList | t.Channels.ALL_CHANNELS == t.Channels.ALL_CHANNELS

        # Make sure the logical channel is contained within the channel mask
        assert (
            t.Channels.from_channel_list([nib.nwkLogicalChannel]) | nib.channelList
            == nib.channelList
        )

        assert nib.nwkKeyLoaded
        assert nib.nwkIsConcentrator
        assert nib.nwkManagerAddr == t.NWK(0x0000)
        assert nib.nwkCoordAddress == t.NWK(0x0000)
