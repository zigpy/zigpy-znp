from .af import AF as AF
from .app import APP as APP
from .app_config import AppConfig as AppConfig
from .mac import MAC as MAC
from .rpc_error import RPCError as RPCError
from .sapi import SAPI as SAPI
from .sys import SYS as SYS
from .ubl import UBL as UBL
from .util import UTIL as UTIL
from .zdo import ZDO as ZDO
from .zgp import ZGP as ZGP
from .znp import ZNP as ZNP

ALL_COMMANDS = [
    RPCError,
    AF,
    APP,
    AppConfig,
    MAC,
    SAPI,
    SYS,
    UTIL,
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
