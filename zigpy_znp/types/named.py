import sys
import typing
import logging
import dataclasses

from zigpy.types import NWK, EUI64, PanId, KeyData, ClusterId, ExtendedPanId

from . import basic, struct

LOGGER = logging.getLogger(__name__)


class ADCChannel(basic.enum_uint8):
    """The ADC channel."""

    AIN0 = 0x00
    AIN1 = 0x01
    AIN2 = 0x02
    AIN3 = 0x03
    AIN4 = 0x04
    AIN5 = 0x05
    AIN6 = 0x06
    AIN7 = 0x07
    Temperature = 0x0E
    Voltage = 0x0F


class ADCResolution(basic.enum_uint8):
    """Resolution of the ADC channel."""

    bits_8 = 0x00
    bits_10 = 0x01
    bits_12 = 0x02
    bits_14 = 0x03


class GpioOperation(basic.enum_uint8):
    """Specifies the type of operation to perform on the GPIO pins."""

    SetDirection = 0x00
    SetInputMode = 0x01
    Set = 0x02
    Clear = 0x03
    Toggle = 0x04
    Read = 0x05


class StackTuneOperation(basic.enum_uint8):
    """The tuning operation to be executed."""

    PowerLevel = 0x00  # XXX: [Value] should correspond to the valid values
    # specified by the ZMacTransmitPower_t
    # enumeration (0xFD - 0x16)

    SetRxOnWhenIdle = 0x01  # Set RxOnWhenIdle off/on if the value of Value is 0/1;
    # otherwise return the 0x01 current setting of RxOnWhenIdle.


class AddrMode(basic.enum_uint8):
    """Address mode."""

    NOT_PRESENT = 0x00
    Group = 0x01
    NWK = 0x02
    IEEE = 0x03

    Broadcast = 0x0F


class AddrModeAddress(struct.Struct):
    mode: AddrMode
    address: typing.Union[NWK, EUI64] = struct.StructField(
        dynamic_type=lambda s: {
            AddrMode.NWK: NWK,
            AddrMode.Group: NWK,
            AddrMode.Broadcast: NWK,
            AddrMode.IEEE: EUI64,
        }[s.mode]
    )

    @classmethod
    def deserialize(cls, data: bytes) -> "AddrModeAddress":
        addr, data = super().deserialize(data)

        if isinstance(addr.address, NWK):
            # The address is padded
            data = data[6:]

        return addr, data

    def serialize(self) -> bytes:
        data = super().serialize()

        if isinstance(self.address, NWK):
            data += b"\x00\x00\x00\x00\x00\x00"

        return data


class Beacon(struct.Struct):
    """Beacon message."""

    Src: NWK
    PanId: PanId
    Channel: basic.uint8_t
    PermitJoining: basic.uint8_t
    RouterCapacity: basic.uint8_t
    DeviceCapacity: basic.uint8_t
    ProtocolVersion: basic.uint8_t
    StackProfile: basic.uint8_t
    LQI: basic.uint8_t
    Depth: basic.uint8_t
    UpdateId: basic.uint8_t
    ExtendedPanId: ExtendedPanId


class GroupId(basic.uint16_t, hex_repr=True):
    """"Group ID class"""

    pass


class ScanType(basic.enum_uint8):
    EnergyDetect = 0x00
    Active = 0x01
    Passive = 0x02
    Orphan = 0x03


@dataclasses.dataclass(frozen=True)
class Param:
    """Schema parameter"""

    name: str
    type: typing.Any = None
    description: str = ""
    optional: bool = False


class MissingEnumMixin:
    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, int):
            raise ValueError(f"{value} is not a valid {cls.__name__}")

        new_member = cls._member_type_.__new__(cls, value)
        new_member._name_ = f"unknown_0x{value:02X}"
        new_member._value_ = cls._member_type_(value)

        if sys.version_info >= (3, 8):
            # Show the warning in the calling code, not in this function
            LOGGER.warning(
                "Unhandled %s value: %s", cls.__name__, new_member, stacklevel=2
            )
        else:
            LOGGER.warning("Unhandled %s value: %s", cls.__name__, new_member)

        return new_member


class Status(MissingEnumMixin, basic.enum_uint8):
    SUCCESS = 0x00
    FAILURE = 0x01
    INVALID_PARAMETER = 0x02
    INVALID_TASK = 0x03
    MSG_BUFFER_NOT_AVAIL = 0x04
    INVALID_MSG_POINTER = 0x05
    INVALID_EVENT_ID = 0x06
    INVALID_INTERRUPT_ID = 0x07
    NO_TIMER_AVAIL = 0x08
    NV_ITEM_UNINIT = 0x09
    NV_OPER_FAILED = 0x0A
    INVALID_MEM_SIZE = 0x0B
    NV_BAD_ITEM_LEN = 0x0C

    MEM_ERROR = 0x10
    BUFFER_FULL = 0x11
    UNSUPPORTED_MODE = 0x12
    MAC_MEM_ERROR = 0x13

    SAPI_IN_PROGRESS = 0x20
    SAPI_TIMEOUT = 0x21
    SAPI_INIT = 0x22

    NOT_AUTHORIZED = 0x7E

    MALFORMED_CMD = 0x80
    UNSUP_CLUSTER_CMD = 0x81

    OTA_ABORT = 0x95
    OTA_IMAGE_INVALID = 0x96
    OTA_WAIT_FOR_DATA = 0x97
    OTA_NO_IMAGE_AVAILABLE = 0x98
    OTA_REQUIRE_MORE_IMAGE = 0x99

    APS_FAIL = 0xB1
    APS_TABLE_FULL = 0xB2
    APS_ILLEGAL_REQUEST = 0xB3
    APS_INVALID_BINDING = 0xB4
    APS_UNSUPPORTED_ATTRIB = 0xB5
    APS_NOT_SUPPORTED = 0xB6
    APS_NO_ACK = 0xB7
    APS_DUPLICATE_ENTRY = 0xB8
    APS_NO_BOUND_DEVICE = 0xB9
    APS_NOT_ALLOWED = 0xBA
    APS_NOT_AUTHENTICATED = 0xBB

    SEC_NO_KEY = 0xA1
    SEC_OLD_FRM_COUNT = 0xA2
    SEC_MAX_FRM_COUNT = 0xA3
    SEC_CCM_FAIL = 0xA4
    SEC_FAILURE = 0xAD

    NWK_INVALID_PARAM = 0xC1
    NWK_INVALID_REQUEST = 0xC2
    NWK_NOT_PERMITTED = 0xC3
    NWK_STARTUP_FAILURE = 0xC4
    NWK_ALREADY_PRESENT = 0xC5
    NWK_SYNC_FAILURE = 0xC6
    NWK_TABLE_FULL = 0xC7
    NWK_UNKNOWN_DEVICE = 0xC8
    NWK_UNSUPPORTED_ATTRIBUTE = 0xC9
    NWK_NO_NETWORKS = 0xCA
    NWK_LEAVE_UNCONFIRMED = 0xCB
    NWK_NO_ACK = 0xCC  # not in spec
    NWK_NO_ROUTE = 0xCD

    MAC_BEACON_LOSS = 0xE0
    MAC_CHANNEL_ACCESS_FAILURE = 0xE1
    MAC_DENIED = 0xE2
    MAC_DISABLE_TRX_FAILURE = 0xE3
    MAC_FAILED_SECURITY_CHECK = 0xE4
    MAC_FRAME_TOO_LONG = 0xE5
    MAC_INVALID_GTS = 0xE6
    MAC_INVALID_HANDLE = 0xE7
    MAC_INVALID_PARAMETER = 0xE8
    MAC_NO_ACK = 0xE9
    MAC_NO_BEACON = 0xEA
    MAC_NO_DATA = 0xEB
    MAC_NO_SHORT_ADDR = 0xEC
    MAC_OUT_OF_CAP = 0xED
    MAC_PANIDCONFLICT = 0xEE
    MAC_REALIGNMENT = 0xEF

    MAC_TRANSACTION_EXPIRED = 0xF0
    MAC_TRANSACTION_OVER_FLOW = 0xF1
    MAC_TX_ACTIVE = 0xF2
    MAC_UN_AVAILABLE_KEY = 0xF3
    MAC_UNSUPPORTED_ATTRIBUTE = 0xF4
    MAC_UNSUPPORTED = 0xF5
    MAC_SRC_MATCH_INVALID_INDEX = 0xFF


class ResetReason(basic.enum_uint8):
    PowerUp = 0x00
    External = 0x01
    Watchdog = 0x02


class ResetType(basic.enum_uint8):
    Hard = 0x00
    Soft = 0x01


class KeySource(basic.FixedList, item_type=basic.uint8_t, length=8):
    pass


class StartupOptions(basic.enum_flag_uint8):
    ClearConfig = 1 << 0
    ClearState = 1 << 1
    AutoStart = 1 << 2

    # FrameCounter should persist across factory resets.
    # This should not be used as part of FN reset procedure.
    # Set to reset the FrameCounter of all Nwk Security Material
    ClearNwkFrameCounter = 1 << 7


class DeviceLogicalType(basic.enum_uint8):
    Coordinator = 0
    Router = 1
    EndDevice = 2


class DeviceTypeCapabilities(basic.enum_flag_uint8):
    Coordinator = 1 << 0
    Router = 1 << 1
    EndDevice = 1 << 2


class ClusterIdList(basic.LVList, item_type=ClusterId, length_type=basic.uint8_t):
    pass


class NWKList(basic.LVList, item_type=NWK, length_type=basic.uint8_t):
    pass


class TCLinkKey(struct.Struct):
    ExtAddr: EUI64
    Key: KeyData
    TxFrameCounter: basic.uint32_t
    RxFrameCounter: basic.uint32_t
