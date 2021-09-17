import zigpy_znp.types as t

DEFAULT_NIB = t.NIB(
    SequenceNum=0,
    PassiveAckTimeout=5,
    MaxBroadcastRetries=2,
    MaxChildren=0,
    MaxDepth=20,
    MaxRouters=0,
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
    RouteDiscoveryTime=5,
    RouteExpiryTime=30,
    nwkDevAddress=0xFFFE,
    nwkLogicalChannel=0,
    nwkCoordAddress=0xFFFE,
    nwkCoordExtAddress=t.EUI64.convert("00:00:00:00:00:00:00:00"),
    nwkPanId=0xFFFF,
    nwkState=t.NwkState.NWK_INIT,
    channelList=t.Channels.NO_CHANNELS,
    beaconOrder=15,
    superFrameOrder=15,
    scanDuration=0,
    battLifeExt=0,
    allocatedRouterAddresses=0,
    allocatedEndDeviceAddresses=0,
    nodeDepth=0,
    extendedPANID=t.EUI64.convert("00:00:00:00:00:00:00:00"),
    nwkKeyLoaded=False,
    spare1=t.NwkKeyDesc(
        KeySeqNum=0, Key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    ),
    spare2=t.NwkKeyDesc(
        KeySeqNum=0, Key=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    ),
    spare3=0,
    spare4=0,
    nwkLinkStatusPeriod=60,
    nwkRouterAgeLimit=3,
    nwkUseMultiCast=False,
    nwkIsConcentrator=True,
    nwkConcentratorDiscoveryTime=120,
    nwkConcentratorRadius=10,
    nwkAllFresh=1,
    nwkManagerAddr=0x0000,
    nwkTotalTransmissions=0,
    nwkUpdateId=0,
)

Z2M_PAN_ID = 0xA162
Z2M_EXT_PAN_ID = t.EUI64.convert("DD:DD:DD:DD:DD:DD:DD:DD")
Z2M_NETWORK_KEY = t.KeyData([1, 3, 5, 7, 9, 11, 13, 15, 0, 2, 4, 6, 8, 10, 12, 13])

DEFAULT_TC_LINK_KEY = t.TCLinkKey(
    ExtAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),  # global
    Key=t.KeyData(b"ZigBeeAlliance09"),
    TxFrameCounter=0,
    RxFrameCounter=0,
)
ZSTACK_CONFIGURE_SUCCESS = t.uint8_t(0x55)

EMPTY_ADDR_MGR_ENTRY = t.AddrMgrEntry(
    type=t.AddrMgrUserType(0xFF),
    nwkAddr=0xFFFF,
    extAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),
)
