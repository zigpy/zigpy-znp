import typing

import pytest

import zigpy_znp.types as t

if typing.TYPE_CHECKING:
    import typing_extensions


def test_struct_fields():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

    assert len(TestStruct.fields) == 2

    assert TestStruct.fields.a.name == "a"
    assert TestStruct.fields.a.type == t.uint8_t

    assert TestStruct.fields.b.name == "b"
    assert TestStruct.fields.b.type == t.uint16_t


def test_struct_field_values():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

    struct = TestStruct(a=1, b=2)
    assert struct.a == 1
    assert isinstance(struct.a, t.uint8_t)

    assert struct.b == 2
    assert isinstance(struct.b, t.uint16_t)

    # Invalid values can't be passed during construction
    with pytest.raises(ValueError):
        TestStruct(a=1, b=2**32)

    struct2 = TestStruct()
    struct2.a = 1
    struct2.b = 2

    assert struct == struct2
    assert struct.serialize() == struct2.serialize()


def test_struct_methods_and_constants():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

        def method(self):
            return self.a + self.b

        def annotated_method(self: "TestStruct") -> int:
            return self.method()

        CONSTANT1 = 1
        constant2 = "foo"
        _constant3 = "bar"

    assert len(TestStruct.fields) == 2
    assert TestStruct.fields.a == t.CStructField(name="a", type=t.uint8_t)
    assert TestStruct.fields.b == t.CStructField(name="b", type=t.uint16_t)

    assert TestStruct.CONSTANT1 == 1
    assert TestStruct.constant2 == "foo"
    assert TestStruct._constant3 == "bar"

    assert TestStruct(a=1, b=2).method() == 3


def test_struct_nesting():
    class Outer(t.CStruct):
        e: t.uint32_t

    class TestStruct(t.CStruct):
        class Inner(t.CStruct):
            c: t.uint16_t

        a: t.uint8_t
        b: Inner
        d: Outer

    assert len(TestStruct.fields) == 3
    assert TestStruct.fields.a == t.CStructField(name="a", type=t.uint8_t)
    assert TestStruct.fields.b == t.CStructField(name="b", type=TestStruct.Inner)
    assert TestStruct.fields.d == t.CStructField(name="d", type=Outer)

    assert len(TestStruct.Inner.fields) == 1
    assert TestStruct.Inner.fields.c == t.CStructField(name="c", type=t.uint16_t)

    struct = TestStruct(a=1, b=TestStruct.Inner(c=2), d=Outer(e=3))
    assert struct.a == 1
    assert struct.b.c == 2
    assert struct.d.e == 3


def test_struct_aligned_serialization_deserialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        # One padding byte here
        b: t.uint16_t
        # No padding here
        c: t.uint32_t  # largest type, so the struct is 32 bit aligned
        d: t.uint8_t
        # Three padding bytes here
        e: t.uint32_t
        f: t.uint8_t
        # Three more to make the struct 32 bit aligned

    assert TestStruct.get_alignment(align=False) == 1
    assert TestStruct.get_alignment(align=True) == 32 // 8
    assert TestStruct.get_size(align=False) == (1 + 2 + 4 + 1 + 4 + 1)
    assert TestStruct.get_size(align=True) == (1 + 2 + 4 + 1 + 4 + 1) + (1 + 3 + 3)

    expected = b""
    expected += t.uint8_t(1).serialize()
    expected += b"\xFF" + t.uint16_t(2).serialize()
    expected += t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += b"\xFF\xFF\xFF" + t.uint32_t(5).serialize()
    expected += t.uint8_t(6).serialize()
    expected += b"\xFF\xFF\xFF"

    struct = TestStruct(a=1, b=2, c=3, d=4, e=5, f=6)
    assert struct.serialize(align=True) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=True)
    assert remaining == b"test"
    assert struct == struct2

    with pytest.raises(ValueError):
        TestStruct.deserialize(expected[:-1], align=True)


def test_struct_aligned_nested_serialization_deserialization():
    class Inner(t.CStruct):
        _padding_byte = b"\xCD"

        c: t.uint8_t
        d: t.uint32_t
        e: t.uint8_t

    class TestStruct(t.CStruct):
        _padding_byte = b"\xAB"

        a: t.uint8_t
        b: Inner
        f: t.uint16_t

    expected = b""
    expected += t.uint8_t(1).serialize()

    # Inner struct
    expected += b"\xAB\xAB\xAB" + t.uint8_t(2).serialize()
    expected += b"\xCD\xCD\xCD" + t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += b"\xCD\xCD\xCD"  # Aligned to 4 bytes

    expected += t.uint16_t(5).serialize()
    expected += b"\xAB\xAB"  # Also aligned to 4 bytes due to inner struct

    struct = TestStruct(a=1, b=Inner(c=2, d=3, e=4), f=5)
    assert struct.serialize(align=True) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=True)
    assert remaining == b"test"
    assert struct == struct2


def test_struct_unaligned_serialization_deserialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t
        c: t.uint32_t
        d: t.uint8_t
        e: t.uint32_t
        f: t.uint8_t

    expected = b""
    expected += t.uint8_t(1).serialize()
    expected += t.uint16_t(2).serialize()
    expected += t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += t.uint32_t(5).serialize()
    expected += t.uint8_t(6).serialize()

    struct = TestStruct(a=1, b=2, c=3, d=4, e=5, f=6)

    assert struct.serialize(align=False) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=False)
    assert remaining == b"test"
    assert struct == struct2

    with pytest.raises(ValueError):
        TestStruct.deserialize(expected[:-1], align=False)


def test_struct_equality():
    class InnerStruct(t.CStruct):
        c: t.EUI64

    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: InnerStruct

    class TestStruct2(t.CStruct):
        a: t.uint8_t
        b: InnerStruct

    s1 = TestStruct(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))
    s2 = TestStruct(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))
    s3 = TestStruct2(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))

    assert s1 == s2
    assert s1.replace(a=3) != s1
    assert s1.replace(a=3).replace(a=2) == s1

    assert s1 != s3
    assert s1.serialize() == s3.serialize()

    assert TestStruct(s1) == s1
    assert TestStruct(a=s1.a, b=s1.b) == s1

    with pytest.raises(ValueError):
        TestStruct(s1, b=InnerStruct(s1.b))

    with pytest.raises(ValueError):
        TestStruct2(s1)


def test_struct_repr():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint32_t

    assert str(TestStruct(a=1, b=2)) == "TestStruct(a=1, b=2)"
    assert str([TestStruct(a=1, b=2)]) == "[TestStruct(a=1, b=2)]"


def test_struct_bad_fields():
    with pytest.raises(TypeError):

        class TestStruct(t.CStruct):
            a: t.uint8_t
            b: int


def test_struct_incomplete_serialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint8_t

    TestStruct(a=1, b=2).serialize()

    with pytest.raises(ValueError):
        TestStruct(a=1, b=None).serialize()

    with pytest.raises(ValueError):
        TestStruct(a=1).serialize()

    struct = TestStruct(a=1, b=2)
    struct.b = object()

    with pytest.raises(ValueError):
        struct.serialize()


def test_old_nib_deserialize():
    PaddingByte: typing_extensions.TypeAlias = t.uint8_t

    class NwkState16(t.enum16):
        NWK_INIT = 0
        NWK_JOINING_ORPHAN = 1
        NWK_DISC = 2
        NWK_JOINING = 3
        NWK_ENDDEVICE = 4
        PAN_CHNL_SELECTION = 5
        PAN_CHNL_VERIFY = 6
        PAN_STARTING = 7
        NWK_ROUTER = 8
        NWK_REJOINING = 9

    class OldNIB(t.CStruct):
        SequenceNum: t.uint8_t
        PassiveAckTimeout: t.uint8_t
        MaxBroadcastRetries: t.uint8_t
        MaxChildren: t.uint8_t
        MaxDepth: t.uint8_t
        MaxRouters: t.uint8_t
        dummyNeighborTable: t.uint8_t
        BroadcastDeliveryTime: t.uint8_t
        ReportConstantCost: t.uint8_t
        RouteDiscRetries: t.uint8_t
        dummyRoutingTable: t.uint8_t
        SecureAllFrames: t.uint8_t
        SecurityLevel: t.uint8_t
        SymLink: t.uint8_t
        CapabilityFlags: t.uint8_t
        PaddingByte0: PaddingByte
        TransactionPersistenceTime: t.uint16_t
        nwkProtocolVersion: t.uint8_t
        RouteDiscoveryTime: t.uint8_t
        RouteExpiryTime: t.uint8_t
        PaddingByte1: PaddingByte
        nwkDevAddress: t.NWK
        nwkLogicalChannel: t.uint8_t
        PaddingByte2: PaddingByte
        nwkCoordAddress: t.NWK
        nwkCoordExtAddress: t.EUI64
        nwkPanId: t.uint16_t
        nwkState: NwkState16
        channelList: t.Channels
        beaconOrder: t.uint8_t
        superFrameOrder: t.uint8_t
        scanDuration: t.uint8_t
        battLifeExt: t.uint8_t
        allocatedRouterAddresses: t.uint32_t
        allocatedEndDeviceAddresses: t.uint32_t
        nodeDepth: t.uint8_t
        extendedPANID: t.EUI64
        nwkKeyLoaded: t.Bool
        spare1: t.NwkKeyDesc
        spare2: t.NwkKeyDesc
        spare3: t.uint8_t
        spare4: t.uint8_t
        nwkLinkStatusPeriod: t.uint8_t
        nwkRouterAgeLimit: t.uint8_t
        nwkUseMultiCast: t.Bool
        nwkIsConcentrator: t.Bool
        nwkConcentratorDiscoveryTime: t.uint8_t
        nwkConcentratorRadius: t.uint8_t
        nwkAllFresh: t.uint8_t
        PaddingByte3: PaddingByte  # type:ignore[valid-type]
        nwkManagerAddr: t.NWK
        nwkTotalTransmissions: t.uint16_t
        nwkUpdateId: t.uint8_t
        PaddingByte4: PaddingByte  # type:ignore[valid-type]

    nib = t.NIB(
        SequenceNum=54,
        PassiveAckTimeout=5,
        MaxBroadcastRetries=2,
        MaxChildren=51,
        MaxDepth=15,
        MaxRouters=51,
        dummyNeighborTable=0,
        BroadcastDeliveryTime=30,
        ReportConstantCost=0,
        RouteDiscRetries=0,
        dummyRoutingTable=0,
        SecureAllFrames=1,
        SecurityLevel=5,
        SymLink=1,
        CapabilityFlags=143,
        TransactionPersistenceTime=7,
        nwkProtocolVersion=2,
        RouteDiscoveryTime=13,
        RouteExpiryTime=30,
        nwkDevAddress=0x0000,
        nwkLogicalChannel=25,
        nwkCoordAddress=0x0000,
        nwkCoordExtAddress=t.EUI64.convert("00:00:00:00:00:00:00:00"),
        nwkPanId=0xABCD,
        nwkState=t.NwkState.NWK_ROUTER,
        channelList=t.Channels.CHANNEL_25,
        beaconOrder=15,
        superFrameOrder=15,
        scanDuration=4,
        battLifeExt=0,
        allocatedRouterAddresses=1,
        allocatedEndDeviceAddresses=1,
        nodeDepth=0,
        extendedPANID=t.EUI64.convert("AA:BB:CC:DD:EE:FF:00:11"),
        nwkKeyLoaded=t.Bool(True),
        spare1=t.NwkKeyDesc(KeySeqNum=0, Key=16 * [0]),
        spare2=t.NwkKeyDesc(KeySeqNum=0, Key=16 * [0]),
        spare3=0,
        spare4=0,
        nwkLinkStatusPeriod=15,
        nwkRouterAgeLimit=5,
        nwkUseMultiCast=t.Bool(False),
        nwkIsConcentrator=t.Bool(True),
        nwkConcentratorDiscoveryTime=120,
        nwkConcentratorRadius=10,
        nwkAllFresh=1,
        nwkManagerAddr=0x0000,
        nwkTotalTransmissions=39020,
        nwkUpdateId=0,
    )

    # Make sure all the same fields exist
    assert [f.name for f in t.NIB.fields] == [
        f.name for f in OldNIB.fields if not f.name.startswith("PaddingByte")
    ]

    # Make sure the new NIB can be deserialized by the new NIB struct
    old_nib, remaining = OldNIB.deserialize(nib.serialize(align=True))
    assert not remaining

    # And vice versa
    new_nib, remaining = t.NIB.deserialize(old_nib.serialize(), align=True)
    assert not remaining
    assert new_nib == nib

    # And they are deserialized correctly
    for field in nib.fields:
        assert getattr(nib, field.name) == getattr(old_nib, field.name)


def test_struct_addrmode_address():
    class TestStruct(t.CStruct):
        addr: t.AddrModeAddress

    struct = TestStruct(addr=t.AddrModeAddress(mode=t.AddrMode.NWK, address=0x1234))
    assert struct.get_size(align=False) == 1 + 8
    assert struct.get_size(align=True) == 1 + 8
