import pytest

import zigpy_znp.commands as cmds
from zigpy_znp import types as t

from collections import defaultdict


def test_command_header():
    """Test CommandHeader class."""
    data = b"\x61\x02"
    extra = b"the rest of data\xaa\x55"
    r, rest = cmds.CommandHeader.deserialize(data + extra)
    assert rest == extra
    assert r.cmd0 == 0x61
    assert r.id == 0x02

    r = cmds.CommandHeader(0x0261)
    assert r.cmd0 == 0x61
    assert r.id == 0x02

    r.id = 0xFF
    assert r.id == 0xFF
    assert r.cmd0 == 0x61

    r.id = 0x00
    assert r.id == 0x00
    assert r.cmd0 == 0x61


def test_command_subsystem():
    """Test subsystem setter."""
    # setting subsystem shouldn't change type
    command = cmds.CommandHeader(0xFFFF)
    for cmd_type in cmds.CommandType:
        command.type = cmd_type
        for subsys in cmds.Subsystem:
            command.subsystem = subsys
            assert command.subsystem == subsys
            assert command.type == cmd_type


def test_command_type():
    """Test type setter."""
    # setting type shouldn't change subsystem
    command = cmds.CommandHeader(0xFFFF)
    for subsys in cmds.Subsystem:
        command.subsystem = subsys
        for cmd_type in cmds.CommandType:
            command.type = cmd_type
            assert command.subsystem == subsys
            assert command.type == cmd_type


def test_error_code():
    data = b"\x03"
    extra = b"the rest of the owl\x00\xff"

    r, rest = cmds.ErrorCode.deserialize(data + extra)
    assert rest == extra
    assert r == 0x03
    assert r.name == "INVALID_PARAMETER"

    r, rest = cmds.ErrorCode.deserialize(b"\xaa" + extra)
    assert rest == extra
    assert r.name == "unknown_0xaa"


def _validate_schema(schema):
    for param in schema.parameters:
        assert isinstance(param.name, str)
        assert isinstance(param.type, type)
        assert isinstance(param.description, str)


def _test_commands(commands):
    commands_by_id = defaultdict(list)

    for command in commands:
        assert command.type in (cmds.CommandType.SREQ, cmds.CommandType.AREQ)

        if command.type == cmds.CommandType.SREQ:
            assert command.type == command.Req.header.type
            assert command.Rsp.header.type == cmds.CommandType.SRSP
            assert command.subsystem == command.Req.header.subsystem == command.Rsp.header.subsystem
            assert isinstance(command.Req.header, cmds.CommandHeader)
            assert isinstance(command.Rsp.header, cmds.CommandHeader)

            _validate_schema(command.Req.schema)
            _validate_schema(command.Rsp.schema)

            commands_by_id[command.Req.header.cmd].append(command.Req)
            commands_by_id[command.Rsp.header.cmd].append(command.Rsp)
        elif command.type == cmds.CommandType.AREQ:
            assert command.type == command.Callback.header.type
            assert command.subsystem == command.Callback.header.subsystem
            assert isinstance(command.Callback.header, cmds.CommandHeader)

            _validate_schema(command.Callback.schema)

            commands_by_id[command.Callback.header.cmd].append(command.Callback)

    duplicate_commands = {cmd: commands for cmd, commands in commands_by_id.items() if len(commands) > 1}
    assert not duplicate_commands


def test_commands_schema():
    for cls in cmds.ALL_COMMANDS:
        _test_commands(cls)

def test_command_param_binding():
    # No params
    cmds.sys.SysCommands.Ping.Req()

    # Invalid param name
    with pytest.raises(KeyError):    
        cmds.sys.SysCommands.Ping.Rsp(asd=123)

    # Valid param name
    cmds.sys.SysCommands.Ping.Rsp(Capabilities=cmds.types.MTCapabilities.CAP_SYS)

    # Too many params, one valid
    with pytest.raises(KeyError):    
        cmds.sys.SysCommands.Ping.Rsp(foo='asd', Capabilities=cmds.types.MTCapabilities.CAP_SYS)

    # Not enough params
    with pytest.raises(KeyError):
        cmds.sys.SysCommands.Ping.Rsp()

    # Invalid type
    with pytest.raises(ValueError):
        cmds.util.UtilCommands.TimeAlive.Rsp(Seconds=b'asd')

    # Coerced numerical type
    a = cmds.util.UtilCommands.TimeAlive.Rsp(Seconds=12)
    b = cmds.util.UtilCommands.TimeAlive.Rsp(Seconds=t.uint32_t(12))

    assert a.Seconds == b.Seconds
    assert type(a) == type(b)

    # Overflowing integer types
    with pytest.raises(ValueError):
        cmds.util.UtilCommands.TimeAlive.Rsp(Seconds=10**20)

    # Integers will not be coerced to enums
    assert cmds.types.MTCapabilities.CAP_SYS == 0x0001

    with pytest.raises(ValueError):
        cmds.sys.SysCommands.Ping.Rsp(Capabilities=0x0001)