from zigpy_znp.commands.types import (  # noqa: F401
    CommandHeader,
    CommandType,
    ErrorCode,
    Subsystem,
)

from . import af  # noqa: F401
from . import app  # noqa: F401
from . import app_config  # noqa: F401
from . import mac  # noqa: F401
from . import sapi  # noqa: F401
from . import sys  # noqa: F401
from . import util  # noqa: F401
from . import zdo  # noqa: F401
from . import zgp  # noqa: F401

ALL_COMMANDS = [
    af.AFCommands,
    app.APPCommands,
    app_config.APPConfigCommands,
    mac.MacCommands,
    sapi.SAPICommands,
    sys.SysCommands,
    util.UtilCommands,
    zdo.ZDOCommands,
    zgp.ZGPCommands,
]

COMMANDS_BY_ID = {}

for cmds in ALL_COMMANDS:
    for command in cmds:
        if command.type == CommandType.SREQ:
            COMMANDS_BY_ID[command.Req] = command.Req.header.cmd
            COMMANDS_BY_ID[command.Rsp] = command.Rsp.header.cmd
        elif command.type == CommandType.AREQ:
            COMMANDS_BY_ID[command.Callback] = command.Callback.header.cmd
        else:
            raise ValueError(f'Unhandled command type: {command.type}')