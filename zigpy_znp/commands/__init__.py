from .af import AF
from .app import App
from .mac import MAC
from .sys import SYS
from .ubl import UBL
from .zdo import ZDO
from .zgp import ZGP
from .znp import ZNP
from .sapi import SAPI
from .util import Util
from .rpc_error import RPCError
from .app_config import AppConfig

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
