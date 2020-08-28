import zigpy_znp.types as t


class ErrorCode(t.enum_uint8):
    InvalidSubsystem = 0x01
    InvalidCommandId = 0x02
    InvalidParameter = 0x03
    InvalidLength = 0x04


class RPCError(t.CommandsBase, subsystem=t.Subsystem.RPCError):
    # When the ZNP cannot recognize an SREQ command from the host processor,
    # the following SRSP is returned
    CommandNotRecognized = t.CommandDef(
        t.CommandType.SRSP,
        0x00,
        req_schema=None,  # XXX: There is no REQ, only a RSP
        rsp_schema=(
            t.Param(
                "ErrorCode",
                ErrorCode,
                "The error code maps to one of the following enumerated values.",
            ),
            t.Param("RequestHeader", t.CommandHeader, "Header of the invalid request"),
        ),
    )
