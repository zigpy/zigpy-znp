from zigpy_znp.commands.types import (  # noqa: F401
    CommandHeader,
    CommandType,
    ErrorCode,
    Subsystem,
)

from .af import AFCommands
from .app import APPCommands
from .app_config import APPConfigCommands
from .mac import MacCommands
from .sapi import SAPICommands
from .sys import SysCommands
from .util import UtilCommands
from .zdo import ZDOCommands
from .zgp import ZGPCommands

ALL_COMMANDS = [
    AFCommands,
    APPCommands,
    APPConfigCommands,
    MacCommands,
    SAPICommands,
    SysCommands,
    UtilCommands,
    ZDOCommands,
    ZGPCommands,
]

COMMANDS_BY_ID = {}

for cmds in ALL_COMMANDS:
    for command in cmds:
        if command.type == CommandType.SREQ:
            COMMANDS_BY_ID[command.Req.header] = command.Req
            COMMANDS_BY_ID[command.Rsp.header] = command.Rsp
        elif command.type == CommandType.AREQ:
            COMMANDS_BY_ID[command.Callback.header] = command.Callback
        else:
            raise ValueError(f"Unhandled command type: {command.type}")
