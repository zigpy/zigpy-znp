import enum
import typing
import logging

import attr
from zigpy.types import EUI64, NWK, ExtendedPanId, PanId

from . import basic, struct


LOGGER = logging.getLogger(__name__)


class ADCChannel(basic.enum_uint8, enum.IntEnum):
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


class ADCResolution(basic.enum_uint8, enum.IntEnum):
    """Resolution of the ADC channel."""

    bits_8 = 0x00
    bits_10 = 0x01
    bits_12 = 0x02
    bits_14 = 0x03


class GpioOperation(basic.enum_uint8, enum.IntEnum):
    """Specifies the type of operation to perform on the GPIO pins."""

    SetDirection = 0x00
    SetInputMode = 0x01
    Set = 0x02
    Clear = 0x03
    Toggle = 0x04
    Read = 0x05


class StackTuneOperation(basic.enum_uint8, enum.IntEnum):
    """The tuning operation to be executed."""

    PowerLevel = 0x00  # XXX: [Value] should correspond to the valid values
    # specified by the ZMacTransmitPower_t
    # enumeration (0xFD – 0x16)

    SetRxOnWhenIdle = 0x01  # Set RxOnWhenIdle off/on if the value of Value is 0/1;
    # otherwise return the 0x01 current setting of RxOnWhenIdle.


class AddrMode(basic.uint8_t, enum.Enum):
    """Address mode."""

    NOT_PRESENT = 0x00
    Group = 0x01
    NWK = 0x02
    IEEE = 0x03

    Broadcast = 0x0F


@attr.s
class AddrModeAddress(struct.Struct):
    mode: AddrMode = attr.ib(converter=struct.Struct.converter(AddrMode))
    address: typing.Union[EUI64, NWK] = attr.ib()

    @classmethod
    def deserialize(cls, data: bytes):
        """Deserialize data."""
        mode, data = AddrMode.deserialize(data)
        if mode == AddrMode.NWK:
            # a value of 2 indicates 2-byte (16-bit) address mode,
            # using only the 2 LSB’s of the DstAddr field to form
            # a 2-byte short address.
            addr64, data = basic.uint64_t.deserialize(data)
            addr = NWK(addr64 & 0xFFFF)
        elif mode == AddrMode.IEEE:
            addr, data = EUI64.deserialize(data)
        else:
            raise ValueError(f"Unknown address mode: {mode}")

        return cls(mode=mode, address=addr), data

    def serialize(self):
        if self.mode == AddrMode.NWK:
            return self.mode.serialize() + basic.uint64_t(self.address).serialize()
        elif self.mode == AddrMode.IEEE:
            return self.mode.serialize() + self.address.serialize()
        else:
            raise ValueError(f"Unknown address mode: {self.mode}")  # pragma: no cover


class BDBCommissioningMode(basic.enum_uint8, enum.IntEnum):
    """Commissioning mode."""

    Initialization = 0x00
    TouchLink = 0x01
    NetworkSteering = 0x02
    NetworkFormation = 0x04
    FindingAndBinding = 0x08


@attr.s
class Beacon(struct.Struct):
    """Beacon message."""

    Src = attr.ib(type=NWK, converter=NWK)
    PanId = attr.ib(type=PanId, converter=PanId)
    Channel = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    PermitJoining = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    RouterCapacity = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    DeviceCapacity = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    ProtocolVersion = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    StackProfile = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    LQI = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    Depth = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    UpdateId = attr.ib(type=basic.uint8_t, converter=basic.uint8_t)
    ExtendedPanId = attr.ib(type=ExtendedPanId, converter=ExtendedPanId)


class GroupId(basic.HexRepr, basic.uint16_t):
    """"Group ID class"""

    pass


class ScanType(basic.enum_uint8, enum.IntEnum):
    EnergyDetect = 0x00
    Active = 0x01
    Passive = 0x02
    Orphan = 0x03


@attr.s(frozen=True)
class Schema:
    """List of Parameters."""

    parameters = attr.ib(factory=tuple, converter=tuple)


class MissingEnumMixin:
    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, int) or value < 0 or value > 0xFF:
            # `return None` works with Python 3.7.7, breaks with 3.7.1
            raise ValueError("%r is not a valid %r", value, cls.__name__)

        # XXX: infer type from enum
        new_member = basic.uint8_t.__new__(cls, value)
        new_member._name_ = f"unknown_0x{value:02X}"
        new_member._value_ = value

        LOGGER.warning("Unhandled %s value: %s", cls.__name__, new_member)

        return new_member


class Status(basic.uint8_t, MissingEnumMixin, enum.Enum):
    Success = 0x00
    Failure = 0x01
    InvalidParameter = 0x02
    ItemCreated = 0x09
    ItemNotCreated = 0x0A
    BadLength = 0x0C
    MemoryFailure = 0x10
    TableFull = 0x11
    MACNoResource = 0x1A
    InvalidRequest = 0xC2

    NwkTableFull = 0xC7
    NwkNoRoute = 0xCD

    MacChannelAccessFailure = 0xE1

    UnknownDevice = 0xC8
    ZMACInvalidParameter = 0xE8
    ZMACNoBeacon = 0xEA
    MACScanInProgress = 0xFC


@attr.s(frozen=True)
class Param:
    """Parameter."""

    name = attr.ib(converter=str)
    type = attr.ib()
    description = attr.ib(default="")


class ResetReason(basic.enum_uint8, enum.IntEnum):
    PowerUp = 0x00
    External = 0x01
    Watchdog = 0x02


class ResetType(basic.enum_uint8, enum.IntEnum):
    Hard = 0x00
    Soft = 0x01


class KeySource(basic.FixedList):
    _length = 8
    _itemtype = basic.uint8_t


class StartupOptions(basic.enum_uint8, enum.IntFlag):
    ClearConfig = 1 << 1
    ClearState = 1 << 2
    AutoStart = 1 << 3


class DeviceLogicalType(basic.enum_uint8, enum.IntFlag):
    Coordinator = 1 << 0
    Router = 1 << 1
    EndDevice = 1 << 2
