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

    new1 = r.with_id(0xFF)
    assert new1.id == 0xFF
    assert new1.cmd0 == 0x61

    new2 = r.with_id(0x00)
    assert new2.id == 0x00
    assert new2.cmd0 == 0x61


def test_command_setters():
    """Test setters"""
    # setting subsystem and type shouldn't change the other
    command = cmds.CommandHeader(0xFFFF)
    for cmd_type in cmds.CommandType:
        for subsys in cmds.Subsystem:
            new1 = command.with_type(cmd_type).with_subsystem(subsys)
            new2 = command.with_subsystem(subsys).with_type(cmd_type)

            assert new1 == new2
            assert new1.subsystem == subsys
            assert new1.type == cmd_type

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


def test_commands_schema():
    commands_by_id = defaultdict(list)

    for commands in cmds.ALL_COMMANDS:
        for command in commands:
            assert command.type in (cmds.CommandType.SREQ, cmds.CommandType.AREQ)

            if command.type == cmds.CommandType.SREQ:
                assert command.type == command.Req.header.type
                assert command.Rsp.header.type == cmds.CommandType.SRSP
                assert command.subsystem == command.Req.header.subsystem == command.Rsp.header.subsystem
                assert isinstance(command.Req.header, cmds.CommandHeader)
                assert isinstance(command.Rsp.header, cmds.CommandHeader)

                assert command.Req.Rsp is command.Rsp
                assert command.Rsp.Req is command.Req

                _validate_schema(command.Req.schema)
                _validate_schema(command.Rsp.schema)

                commands_by_id[command.Req.header].append(command.Req)
                commands_by_id[command.Rsp.header].append(command.Rsp)
            elif command.type == cmds.CommandType.AREQ:
                assert command.type == command.Callback.header.type
                assert command.subsystem == command.Callback.header.subsystem
                assert isinstance(command.Callback.header, cmds.CommandHeader)

                _validate_schema(command.Callback.schema)

                commands_by_id[command.Callback.header].append(command.Callback)

    duplicate_commands = {cmd: commands for cmd, commands in commands_by_id.items() if len(commands) > 1}
    assert not duplicate_commands

    assert len(commands_by_id.keys()) == len(cmds.COMMANDS_BY_ID.keys())


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

    # Parameters can be looked up by name
    c = cmds.sys.SysCommands.Ping.Rsp(Capabilities=cmds.types.MTCapabilities.CAP_SYS)
    assert c.Capabilities == cmds.types.MTCapabilities.CAP_SYS

    # Invalid ones cannot
    with pytest.raises(AttributeError):
        c.Oops


def test_command_serialization():
    command = cmds.sys.SysCommands.NVWrite.Req(
        SysId=0x12,
        ItemId=0x3456,
        SubId=0x7890,
        Offset=0x00,
        Value=b'asdfoo',
    )
    frame = command.to_frame()

    assert frame.data == bytes.fromhex('12 5634 9078 00 06') + b'asdfoo'


def test_command_equality():
    command1 = cmds.sys.SysCommands.NVWrite.Req(
        SysId=0x12,
        ItemId=0x3456,
        SubId=0x7890,
        Offset=0x00,
        Value=b'asdfoo',
    )

    command2 = cmds.sys.SysCommands.NVWrite.Req(
        SysId=0x12,
        ItemId=0x3456,
        SubId=0x7890,
        Offset=0x00,
        Value=b'asdfoo',
    )

    command3 = cmds.sys.SysCommands.NVWrite.Req(
        SysId=0xFF,
        ItemId=0x3456,
        SubId=0x7890,
        Offset=0x00,
        Value=b'asdfoo',
    )

    assert command1 == command1
    assert command1.matches(command1)
    assert command2 == command1
    assert command1 == command2

    assert command1 != command3
    assert command3 != command1

    assert command1.matches(command2)  # Matching is a superset of equality
    assert command2.matches(command1)
    assert not command1.matches(command3)
    assert not command3.matches(command1)

    assert not command1.matches(cmds.sys.SysCommands.NVWrite.Req(partial=True))
    assert cmds.sys.SysCommands.NVWrite.Req(partial=True).matches(command1)

    # parameters can be specified explicitly as None
    assert cmds.sys.SysCommands.NVWrite.Req(partial=True, SubId=None).matches(command1)
    assert cmds.sys.SysCommands.NVWrite.Req(partial=True, SubId=0x7890).matches(command1)
    assert not cmds.sys.SysCommands.NVWrite.Req(partial=True, SubId=123).matches(command1)


def test_command_deserialization():
    command = cmds.sys.SysCommands.NVWrite.Req(
        SysId=0x12,
        ItemId=0x3456,
        SubId=0x7890,
        Offset=0x00,
        Value=b'asdfoo',
    )

    assert type(command).from_frame(command.to_frame()) == command
    assert command.to_frame() == type(command).from_frame(command.to_frame()).to_frame()
