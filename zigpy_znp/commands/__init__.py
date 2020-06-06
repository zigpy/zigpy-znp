from .rpc_error import RPCError
from .af import AF
from .app import App
from .app_config import AppConfig
from .mac import MAC
from .sapi import SAPI
from .sys import SYS
from .util import Util
from .zdo import ZDO
from .zgp import ZGP
from .znp import ZNP
from .ubl import UBL

ALL_COMMANDS = [
    RPCError,
    AF,
    App,
    AppConfig,
    MAC,
    SAPI,
    SYS,
    Util,
    ZDO,
    ZGP,
    ZNP,
    UBL,
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
