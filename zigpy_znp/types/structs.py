from . import basic, cstruct, zigpy_types


class NwkKeyDesc(cstruct.CStruct):
    KeySeqNum: basic.uint8_t
    Key: zigpy_types.KeyData


class NwkState(basic.enum8):
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


class NIB(cstruct.CStruct):
    # NwkState is 16 bits on newer platforms but we cheat a little and make it 8, since
    # its max value is 8. However, we can't allow values like 0xFF08 to be serialized.
    _padding_byte = b"\x00"

    SequenceNum: basic.uint8_t
    PassiveAckTimeout: basic.uint8_t
    MaxBroadcastRetries: basic.uint8_t
    MaxChildren: basic.uint8_t
    MaxDepth: basic.uint8_t
    MaxRouters: basic.uint8_t
    dummyNeighborTable: basic.uint8_t
    BroadcastDeliveryTime: basic.uint8_t
    ReportConstantCost: basic.uint8_t
    RouteDiscRetries: basic.uint8_t
    dummyRoutingTable: basic.uint8_t
    SecureAllFrames: basic.uint8_t
    SecurityLevel: basic.uint8_t
    SymLink: basic.uint8_t
    CapabilityFlags: basic.uint8_t

    TransactionPersistenceTime: basic.uint16_t

    nwkProtocolVersion: basic.uint8_t
    RouteDiscoveryTime: basic.uint8_t
    RouteExpiryTime: basic.uint8_t

    nwkDevAddress: zigpy_types.NWK

    nwkLogicalChannel: basic.uint8_t

    nwkCoordAddress: zigpy_types.NWK
    nwkCoordExtAddress: zigpy_types.EUI64
    nwkPanId: basic.uint16_t

    # XXX: this is really a uint16_t but we pad with zeroes so it works out in the end
    nwkState: NwkState
    channelList: zigpy_types.Channels

    beaconOrder: basic.uint8_t
    superFrameOrder: basic.uint8_t
    scanDuration: basic.uint8_t
    battLifeExt: basic.uint8_t

    allocatedRouterAddresses: basic.uint32_t
    allocatedEndDeviceAddresses: basic.uint32_t

    nodeDepth: basic.uint8_t

    extendedPANID: zigpy_types.EUI64

    nwkKeyLoaded: zigpy_types.Bool

    spare1: NwkKeyDesc
    spare2: NwkKeyDesc

    spare3: basic.uint8_t
    spare4: basic.uint8_t

    nwkLinkStatusPeriod: basic.uint8_t
    nwkRouterAgeLimit: basic.uint8_t
    nwkUseMultiCast: zigpy_types.Bool
    nwkIsConcentrator: zigpy_types.Bool
    nwkConcentratorDiscoveryTime: basic.uint8_t
    nwkConcentratorRadius: basic.uint8_t
    nwkAllFresh: basic.uint8_t

    nwkManagerAddr: zigpy_types.NWK
    nwkTotalTransmissions: basic.uint16_t
    nwkUpdateId: basic.uint8_t


class Beacon(cstruct.CStruct):
    """Beacon message."""

    Src: zigpy_types.NWK
    PanId: zigpy_types.PanId
    Channel: basic.uint8_t
    PermitJoining: basic.uint8_t
    RouterCapacity: basic.uint8_t
    DeviceCapacity: basic.uint8_t
    ProtocolVersion: basic.uint8_t
    StackProfile: basic.uint8_t
    LQI: basic.uint8_t
    Depth: basic.uint8_t
    UpdateId: basic.uint8_t
    ExtendedPanId: zigpy_types.ExtendedPanId


class TCLinkKey(cstruct.CStruct):
    ExtAddr: zigpy_types.EUI64
    Key: zigpy_types.KeyData
    TxFrameCounter: basic.uint32_t
    RxFrameCounter: basic.uint32_t


class NwkActiveKeyItems(cstruct.CStruct):
    Active: NwkKeyDesc
    FrameCounter: basic.uint32_t


class KeyType(basic.enum8):
    NONE = 0

    # Standard Network Key
    NWK = 1
    # Application Master Key
    APP_MASTER = 2
    # Application Link Key
    APP_LINK = 3
    # Trust Center Link Key
    TC_LINK = 4

    # XXX: just "6" in the Z-Stack source
    UNKNOWN_6 = 6


class KeyAttributes(basic.enum8):
    # Used for IC derived keys
    PROVISIONAL_KEY = 0x00
    # Unique key that is not verified
    UNVERIFIED_KEY = 0x01
    # Unique key that got verified by ZC
    VERIFIED_KEY = 0x02

    # Internal definitions

    # Use default key to join
    DISTRIBUTED_DEFAULT_KEY = 0xFC
    # Joined a network which is not R21 nwk, so TCLK process finished.
    NON_R21_NWK_JOINED = 0xFD
    # Unique key that got verified by Joining device.
    # This means that key is stored as plain text (not seed hashed)
    VERIFIED_KEY_JOINING_DEV = 0xFE
    # Entry using default key
    DEFAULT_KEY = 0xFF


class TCLKDevEntry(cstruct.CStruct):
    _padding_byte = b"\x00"

    txFrmCntr: basic.uint32_t
    rxFrmCntr: basic.uint32_t

    extAddr: zigpy_types.EUI64
    keyAttributes: KeyAttributes
    keyType: KeyType

    # For Unique key this is the number of shifts
    # for IC this is the offset on the NvId index
    SeedShift_IcIndex: basic.uint8_t


class NwkSecMaterialDesc(cstruct.CStruct):
    FrameCounter: basic.uint32_t
    ExtendedPanID: zigpy_types.EUI64


class AddrMgrUserType(basic.bitmap8):
    Default = 0x00
    Assoc = 0x01
    Security = 0x02
    Binding = 0x04
    Private1 = 0x08


class AddrMgrEntry(cstruct.CStruct):
    type: AddrMgrUserType
    nwkAddr: zigpy_types.NWK
    extAddr: zigpy_types.EUI64


class AddressManagerTable(basic.CompleteList, item_type=AddrMgrEntry):
    pass


class AuthenticationOption(basic.enum8):
    NotAuthenticated = 0x00
    AuthenticatedCBCK = 0x01
    AuthenticatedEA = 0x02


class APSKeyDataTableEntry(cstruct.CStruct):
    Key: zigpy_types.KeyData
    TxFrameCounter: basic.uint32_t
    RxFrameCounter: basic.uint32_t


class APSLinkKeyTableEntry(cstruct.CStruct):
    AddressManagerIndex: basic.uint16_t
    LinkKeyNvId: basic.uint16_t
    AuthenticationState: AuthenticationOption


class APSLinkKeyTable(
    basic.LVList, length_type=basic.uint16_t, item_type=APSLinkKeyTableEntry
):
    pass


class LinkInfo(cstruct.CStruct):
    # Counter of transmission success/failures
    txCounter: basic.uint8_t
    # Average of sending rssi values if link staus is enabled
    # i.e. NWK_LINK_STATUS_PERIOD is defined as non zero
    txCost: basic.uint8_t
    # average of received rssi values.
    # needs to be converted to link cost (1-7) before use
    rxLqi: basic.uint8_t
    # security key sequence number
    inKeySeqNum: basic.uint8_t
    # security frame counter..
    inFrmCntr: basic.uint32_t
    # higher values indicate more failures
    txFailure: basic.uint16_t


class AgingEndDevice(cstruct.CStruct):
    endDevCfg: basic.uint8_t
    deviceTimeout: basic.uint32_t


class BaseAssociatedDevice(cstruct.CStruct):
    shortAddr: basic.uint16_t
    addrIdx: basic.uint16_t
    nodeRelation: basic.uint8_t
    devStatus: basic.uint8_t
    assocCnt: basic.uint8_t
    age: basic.uint8_t
    linkInfo: LinkInfo
    endDev: AgingEndDevice
    timeoutCounter: basic.uint32_t
    keepaliveRcv: zigpy_types.Bool


class AssociatedDeviceZStack1(BaseAssociatedDevice):
    pass


class AssociatedDeviceZStack3(BaseAssociatedDevice):
    ctrl: basic.uint8_t  # This member was added
