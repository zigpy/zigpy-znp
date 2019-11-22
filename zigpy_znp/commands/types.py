import enum

import attr

import zigpy_znp.types as t


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
            fake_enum = t.FakeEnum("ErrorCode")
            return fake_enum(f"unknown_0x{code:02x}", code), data


class Subsystem(t.enum_uint8, enum.IntEnum):
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


class CallbackSubsystem(t.enum_uint16, enum.IntEnum):
    """Subscribe/unsubscribe subsystem callbacks."""

    MT_SYS = Subsystem.SYS << 8
    MC_MAC = Subsystem.MAC << 8
    MT_NWK = Subsystem.NWK << 8
    MT_AF = Subsystem.AF << 8
    MT_ZDO = Subsystem.ZDO << 8
    MT_SAPI = Subsystem.SAPI << 8
    MT_UTIL = Subsystem.UTIL << 8
    MT_DEBUG = Subsystem.DEBUG << 8
    MT_APP = Subsystem.APP << 8
    ALL = 0xFFFF


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
        self.cmd = t.uint16_t(self.cmd & 0x00FF | (value & 0xFF) << 8)

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


@attr.s
class CommandDef:
    command_type: CommandType = attr.ib()
    command_id: int = attr.ib()
    req_schema: t.Schema = attr.ib(factory=t.Schema)
    rsp_schema: t.Schema = attr.ib(factory=t.Schema)


class DeviceState(t.enum_uint8, enum.IntEnum):
    """Indicated device state."""

    InitializedNotStarted = 0x00
    InitializedNotConnected = 0x01
    DiscoveringPANs = 0x02
    Joining = 0x03
    ReJoining = 0x04
    JoinedNotAuthenticated = 0x05
    JoinedAsEndDevice = 0x06
    JoinedAsRouter = 0x07
    StartingAsCoordinator = 0x08
    StartedAsCoordinator = 0x09
    LostParent = 0x0A


class InterPanCommand(t.uint8_t, enum.Enum):
    InterPanClr = 0x00
    InterPanSet = 0x01
    InterPanReg = 0x02
    InterPanChk = 0x03


class MTCapabilities(t.enum_uint16, enum.IntFlag):
    CAP_SYS = 0x0001
    CAP_MAC = 0x0002
    CAP_NWK = 0x0004
    CAP_AF = 0x0008
    CAP_ZDO = 0x0010
    CAP_SAPI = 0x0020
    CAP_UTIL = 0x0040
    CAP_DEBUG = 0x0080
    CAP_APP = 0x0100
    CAP_ZOAD = 0x1000


STATUS_SCHEMA = t.Schema(
    (t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),)
)