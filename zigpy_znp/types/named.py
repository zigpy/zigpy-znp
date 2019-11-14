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

    NWK = 0x02
    IEEE = 0x03


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
