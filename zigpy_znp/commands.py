import collections
import enum

import attr

import zigpy_znp.types as t
from zigpy_znp.types import basic


class CommandType(enum.IntEnum):
    """Command Type."""
    POLL = 0
    SREQ = 1  # A synchronous request that requires an immediate response
    AREQ = 2  # An asynchronous request
    SRSP = 3  # A synchronous response. This type of command is only sent in response to
              # a SREQ command
    RESERVED_4 = 4
    RESERVED_5 = 5
    RESERVED_6 = 6
    RESERVED_7 = 7


class ErrorCode(t.uint8_t, enum.Enum):
    """Error code."""
    INVALID_SUBSYSTEM = 0x01
    INVALID_COMMAND_ID = 0x02
    INVALID_PARAMETER = 0x03
    INVALID_LENGTH = 0x04

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        try:
            return super().deserialize(data, byteorder)
        except ValueError:
            code, data = t.uint8_t.deserialize(data, byteorder)
            fake_enum = collections.namedtuple("ErrorCode", "name,value")
            return fake_enum(f"unknown_0x{code:02x}", code), data


class Subsystem(t.uint8_t, enum.Enum):
    """Command sybsystem."""
    RPC = 0
    SYS = 1
    MAC = 2
    NWK = 3
    AF = 4
    ZDO = 5
    SAPI = 6
    UTIL = 7
    DEBUG = 8
    APP = 9
    RESERVED_10 = 10
    RESERVED_11 = 11
    RESERVED_12 = 12
    RESERVED_13 = 13
    RESERVED_14 = 14
    RESERVED_15 = 15
    RESERVED_16 = 16
    RESERVED_17 = 17
    RESERVED_18 = 18
    RESERVED_19 = 19
    RESERVED_20 = 20
    RESERVED_21 = 21
    RESERVED_22 = 22
    RESERVED_23 = 23
    RESERVED_24 = 24
    RESERVED_25 = 25
    RESERVED_26 = 26
    RESERVED_27 = 27
    RESERVED_28 = 28
    RESERVED_29 = 29
    RESERVED_30 = 30
    RESERVED_31 = 31


@attr.s
class Command(t.Struct):
    """Command class."""

    cmd = attr.ib(type=t.uint16_t, converter=t.uint16_t)

    @property
    def cmd0(self) -> t.uint8_t:
        """Cmd0 of the command."""
        return t.uint8_t(self.cmd & 0x00FF)

    @property
    def id(self) -> t.uint8_t:
        """Return Command id."""
        return t.uint8_t(self.cmd >> 8)

    @id.setter
    def id(self, value: int) -> None:
        """command ID setter."""
        self.cmd = t.uint16_t(self.cmd & 0xFF00 | value & 0xFF << 8)

    @property
    def subsystem(self) -> t.uint8_t:
        """Return subsystem of the command."""
        return Subsystem(self.cmd0 & 0x1F)

    @subsystem.setter
    def subsystem(self, value: int) -> None:
        """Subsystem setter."""
        self.cmd = self.cmd & 0xFFE0 | value & 0x1F

    @property
    def type(self) -> t.uint8_t:
        """Return command type."""
        return CommandType(self.cmd0 >> 5)

    @type.setter
    def type(self, value) -> None:
        """Type setter."""
        self.cmd = self.cmd & 0xFF1F | (value & 0x07) << 5
