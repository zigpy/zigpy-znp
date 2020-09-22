import zigpy_znp.types as t


class BaseNvIds(t.enum_uint16):
    pass


class ZclPortNvIds(BaseNvIds):
    # ZCL Port NV IDs (Application Layer NV Items)
    SCENE_TABLE = 0x0001
    PROXY_TABLE = 0x0002
    SINK_TABLE = 0x0003


class OsalExNvIds(BaseNvIds):
    # OSAL NV Item IDs
    LEGACY = 0x0000
    ADDRMGR = 0x0001
    BINDING_TABLE = 0x0002
    DEVICE_LIST = 0x0003
    TCLK_TABLE = 0x0004
    TCLK_IC_TABLE = 0x0005
    APS_KEY_DATA_TABLE = 0x0006
    NWK_SEC_MATERIAL_TABLE = 0x0007


class NwkNvIds(BaseNvIds):
    # Introduced by zigbeer/zigbee-shepherd and now used by Zigbee2MQTT
    HAS_CONFIGURED_ZSTACK1 = 0x0F00
    HAS_CONFIGURED_ZSTACK3 = 0x0060

    # OSAL NV item IDs
    EXTADDR = 0x0001
    BOOTCOUNTER = 0x0002
    STARTUP_OPTION = 0x0003
    START_DELAY = 0x0004

    # NWK Layer NV item IDs
    NIB = 0x0021
    DEVICE_LIST = 0x0022
    ADDRMGR = 0x0023
    POLL_RATE_OLD16 = 0x0024  # Deprecated when poll rate changed from 16 to 32 bits
    POLL_RATE = 0x0035

    DATA_RETRIES = 0x0028
    POLL_FAILURE_RETRIES = 0x0029
    STACK_PROFILE = 0x002A
    INDIRECT_MSG_TIMEOUT = 0x002B
    ROUTE_EXPIRY_TIME = 0x002C
    EXTENDED_PAN_ID = 0x002D
    BCAST_RETRIES = 0x002E
    PASSIVE_ACK_TIMEOUT = 0x002F
    BCAST_DELIVERY_TIME = 0x0030
    # NWK_MODE                   = 0x0031  #Deprecated, as this will always be Mesh
    CONCENTRATOR_ENABLE = 0x0032
    CONCENTRATOR_DISCOVERY = 0x0033

    CONCENTRATOR_RADIUS_OLD16 = 0x0034
    CONCENTRATOR_RADIUS = 0x0035  # used above for new 32 bit Poll Rate

    CONCENTRATOR_RC = 0x0036
    NWK_MGR_MODE = 0x0037
    SRC_RTG_EXPIRY_TIME = 0x0038
    ROUTE_DISCOVERY_TIME = 0x0039
    NWK_ACTIVE_KEY_INFO = 0x003A
    NWK_ALTERN_KEY_INFO = 0x003B
    ROUTER_OFF_ASSOC_CLEANUP = 0x003C
    NWK_LEAVE_REQ_ALLOWED = 0x003D
    NWK_CHILD_AGE_ENABLE = 0x003E
    DEVICE_LIST_KA_TIMEOUT = 0x003F

    # APS Layer NV item IDs
    BINDING_TABLE = 0x0041
    GROUP_TABLE = 0x0042
    APS_FRAME_RETRIES = 0x0043
    APS_ACK_WAIT_DURATION = 0x0044
    APS_ACK_WAIT_MULTIPLIER = 0x0045
    BINDING_TIME = 0x0046
    APS_USE_EXT_PANID = 0x0047
    APS_USE_INSECURE_JOIN = 0x0048
    COMMISSIONED_NWK_ADDR = 0x0049

    APS_NONMEMBER_RADIUS = 0x004B  # Multicast non_member radius
    APS_LINK_KEY_TABLE = 0x004C
    APS_DUPREJ_TIMEOUT_INC = 0x004D
    APS_DUPREJ_TIMEOUT_COUNT = 0x004E
    APS_DUPREJ_TABLE_SIZE = 0x004F

    # System statistics and metrics NV ID
    DIAGNOSTIC_STATS = 0x0050

    # Additional NWK Layer NV item IDs
    NWK_PARENT_INFO = 0x0051
    NWK_ENDDEV_TIMEOUT_DEF = 0x0052
    END_DEV_TIMEOUT_VALUE = 0x0053
    END_DEV_CONFIGURATION = 0x0054

    BDBNODEISONANETWORK = 0x0055  # bdbNodeIsOnANetwork attribute
    BDBREPORTINGCONFIG = 0x0056

    # Security NV Item IDs
    SECURITY_LEVEL = 0x0061
    PRECFGKEY = 0x0062
    PRECFGKEYS_ENABLE = 0x0063
    # Deprecated Item as there is only one security mode supported now Z3.0
    # SECURITY_MODE = 0x0064
    SECURE_PERMIT_JOIN = 0x0065
    APS_LINK_KEY_TYPE = 0x0066
    APS_ALLOW_R19_SECURITY = 0x0067
    DISTRIBUTED_KEY = 0x0068  # Default distributed nwk key Id. Nv ID not in use

    IMPLICIT_CERTIFICATE = 0x0069
    DEVICE_PRIVATE_KEY = 0x006A
    CA_PUBLIC_KEY = 0x006B
    KE_MAX_DEVICES = 0x006C

    USE_DEFAULT_TCLK = 0x006D
    # deprecated: TRUSTCENTER_ADDR (16-bit)   0x006E
    RNG_COUNTER = 0x006F
    RANDOM_SEED = 0x0070
    TRUSTCENTER_ADDR = 0x0071

    CERT_283 = 0x0072
    PRIVATE_KEY_283 = 0x0073
    PUBLIC_KEY_283 = 0x0074

    LEGACY_NWK_SEC_MATERIAL_TABLE_START = 0x0075
    LEGACY_NWK_SEC_MATERIAL_TABLE_END = 0x0080

    # ZDO NV Item IDs
    USERDESC = 0x0081
    NWKKEY = 0x0082
    PANID = 0x0083
    CHANLIST = 0x0084
    LEAVE_CTRL = 0x0085
    SCAN_DURATION = 0x0086
    LOGICAL_TYPE = 0x0087
    NWKMGR_MIN_TX = 0x0088
    NWKMGR_ADDR = 0x0089

    ZDO_DIRECT_CB = 0x008F

    # ZCL NV item IDs
    SCENE_TABLE = 0x0091
    MIN_FREE_NWK_ADDR = 0x0092
    MAX_FREE_NWK_ADDR = 0x0093
    MIN_FREE_GRP_ID = 0x0094
    MAX_FREE_GRP_ID = 0x0095
    MIN_GRP_IDS = 0x0096
    MAX_GRP_IDS = 0x0097
    OTA_BLOCK_REQ_DELAY = 0x0098

    # Non-standard NV item IDs
    SAPI_ENDPOINT = 0x00A1

    # NV Items Reserved for Commissioning Cluster Startup Attribute Set (SAS):
    # 0x00B1 - 0x00BF: Parameters related to APS and NWK layers
    # 0x00C1 - 0x00CF: Parameters related to Security
    # 0x00D1 - 0x00DF: Current key parameters
    SAS_SHORT_ADDR = 0x00B1
    SAS_EXT_PANID = 0x00B2
    SAS_PANID = 0x00B3
    SAS_CHANNEL_MASK = 0x00B4
    SAS_PROTOCOL_VER = 0x00B5
    SAS_STACK_PROFILE = 0x00B6
    SAS_STARTUP_CTRL = 0x00B7

    SAS_TC_ADDR = 0x00C1
    SAS_TC_MASTER_KEY = 0x00C2
    SAS_NWK_KEY = 0x00C3
    SAS_USE_INSEC_JOIN = 0x00C4
    SAS_PRECFG_LINK_KEY = 0x00C5
    SAS_NWK_KEY_SEQ_NUM = 0x00C6
    SAS_NWK_KEY_TYPE = 0x00C7
    SAS_NWK_MGR_ADDR = 0x00C8

    SAS_CURR_TC_MASTER_KEY = 0x00D1
    SAS_CURR_NWK_KEY = 0x00D2
    SAS_CURR_PRECFG_LINK_KEY = 0x00D3

    USE_NVOCMP = 0x00FF

    # NV Items Reserved for Trust Center Link Key Table entries
    # 0x0101 - 0x01FF
    TCLK_SEED = 0x0101  # Seed
    TCLK_JOIN_DEV = (
        0x0102  # Nv Id where Joining device store their APS key. Key is in plain text.
    )
    TCLK_DEFAULT = 0x0103  # Not accually a Nv Item but Id used by SecMgr

    LEGACY_TCLK_IC_TABLE_START = 0x0104  # Deprecated. Refer to EX_TCLK_IC_TABLE
    LEGACY_TCLK_IC_TABLE_END = 0x0110  # IC keys, refered with shift byte

    LEGACY_TCLK_TABLE_START = 0x0111  # Deprecated. Refer to EX_TCLK_TABLE
    LEGACY_TCLK_TABLE_END = 0x01FF

    # NV Items Reserved for APS Link Key Table entries
    # 0x0201 - 0x02FF
    LEGACY_APS_LINK_KEY_DATA_START = 0x0201  # Deprecated. Refer to EX_APS_KEY_TABLE
    LEGACY_APS_LINK_KEY_DATA_END = 0x02FF

    # NV items used to duplicate system elements
    DUPLICATE_BINDING_TABLE = 0x0300
    DUPLICATE_DEVICE_LIST = 0x0301
    DUPLICATE_DEVICE_LIST_KA_TIMEOUT = 0x0302

    # NV Items Reserved for Proxy Table entries
    # 0x0310 - 0x031F
    LEGACY_PROXY_TABLE_START = 0x0310  # Deprecated. Refer to EX_GP_PROXY_TABLE
    LEGACY_PROXY_TABLE_END = 0x031F

    # NV Items Reserved for Sink Table entries
    # 0x0320 - 0x032F
    LEGACY_SINK_TABLE_START = 0x0320  # Deprecated. Refer to EX_GP_SINK_TABLE
    LEGACY_SINK_TABLE_END = 0x032F

    INVALID_INDEX = 0xFFFF


def is_secure_nvid(nvid: NwkNvIds) -> bool:
    """
    Returns whether or not an nvid may be prevented from being read from NVRAM.
    """

    if nvid in (
        NwkNvIds.IMPLICIT_CERTIFICATE,
        NwkNvIds.CA_PUBLIC_KEY,
        NwkNvIds.DEVICE_PRIVATE_KEY,
        NwkNvIds.NWK_ACTIVE_KEY_INFO,
        NwkNvIds.NWK_ALTERN_KEY_INFO,
        NwkNvIds.PRECFGKEY,
        NwkNvIds.TCLK_SEED,
    ):
        return True

    if NwkNvIds.LEGACY_TCLK_TABLE_START <= nvid <= NwkNvIds.LEGACY_TCLK_TABLE_END:
        return True

    if (
        NwkNvIds.LEGACY_APS_LINK_KEY_DATA_START
        <= nvid
        <= NwkNvIds.LEGACY_APS_LINK_KEY_DATA_END
    ):
        return True

    return False
