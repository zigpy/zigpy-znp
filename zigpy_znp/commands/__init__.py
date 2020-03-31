from zigpy_znp.commands.types import (  # noqa: F401
    CommandHeader,
    CommandType,
    ErrorCode,
    Subsystem,
)

from .rpc_error import RPCErrorCommands
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
    RPCErrorCommands,
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
        if command.Req is not None:
            COMMANDS_BY_ID[command.Req.header] = command.Req

        if command.Rsp is not None:
            COMMANDS_BY_ID[command.Rsp.header] = command.Rsp

        if command.Callback is not None:
            COMMANDS_BY_ID[command.Callback.header] = command.Callback
