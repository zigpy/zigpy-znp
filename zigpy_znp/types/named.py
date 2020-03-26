import enum
import typing

import attr
from zigpy.types import EUI64, NWK, ExtendedPanId, PanId

from . import basic, struct


class _EnumEq:
    def __eq__(self, other):
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)


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


class AddrMode(basic.uint8_t, enum.Enum):
    """Address mode."""

    NOT_PRESENT = 0x00
    Group = 0x01
    NWK = 0x02
    IEEE = 0x03
    Broadcast = 0xFF


@attr.s
class AddrModeAddress(struct.Struct):
    mode: AddrMode = attr.ib(converter=struct.Struct.converter(AddrMode))
    address: typing.Union[EUI64, NWK] = attr.ib()

    @classmethod
    def deserialize(cls, data: bytes):
        """Deserialize data."""
        mode, data = AddrMode.deserialize(data)
        if mode == AddrMode.NWK:
            addr, data = basic.uint64_t.deserialize(data)
            addr = basic.uint64_t(addr & 0xFFFF)
        elif mode == AddrMode.IEEE:
            addr, data = EUI64.deserialize(data)
        return cls(mode=mode, address=addr), data


class BDBCommissioningMode(basic.enum_uint8, enum.IntEnum):
    """Commissioning mode."""

    Initialization = 0x00
    TouchLink = 0x01
    NetworkSteering = 0x02
    NetworkFormation = 0x04
    FindingAndBinding = 0x08


class Channels(basic.enum_uint32, enum.IntFlag):
    """Zigbee Channels."""

    NO_CHANNELS = 0x00000000
    ALL_CHANNELS = 0x07FFF800
    CHANNEL_11 = 0x00000800
    CHANNEL_12 = 0x00001000
    CHANNEL_13 = 0x00002000
    CHANNEL_14 = 0x00004000
    CHANNEL_15 = 0x00008000
    CHANNEL_16 = 0x00010000
    CHANNEL_17 = 0x00020000
    CHANNEL_18 = 0x00040000
    CHANNEL_19 = 0x00080000
    CHANNEL_20 = 0x00100000
    CHANNEL_21 = 0x00200000
    CHANNEL_22 = 0x00400000
    CHANNEL_23 = 0x00800000
    CHANNEL_24 = 0x01000000
    CHANNEL_25 = 0x02000000
    CHANNEL_26 = 0x04000000

    @classmethod
    def from_channel_list(cls, channels: typing.Iterable[int]) -> "Channels":
        mask = cls.NO_CHANNELS

        for channel in channels:
            if not 11 <= channel <= 26:
                raise ValueError(
                    f"Invalid channel number {channel}. Must be between 11 and 26."
                )

            mask |= cls[f"CHANNEL_{channel}"]

        return mask


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


def FakeEnum(class_name: str):
    return attr.make_class(
        class_name,
        {"name": attr.ib(converter=str), "value": attr.ib()},
        bases=(_EnumEq,),
        eq=False,
    )


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


class Status(basic.uint8_t, enum.Enum):
    Success = 0x00
    Failure = 0x01
    InvalidParameter = 0x02
    ItemCreated = 0x09
    ItemNotCreated = 0x0A
    BadLength = 0x0C
    MemoryFailure = 0x10
    TableFull = 0x011
    MACNoResource = 0x1A
    InvalidRequest = 0xC2
    UnknownDevice = 0xC8
    ZMACInvalidParameter = 0xE8
    ZMACNoBeacon = 0xEA
    MACScanInProgress = 0xFC

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        try:
            return super().deserialize(data, byteorder)
        except ValueError:
            fenum = FakeEnum(cls.__name__)
            status, data = basic.uint8_t.deserialize(data, byteorder)
            return fenum(f"unknown_0x{status:02x}", status), data


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
    ClearConfig = 0x01
    ClearState = 0x02


class DeviceLogicalType(basic.enum_uint8, enum.IntFlag):
    Coordinator = 0x00
    Router = 0x01
    EndDevice = 0x02

    # Are these valid?
    ComplexDescAvail = 0x04
    UserDescAvail = 0x08
    Reserved1 = 0x10
    Reserved2 = 0x20
    Reserved3 = 0x40
    Reserved4 = 0x80
