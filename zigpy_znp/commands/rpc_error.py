import enum
from zigpy_znp.commands.types import (
    CommandDef,
    CommandType,
    CommandsBase,
    Subsystem,
    CommandHeader,
)
import zigpy_znp.types as t


class ErrorCode(t.uint8_t, enum.Enum):
    InvalidSubsystem = 0x01
    InvalidCommandId = 0x02
    InvalidParameter = 0x03
    InvalidLength = 0x04


class RPCErrorCommands(CommandsBase, subsystem=Subsystem.RPCError):
    # When the ZNP cannot recognize an SREQ command from the host processor,
    # the following SRSP is returned
    CommandNotRecognized = CommandDef(
        CommandType.SRSP,
        0x00,
        req_schema=None,  # XXX: There is no REQ, only a RSP
        rsp_schema=t.Schema(
            (
                t.Param(
                    "ErrorCode",
                    ErrorCode,
                    "The error code maps to one of the following enumerated values.",
                ),
                t.Param(
                    "RequestHeader", CommandHeader, "Header of the invalid request"
                ),
            )
        ),
    )
