from __future__ import annotations

import enum
import typing
import logging
import dataclasses

import zigpy.zdo.types

import zigpy_znp.types as t

LOGGER = logging.getLogger(__name__)


class CommandType(t.enum8):
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


class ErrorCode(t.enum8):
    """Error code."""

    INVALID_SUBSYSTEM = 0x01
    INVALID_COMMAND_ID = 0x02
    INVALID_PARAMETER = 0x03
    INVALID_LENGTH = 0x04


class Subsystem(t.enum8):
    """Command subsystem."""

    RPCError = 0x00
    SYS = 0x01
    MAC = 0x02
    NWK = 0x03
    AF = 0x04
    ZDO = 0x05
    SAPI = 0x06
    UTIL = 0x07
    DEBUG = 0x08
    APP = 0x09
    OTA = 0x0A
    ZNP = 0x0B
    RESERVED_12 = 0x0C
    UBL_FUNC = 0x0D
    RESERVED_14 = 0x0E
    APPConfig = 0x0F
    RESERVED_16 = 0x10
    PROTOBUF = 0x11
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


class CallbackSubsystem(t.enum16):
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


class CommandHeader(t.uint16_t):
    """CommandHeader class."""

    def __new__(
        cls, value: int = 0x0000, *, id=None, subsystem=None, type=None
    ) -> CommandHeader:
        instance = super().__new__(cls, value)

        if id is not None:
            instance = instance.with_id(id)

        if subsystem is not None:
            instance = instance.with_subsystem(subsystem)

        if type is not None:
            instance = instance.with_type(type)

        return instance

    @property
    def cmd0(self) -> t.uint8_t:
        return t.uint8_t(self & 0x00FF)

    @property
    def id(self) -> t.uint8_t:
        """Return CommandHeader id."""
        return t.uint8_t(self >> 8)

    def with_id(self, value: int) -> CommandHeader:
        """command ID setter."""
        return type(self)(self & 0x00FF | (value & 0xFF) << 8)

    @property
    def subsystem(self) -> Subsystem:
        """Return subsystem of the command."""
        return Subsystem(self.cmd0 & 0x1F)

    def with_subsystem(self, value: Subsystem) -> CommandHeader:
        return type(self)(self & 0xFFE0 | value & 0x1F)

    @property
    def type(self) -> CommandType:
        """Return command type."""
        return CommandType(self.cmd0 >> 5)

    def with_type(self, value) -> CommandHeader:
        return type(self)(self & 0xFF1F | (value & 0x07) << 5)

    def __str__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"id=0x{self.id:02X}, "
            f"subsystem={self.subsystem!s}, "
            f"type={self.type!s}"
            ")"
        )

    __repr__ = __str__


@dataclasses.dataclass(frozen=True)
class CommandDef:
    command_type: CommandType
    command_id: t.uint8_t
    req_schema: tuple | None = None
    rsp_schema: tuple | None = None


class CommandsMeta(type):
    """
    Metaclass that creates `Command` subclasses out of the `CommandDef` definitions
    """

    def __new__(cls, name: str, bases, classdict, *, subsystem):
        # Ignore CommandsBase
        if not bases:
            return type.__new__(cls, name, bases, classdict)

        classdict["_commands"] = []

        for command, definition in classdict.items():
            if not isinstance(definition, CommandDef):
                continue

            # We manually create the qualname to match the final object structure
            qualname = classdict["__qualname__"] + "." + command

            # The commands class is dynamically created from the definition
            helper_class_dict = {
                "definition": definition,
                "type": definition.command_type,
                "subsystem": subsystem,
                "__qualname__": qualname,
                "Req": None,
                "Rsp": None,
                "Callback": None,
            }

            header = (
                CommandHeader()
                .with_id(definition.command_id)
                .with_type(definition.command_type)
                .with_subsystem(subsystem)
            )

            rsp_header = header

            # TODO: explore __set_name__

            if definition.req_schema is not None:
                # AREQ doesn't necessarily mean it's a callback
                # Some requests don't have any response at all
                if definition.command_type == CommandType.AREQ:

                    class Req(CommandBase, header=header, schema=definition.req_schema):
                        pass

                    Req.__qualname__ = qualname + ".Req"
                    Req.Req = Req
                    Req.Rsp = None
                    Req.Callback = None
                    helper_class_dict["Req"] = Req
                else:
                    req_header = header
                    rsp_header = CommandHeader(0x0040 + req_header)

                    class Req(  # type:ignore[no-redef]
                        CommandBase, header=req_header, schema=definition.req_schema
                    ):
                        pass

                    class Rsp(
                        CommandBase, header=rsp_header, schema=definition.rsp_schema
                    ):
                        pass

                    Req.__qualname__ = qualname + ".Req"
                    Req.Req = Req
                    Req.Rsp = Rsp
                    Req.Callback = None
                    helper_class_dict["Req"] = Req

                    Rsp.__qualname__ = qualname + ".Rsp"
                    Rsp.Req = Rsp
                    Rsp.Req = Req
                    Rsp.Callback = None
                    helper_class_dict["Rsp"] = Rsp
            else:
                assert definition.rsp_schema is not None, definition

                if definition.command_type == CommandType.AREQ:
                    # If there is no request schema, this is a callback
                    class Callback(
                        CommandBase, header=header, schema=definition.rsp_schema
                    ):
                        pass

                    Callback.__qualname__ = qualname + ".Callback"
                    Callback.Req = None
                    Callback.Rsp = None
                    Callback.Callback = Callback
                    helper_class_dict["Callback"] = Callback
                elif definition.command_type == CommandType.SRSP:
                    # XXX: This is the only command like this
                    #      everything else should be an error!
                    if header != CommandHeader(
                        subsystem=Subsystem.RPCError, id=0x00, type=CommandType.SRSP
                    ):
                        raise RuntimeError(
                            f"Invalid command definition {command} = {definition}"
                        )  # pragma: no cover

                    # If there is no request, this is a just a response
                    class Rsp(  # type:ignore[no-redef]
                        CommandBase, header=header, schema=definition.rsp_schema
                    ):
                        pass

                    Rsp.__qualname__ = qualname + ".Rsp"
                    Rsp.Req = None
                    Rsp.Rsp = Rsp
                    Rsp.Callback = None
                    helper_class_dict["Rsp"] = Rsp
                else:
                    raise RuntimeError(
                        f"Invalid command definition {command} = {definition}"
                    )  # pragma: no cover

            classdict[command] = type(command, (), helper_class_dict)
            classdict["_commands"].append(classdict[command])

        return type.__new__(cls, name, bases, classdict)

    def __iter__(self):
        return iter(self._commands)


class CommandsBase(metaclass=CommandsMeta, subsystem=None):
    pass


class CommandBase:
    Req = None
    Rsp = None
    Callback = None

    def __init_subclass__(cls, *, header, schema):
        super().__init_subclass__()
        cls.header = header
        cls.schema = schema

    def __init__(self, *, partial=False, **params):
        super().__setattr__("_partial", partial)
        super().__setattr__("_bound_params", {})

        all_params = [p.name for p in self.schema]
        optional_params = [p.name for p in self.schema if p.optional]
        given_params = set(params.keys())
        given_optional = [p for p in params.keys() if p in optional_params]

        unknown_params = given_params - set(all_params)
        missing_params = (set(all_params) - set(optional_params)) - given_params

        if unknown_params:
            raise KeyError(
                f"Unexpected parameters: {unknown_params}. "
                f"Expected one of {missing_params}"
            )

        if not partial:
            # Optional params must be passed without any skips
            if optional_params[: len(given_optional)] != given_optional:
                raise KeyError(
                    f"Optional parameters cannot be skipped: "
                    f"expected order {optional_params}, got {given_optional}."
                )

            if missing_params:
                raise KeyError(f"Missing parameters: {set(all_params) - given_params}")

        bound_params = {}

        for param in self.schema:
            if params.get(param.name) is None and (partial or param.optional):
                bound_params[param.name] = (param, None)
                continue

            value = params[param.name]

            if not isinstance(value, param.type):
                # fmt: off
                is_coercible_type = [
                    isinstance(value, int)
                    and issubclass(param.type, int)
                    and not issubclass(param.type, enum.Enum),

                    isinstance(value, bytes)
                    and issubclass(param.type, (t.ShortBytes, t.LongBytes, t.Bytes)),

                    isinstance(value, list) and issubclass(param.type, list),
                    isinstance(value, bool) and issubclass(param.type, t.Bool),
                ]
                # fmt: on

                if any(is_coercible_type):
                    value = param.type(value)
                elif (
                    type(value) is zigpy.zdo.types.SimpleDescriptor
                    and param.type is zigpy.zdo.types.SizePrefixedSimpleDescriptor
                ):
                    data = value.serialize()
                    value, _ = param.type.deserialize(bytes([len(data)]) + data)
                else:
                    raise ValueError(
                        f"In {type(self)}, param {param.name} is "
                        f"type {param.type}, got {type(value)}"
                    )

            try:
                # XXX: Break early if a type cannot be serialized
                value.serialize()
            except Exception as e:
                raise ValueError(
                    f"Invalid parameter value: {param.name}={value!r}"
                ) from e

            bound_params[param.name] = (param, value)

        super().__setattr__("_bound_params", bound_params)

    def to_frame(self, *, align=False):
        if self._partial:
            raise ValueError(f"Cannot serialize a partial frame: {self}")

        from zigpy_znp.frames import GeneralFrame

        chunks = []

        for param, value in self._bound_params.values():
            # At this point the optional params are assumed to be in a valid order
            if value is None:
                continue

            if issubclass(param.type, t.CStruct):
                chunks.append(value.serialize(align=align))
            else:
                chunks.append(value.serialize())

        return GeneralFrame(self.header, b"".join(chunks))

    @classmethod
    def from_frame(cls, frame, *, align=False) -> CommandBase:
        if frame.header != cls.header:
            raise ValueError(
                f"Wrong frame header in {cls}: {cls.header} != {frame.header}"
            )

        data = frame.data
        params = {}

        for param in cls.schema:
            try:
                if issubclass(param.type, t.CStruct):
                    params[param.name], data = param.type.deserialize(data, align=align)
                else:
                    params[param.name], data = param.type.deserialize(data)
            except ValueError:
                if not data and param.optional:
                    # If we're out of data and the parameter is optional, we're done
                    break
                elif not data and not param.optional:
                    # If we're out of data but the parameter is required, this is bad
                    raise ValueError(
                        f"Frame data is truncated (parsed {params}),"
                        f" required parameter remains: {param}"
                    )
                else:
                    # Otherwise, let the exception happen
                    raise

        if data:
            raise ValueError(
                f"Frame {frame} contains trailing data after parsing: {data}"
            )

        return cls(**params)

    def matches(self, other: CommandBase) -> bool:
        if type(self) is not type(other):
            return False

        assert self.header == other.header

        param_pairs = zip(self._bound_params.values(), other._bound_params.values())

        for (
            (expected_param, expected_value),
            (actual_param, actual_value),
        ) in param_pairs:
            assert expected_param == actual_param

            # Only non-None bound params are considered
            if expected_value is not None and expected_value != actual_value:
                return False

        return True

    def replace(self, **kwargs) -> CommandBase:
        """
        Returns a copy of the current command with replaced parameters.
        """

        params = {key: value for key, (param, value) in self._bound_params.items()}
        params.update(kwargs)

        return type(self)(partial=self._partial, **params)

    def as_dict(self) -> dict[str, typing.Any]:
        """
        Converts the command into a dictionary.
        """

        return {p.name: v for p, v in self._bound_params.values()}

    def __eq__(self, other):
        return type(self) is type(other) and self._bound_params == other._bound_params

    def __hash__(self):
        params = tuple(self._bound_params.items())
        return hash((type(self), self.header, self.schema, params))

    def __getattribute__(self, key):
        try:
            return object.__getattribute__(self, key)
        except AttributeError:
            pass

        try:
            param, value = object.__getattribute__(self, "_bound_params")[key]
            return value
        except KeyError:
            pass

        raise AttributeError(f"{self} has no attribute {key!r}")

    def __setattr__(self, key, value):
        raise RuntimeError("Command instances are immutable")

    def __delattr__(self, key):
        raise RuntimeError("Command instances are immutable")

    def __repr__(self):
        params = [f"{p.name}={v!r}" for p, v in self._bound_params.values()]

        return f'{self.__class__.__qualname__}({", ".join(params)})'

    __str__ = __repr__


class DeviceState(t.enum8):
    """Indicated device state."""

    # Initialized - not started automatically
    InitializedNotStarted = 0x00
    # Initialized - not connected to anything
    InitializedNotConnected = 0x01
    # Discovering PAN's to join
    DiscoveringPANs = 0x02
    # Joining a PAN
    Joining = 0x03
    # ReJoining a PAN in secure mode scanning in current channel, only for end devices
    ReJoiningSecureScanningCurrentChannel = 0x04
    # Joined but not yet authenticated by trust center
    JoinedNotAuthenticated = 0x05
    # Started as device after authentication
    JoinedAsEndDevice = 0x06
    # Device joined, authenticated and is a router
    JoinedAsRouter = 0x07
    # Started as Zigbee Coordinator
    StartingAsCoordinator = 0x08
    # Started as Zigbee Coordinator
    StartedAsCoordinator = 0x09
    # Device has lost information about its parent
    LostParent = 0x0A
    # Device is sending KeepAlive message to its parent
    SendingKeepAliveToParent = 0x0B
    # Device is waiting before trying to rejoin
    BackoffBeforeRejoin = 0x0C
    # ReJoining a PAN in secure mode scanning in all channels, only for end devices
    RejoinSecureScanningAllChannels = 0x0D
    # ReJoining a PAN in unsecure mode scanning in current channel, only for end devices
    RejoinInsecureScanningCurrentChannel = 0x0E
    # ReJoining a PAN in unsecure mode scanning in all channels, only for end devices
    RejoinInsecureScanningAllChannels = 0x0F


class InterPanCommand(t.enum8):
    # Switch channel back to the NIB channel
    Clr = 0x00
    # Set channel for inter-pan communication
    Set = 0x01
    # Register an endpoint as inter-pan
    Reg = 0x02
    # Check if an endpoint is registered as inter-pan
    Chk = 0x03


class MTCapabilities(t.bitmap16):
    SYS = 1 << 0
    MAC = 1 << 1
    NWK = 1 << 2
    AF = 1 << 3
    ZDO = 1 << 4
    SAPI = 1 << 5
    UTIL = 1 << 6
    DEBUG = 1 << 7
    APP = 1 << 8
    GP = 1 << 9
    APP_CNF = 1 << 10
    UNK12 = 1 << 11
    ZOAD = 1 << 12
    UNK14 = 1 << 13
    UNK15 = 1 << 14
    UNK16 = 1 << 15


class Network(t.CStruct):
    PanId: t.PanId
    Channel: t.uint8_t
    StackProfileVersion: t.uint8_t
    BeaconOrderSuperframe: t.uint8_t
    PermitJoining: t.uint8_t


STATUS_SCHEMA = (
    t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
)
