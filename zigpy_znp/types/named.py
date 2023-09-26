from __future__ import annotations

import enum
import typing
import logging
import dataclasses

import zigpy.types
from zigpy.zdo.types import Status as ZDOStatus  # noqa: F401

from . import basic, zigpy_types

LOGGER = logging.getLogger(__name__)

JSONType = typing.Dict[str, typing.Any]


class AddrMode(basic.enum8):
    """Address mode."""

    _missing_ = enum.Enum._missing_  # There are no missing members

    NOT_PRESENT = 0x00
    Group = 0x01
    NWK = 0x02
    IEEE = 0x03

    Broadcast = 0x0F


class AddrModeAddress:
    def __new__(cls, mode=None, address=None):
        if mode is not None and address is None and isinstance(mode, cls):
            other = mode
            return cls(mode=other.mode, address=other.address)

        instance = super().__new__(cls)

        if mode is not None and mode == AddrMode.NOT_PRESENT:
            raise ValueError(f"Invalid address mode: {mode}")

        instance.mode = None if mode is None else AddrMode(mode)
        instance.address = (
            None if address is None else instance._get_address_type()(address)
        )

        return instance

    @classmethod
    def from_zigpy_type(
        cls, zigpy_addr: zigpy.types.AddrModeAddress
    ) -> AddrModeAddress:
        return cls(
            mode=AddrMode[zigpy_addr.addr_mode.name],
            address=zigpy_addr.address,
        )

    def as_zigpy_type(self) -> zigpy.types.AddrModeAddress:
        return zigpy.types.AddrModeAddress(
            addr_mode=zigpy.types.AddrMode[self.mode.name],
            address=self.address,
        )

    def _get_address_type(self):
        return {
            AddrMode.NWK: zigpy_types.NWK,
            AddrMode.Group: zigpy_types.NWK,
            AddrMode.Broadcast: zigpy_types.NWK,
            AddrMode.IEEE: zigpy_types.EUI64,
        }[self.mode]

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[AddrModeAddress, bytes]:
        mode, data = AddrMode.deserialize(data)
        address, data = zigpy_types.EUI64.deserialize(data)

        if mode != AddrMode.IEEE:
            address, _ = zigpy_types.NWK.deserialize(address.serialize())

        return cls(mode=mode, address=address), data

    def serialize(self) -> bytes:
        result = (
            self.mode.serialize() + self._get_address_type()(self.address).serialize()
        )

        if self.mode != AddrMode.IEEE:
            result += b"\x00\x00\x00\x00\x00\x00"

        return result

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented

        return self.mode == other.mode and self.address == other.address

    def __repr__(self) -> str:
        return f"{type(self).__name__}(mode={self.mode!r}, address={self.address!r})"


class GroupId(basic.uint16_t, repr="hex"):  # type: ignore[call-arg]
    """Group ID class"""


class ScanType(basic.enum8):
    EnergyDetect = 0x00
    Active = 0x01
    Passive = 0x02
    Orphan = 0x03


@dataclasses.dataclass(frozen=True)
class Param:
    """Schema parameter"""

    name: str
    type: type = None
    description: str = ""
    optional: bool = False


class Status(basic.enum8):
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

    # The operation is not supported in the current configuration
    MAC_UNSUPPORTED = 0x18

    # The operation could not be performed in the current state
    MAC_BAD_STATE = 0x19

    # The operation could not be completed because no memory resources were available
    MAC_NO_RESOURCES = 0x1A

    # For internal use only
    MAC_ACK_PENDING = 0x1B

    # For internal use only
    MAC_NO_TIME = 0x1C

    # For internal use only
    MAC_TX_ABORTED = 0x1D

    # For internal use only - A duplicated entry is added to the source matching table
    MAC_DUPLICATED_ENTRY = 0x1E

    # The frame counter puportedly applied by the originator of the received frame
    # is invalid
    MAC_COUNTER_ERROR = 0xDB

    # The key purportedly applied by the originator of the received frame is not allowed
    MAC_IMPROPER_KEY_TYPE = 0xDC

    # The security level purportedly applied by the originator of the received frame
    # does not meet the minimum security level
    MAC_IMPROPER_SECURITY_LEVEL = 0xDD

    # The received frame was secured with legacy security which is not supported
    MAC_UNSUPPORTED_LEGACY = 0xDE

    # The security of the received frame is not supported
    MAC_UNSUPPORTED_SECURITY = 0xDF

    # The beacon was lost following a synchronization request
    MAC_BEACON_LOSS = 0xE0

    # The operation or data request failed because of activity on the channel
    MAC_CHANNEL_ACCESS_FAILURE = 0xE1

    # The MAC was not able to enter low power mode.
    MAC_DENIED = 0xE2

    # Unused
    MAC_DISABLE_TRX_FAILURE = 0xE3

    # Cryptographic processing of the secure frame failed
    MAC_SECURITY_ERROR = 0xE4

    # The received frame or frame resulting from an operation or data request is
    # too long to be processed by the MAC
    MAC_FRAME_TOO_LONG = 0xE5

    # Unused
    MAC_INVALID_GTS = 0xE6

    # The purge request contained an invalid handle
    MAC_INVALID_HANDLE = 0xE7

    # The API function parameter is out of range
    MAC_INVALID_PARAMETER = 0xE8

    # The operation or data request failed because no acknowledgement was received
    MAC_NO_ACK = 0xE9

    # The scan request failed because no beacons were received or the orphan scan failed
    # because no coordinator realignment was received
    MAC_NO_BEACON = 0xEA

    # The associate request failed because no associate response was received or the
    # poll request did not return any data
    MAC_NO_DATA = 0xEB

    # The short address parameter of the start request was invalid
    MAC_NO_SHORT_ADDRESS = 0xEC

    # Unused
    MAC_OUT_OF_CAP = 0xED

    # A PAN identifier conflict has been detected and communicated to the PAN
    # coordinator
    MAC_PAN_ID_CONFLICT = 0xEE

    # A coordinator realignment command has been received
    MAC_REALIGNMENT = 0xEF

    # The associate response, disassociate request, or indirect data transmission failed
    # because the peer device did not respond before the transaction expired or was
    # purged
    MAC_TRANSACTION_EXPIRED = 0xF0

    # The request failed because MAC data buffers are full
    MAC_TRANSACTION_OVERFLOW = 0xF1

    # Unused
    MAC_TX_ACTIVE = 0xF2

    # The operation or data request failed because the security key is not available
    MAC_UNAVAILABLE_KEY = 0xF3

    # The set or get request failed because the attribute is not supported
    MAC_UNSUPPORTED_ATTRIBUTE = 0xF4

    # The data request failed because neither the source address nor destination address
    # parameters were present
    MAC_INVALID_ADDRESS = 0xF5

    # Unused
    MAC_ON_TIME_TOO_LONG = 0xF6

    # Unused
    MAC_PAST_TIME = 0xF7

    # The start request failed because the device is not tracking the beacon of its
    # coordinator
    MAC_TRACKING_OFF = 0xF8

    # Unused
    MAC_INVALID_INDEX = 0xF9

    # The scan terminated because the PAN descriptor storage limit was reached
    MAC_LIMIT_REACHED = 0xFA

    # A set request was issued with a read-only identifier
    MAC_READ_ONLY = 0xFB

    # The scan request failed because a scan is already in progress
    MAC_SCAN_IN_PROGRESS = 0xFC

    # The beacon start time overlapped the coordinator transmission time
    MAC_SUPERFRAME_OVERLAP = 0xFD

    # The AUTOPEND pending all is turned on
    MAC_AUTOACK_PENDING_ALL_ON = 0xFE

    # The AUTOPEND pending all is turned off
    MAC_AUTOACK_PENDING_ALL_OFF = 0xFF


class ResetReason(basic.enum8):
    PowerUp = 0x00
    External = 0x01
    Watchdog = 0x02


class ResetType(basic.enum8):
    Hard = 0x00
    Soft = 0x01
    Shutdown = 0x02


class KeySource(basic.FixedList, item_type=basic.uint8_t, length=8):
    pass


class StartupOptions(basic.bitmap8):
    NONE = 0

    ClearConfig = 1 << 0
    ClearState = 1 << 1
    AutoStart = 1 << 2

    # FrameCounter should persist across factory resets.
    # This should not be used as part of FN reset procedure.
    # Set to reset the FrameCounter of all Nwk Security Material
    ClearNwkFrameCounter = 1 << 7


class DeviceLogicalType(basic.enum8):
    Coordinator = 0
    Router = 1
    EndDevice = 2


class DeviceTypeCapabilities(basic.bitmap8):
    Coordinator = 1 << 0
    Router = 1 << 1
    EndDevice = 1 << 2


class ClusterIdList(
    basic.LVList, item_type=zigpy_types.ClusterId, length_type=basic.uint8_t
):
    pass


class NWKList(basic.LVList, item_type=zigpy_types.NWK, length_type=basic.uint8_t):
    pass


class NwkMode(basic.enum8):
    Star = 0
    Tree = 1
    Mesh = 2
