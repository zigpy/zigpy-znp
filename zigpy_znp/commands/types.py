import enum

import attr
import zigpy.zdo.types

import zigpy_znp.types as t


@attr.s
class BindEntry(t.Struct):
    """Bind table entry."""

    Src = attr.ib(type=t.EUI64, converter=t.Struct.converter(t.EUI64))
    SrcEp = attr.ib(type=t.uint8_t, converter=t.uint8_t)
    ClusterId = attr.ib(type=t.ClusterId, converter=t.ClusterId)
    DstAddr = attr.ib(
        type=zigpy.zdo.types.MultiAddress,
        converter=t.Struct.converter(zigpy.zdo.types.MultiAddress),
    )


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
    """Command subsystem."""

    Reserved = 0x00
    SYS = 0x01
    MAC = 0x02
    NWK = 0x03
    AF = 0x04
    ZDO = 0x05
    SAPI = 0x06
    UTIL = 0x07
    DEBUG = 0x08
    APP = 0x09
    RESERVED_10 = 0x0A
    RESERVED_11 = 0x0B
    RESERVED_12 = 0x0C
    RESERVED_13 = 0x0D
    RESERVED_14 = 0x0E
    APPConfig = 0x0F
    RESERVED_16 = 0x10
    RESERVED_17 = 0x11
    RESERVED_18 = 0x12
    RESERVED_19 = 0x13
    RESERVED_20 = 0x14
    ZGP = 0x15
    RESERVED_22 = 0x16
    RESERVED_23 = 0x17
    RESERVED_24 = 0x18
    RESERVED_25 = 0x19
    RESERVED_26 = 0x1A
    RESERVED_27 = 0x1B
    RESERVED_28 = 0x1C
    RESERVED_29 = 0x1D
    RESERVED_30 = 0x1E
    RESERVED_31 = 0x1F


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
    MT_APPConfig = Subsystem.APPConfig << 8
    MT_ZGP = Subsystem.ZGP << 8
    ALL = 0xFFFF


@attr.s
class CommandHeader(t.Struct):
    """CommandHeader class."""

    cmd = attr.ib(type=t.uint16_t, converter=t.uint16_t, repr=lambda c: f'0x{c:04x}')

    @property
    def cmd0(self) -> t.uint8_t:
        """Cmd0 of the command."""
        return t.uint8_t(self.cmd & 0x00FF)

    @property
    def id(self) -> t.uint8_t:
        """Return CommandHeader id."""
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


@attr.s
class Network(t.Struct):
    PanId = attr.ib(type=t.PanId, converter=t.Struct.converter(t.PanId))
    Channel = attr.ib(type=t.uint8_t, converter=t.uint8_t)
    StackProfileVersion = attr.ib(type=t.uint8_t, converter=t.uint8_t)
    BeaconOrderSuperframe = attr.ib(type=t.uint8_t, converter=t.uint8_t)
    PermitJoining = attr.ib(type=t.uint8_t, converter=t.uint8_t)


STATUS_SCHEMA = t.Schema(
    (t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),)
)
