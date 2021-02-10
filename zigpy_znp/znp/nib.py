import zigpy_znp.types as t


class NwkState(t.enum_uint8):
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

    TransactionPersistenceTime: t.uint16_t

    nwkProtocolVersion: t.uint8_t
    RouteDiscoveryTime: t.uint8_t
    RouteExpiryTime: t.uint8_t

    nwkDevAddress: t.NWK

    nwkLogicalChannel: t.uint8_t

    nwkCoordAddress: t.NWK
    nwkCoordExtAddress: t.EUI64
    nwkPanId: t.uint16_t
    nwkState: NwkState
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

    nwkManagerAddr: t.NWK
    nwkTotalTransmissions: t.uint16_t
    nwkUpdateId: t.uint8_t
