import typing

import zigpy_znp.types as t


class NwkState8(t.enum_uint8):
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


class NwkState16(t.enum_uint16):
    """
    This enum is identical to `NwkState8`, with the only difference being the base class
    """

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


class PaddingByte(t.Bytes):
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls, *args, **kwargs)

        if len(instance) != 1:
            raise ValueError("Padding byte must be a single byte")

        return instance

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple[t.Bytes, bytes]:
        if not data:
            raise ValueError("Data is empty and cannot contain a padding byte")

        return cls(data[:1]), data[1:]


class Empty(t.Bytes):
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls, *args, **kwargs)

        if instance:
            raise ValueError("Empty must be empty")

        return instance

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple[t.Bytes, bytes]:
        return cls(), data


class NwkKeyDesc(t.Struct):
    keySeqNum: t.uint8_t
    key: t.KeyData


class NIB(t.Struct):
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

    spare1: NwkKeyDesc
    spare2: NwkKeyDesc

    spare3: t.uint8_t
    spare4: t.uint8_t

    nwkLinkStatusPeriod: t.uint8_t
    nwkRouterAgeLimit: t.uint8_t
    nwkUseMultiCast: t.Bool
    nwkIsConcentrator: t.Bool
    nwkConcentratorDiscoveryTime: t.uint8_t
    nwkConcentratorRadius: t.uint8_t
    nwkAllFresh: t.uint8_t

    PaddingByte3: PaddingByte

    nwkManagerAddr: t.NWK
    nwkTotalTransmissions: t.uint16_t
    nwkUpdateId: t.uint8_t

    PaddingByte4: PaddingByte


class CC2531NIB(t.Struct):
    """
    Struct doesn't allow field re-ordering so this is unfortunately a duplicate of the
    above `NIB` structure, with the following differences:

     1. There are no padding bytes.
     2. The `NwkState` enum is a `uint8_t` instead of a `uint16_t`

    Otherwise, the contents of the two structs are identical. These are only alignment
    differences between the two platforms.
    """

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

    TransactionPersistenceTime: t.uint16_t

    nwkProtocolVersion: t.uint8_t
    RouteDiscoveryTime: t.uint8_t
    RouteExpiryTime: t.uint8_t

    nwkDevAddress: t.NWK

    nwkLogicalChannel: t.uint8_t

    nwkCoordAddress: t.NWK
    nwkCoordExtAddress: t.EUI64
    nwkPanId: t.uint16_t
    nwkState: NwkState8
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

    spare1: NwkKeyDesc
    spare2: NwkKeyDesc

    spare3: t.uint8_t
    spare4: t.uint8_t

    nwkLinkStatusPeriod: t.uint8_t
    nwkRouterAgeLimit: t.uint8_t
    nwkUseMultiCast: t.Bool
    nwkIsConcentrator: t.Bool
    nwkConcentratorDiscoveryTime: t.uint8_t
    nwkConcentratorRadius: t.uint8_t
    nwkAllFresh: t.uint8_t

    nwkManagerAddr: t.NWK
    nwkTotalTransmissions: t.uint16_t
    nwkUpdateId: t.uint8_t


def parse_nib(data: bytes) -> typing.Union[NIB, CC2531NIB]:
    if len(data) == 116:
        nib, remaining = NIB.deserialize(data)
    elif len(data) == 110:
        nib, remaining = CC2531NIB.deserialize(data)
    else:
        raise ValueError(f"Unknown NIB format: {data!r}")

    assert not remaining

    return nib
