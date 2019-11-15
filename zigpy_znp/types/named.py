import attr
import enum
import typing

from zigpy.types import EUI64, NWK

from . import basic
from . import struct


class _EnumEq:
    def __eq__(self, other):
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)


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


@attr.s
class Schema:
    """List of Parameters."""

    parameters = attr.ib(factory=list, converter=list)


class Status(basic.uint8_t, enum.Enum):
    Success = 0x00
    Failure = 0x01
    InvalidParameter = 0x02
    MemoryFailure = 0x10

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        try:
            return super().deserialize(data, byteorder)
        except ValueError:
            fenum = FakeEnum(cls.__name__)
            status, data = basic.uint8_t.deserialize(data, byteorder)
            return fenum(f"unknown_0x{status:02x}", status), data


@attr.s
class Param:
    """Parameter."""

    name = attr.ib(converter=str)
    type = attr.ib()
    description = attr.ib(default="")


class KeySource(basic.FixedList):
    _length = 8
    _itemtype = basic.uint8_t
