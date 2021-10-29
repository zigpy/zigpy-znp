import zigpy_znp.types as t

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

EMPTY_KEY = t.NwkKeyDesc(
    KeySeqNum=0x00,
    Key=t.KeyData([0x00] * 16),
)

# Used only when creating a temporary network during formation
STARTUP_CHANNELS = t.Channels.from_channel_list([15, 20, 25])
