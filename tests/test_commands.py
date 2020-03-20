import pytest

import zigpy_znp.commands as c
from zigpy_znp import types as t

from collections import defaultdict


def test_command_header():
    """Test CommandHeader class."""
    data = b"\x61\x02"
    extra = b"the rest of data\xaa\x55"
    r, rest = c.CommandHeader.deserialize(data + extra)
    assert rest == extra
    assert r.cmd0 == 0x61
    assert r.id == 0x02

    r = c.CommandHeader(0x0261)
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
    # the setter order should not matter
    command = c.CommandHeader(0xFFFF)
    for cmd_type in c.CommandType:
        for subsys in c.Subsystem:
            # There's probably no need to iterate over all 256 possible values
            for cmd_id in (0x00, 0xFF, 0x10, 0x01, 0xF0, 0x0F, 0x22, 0xEE):
                perms = [
                    command.with_id(cmd_id).with_type(cmd_type).with_subsystem(subsys),
                    command.with_type(cmd_type).with_id(cmd_id).with_subsystem(subsys),
                    command.with_type(cmd_type).with_subsystem(subsys).with_id(cmd_id),
                    command.with_subsystem(subsys).with_type(cmd_type).with_id(cmd_id),
                    command.with_subsystem(subsys).with_id(cmd_id).with_type(cmd_type),
                    command.with_id(cmd_id).with_subsystem(subsys).with_type(cmd_type),
                ]

                assert len(set(perms)) == 1
                assert perms[0].id == cmd_id
                assert perms[0].subsystem == subsys
                assert perms[0].type == cmd_type


def test_error_code():
    data = b"\x03"
    extra = b"the rest of the owl\x00\xff"

    r, rest = c.ErrorCode.deserialize(data + extra)
    assert rest == extra
    assert r == 0x03
    assert r.name == "INVALID_PARAMETER"

    r, rest = c.ErrorCode.deserialize(b"\xaa" + extra)
    assert rest == extra
    assert r.name == "unknown_0xaa"


def _validate_schema(schema):
    for param in schema.parameters:
        assert isinstance(param.name, str)
        assert isinstance(param.type, type)
        assert isinstance(param.description, str)


def test_commands_schema():
    commands_by_id = defaultdict(list)

    for commands in c.ALL_COMMANDS:
        for command in commands:
            assert command.type in (c.CommandType.SREQ, c.CommandType.AREQ)

            if command.type == c.CommandType.SREQ:
                assert command.type == command.Req.header.type
                assert command.Rsp.header.type == c.CommandType.SRSP
                assert (
                    command.subsystem
                    == command.Req.header.subsystem
                    == command.Rsp.header.subsystem
                )
                assert isinstance(command.Req.header, c.CommandHeader)
                assert isinstance(command.Rsp.header, c.CommandHeader)

                assert command.Req.Rsp is command.Rsp
                assert command.Rsp.Req is command.Req

                _validate_schema(command.Req.schema)
                _validate_schema(command.Rsp.schema)

                commands_by_id[command.Req.header].append(command.Req)
                commands_by_id[command.Rsp.header].append(command.Rsp)
            elif command.type == c.CommandType.AREQ:
                assert command.type == command.Callback.header.type
                assert command.subsystem == command.Callback.header.subsystem
                assert isinstance(command.Callback.header, c.CommandHeader)

                _validate_schema(command.Callback.schema)

                commands_by_id[command.Callback.header].append(command.Callback)

    duplicate_commands = {
        cmd: commands for cmd, commands in commands_by_id.items() if len(commands) > 1
    }
    assert not duplicate_commands

    assert len(commands_by_id.keys()) == len(c.COMMANDS_BY_ID.keys())


def test_command_param_binding():
    # No params
    c.SysCommands.Ping.Req()

    # Invalid param name
    with pytest.raises(KeyError):
        c.SysCommands.Ping.Rsp(asd=123)

    # Valid param name
    c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)

    # Too many params, one valid
    with pytest.raises(KeyError):
        c.SysCommands.Ping.Rsp(foo="asd", Capabilities=c.types.MTCapabilities.CAP_SYS)

    # Not enough params
    with pytest.raises(KeyError):
        c.SysCommands.Ping.Rsp()

    # Invalid type
    with pytest.raises(ValueError):
        c.UtilCommands.TimeAlive.Rsp(Seconds=b"asd")

    # Coerced numerical type
    a = c.UtilCommands.TimeAlive.Rsp(Seconds=12)
    b = c.UtilCommands.TimeAlive.Rsp(Seconds=t.uint32_t(12))

    assert a.Seconds == b.Seconds
    assert type(a) == type(b)

    # Overflowing integer types
    with pytest.raises(ValueError):
        c.UtilCommands.TimeAlive.Rsp(Seconds=10 ** 20)

    # Integers will not be coerced to enums
    assert c.types.MTCapabilities.CAP_SYS == 0x0001

    with pytest.raises(ValueError):
        c.SysCommands.Ping.Rsp(Capabilities=0x0001)

    # Parameters can be looked up by name
    ping_rsp = c.SysCommands.Ping.Rsp(Capabilities=c.types.MTCapabilities.CAP_SYS)
    assert ping_rsp.Capabilities == c.types.MTCapabilities.CAP_SYS

    # Invalid ones cannot
    with pytest.raises(AttributeError):
        ping_rsp.Oops


def test_command_serialization():
    command = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )
    frame = command.to_frame()

    assert frame.data == bytes.fromhex("12 5634 9078 00 06") + b"asdfoo"

    # Partial frames cannot be serialized
    with pytest.raises(ValueError):
        partial1 = c.SysCommands.NVWrite.Req(partial=True, SysId=0x12)
        partial1.to_frame()

    # Partial frames cannot be serialized, even if all params are filled out
    with pytest.raises(ValueError):
        partial2 = c.SysCommands.NVWrite.Req(
            partial=True, SysId=None, ItemId=0x1234, SubId=None, Offset=None, Value=None
        )
        partial2.to_frame()


def test_command_equality():
    command1 = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    command2 = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    command3 = c.SysCommands.NVWrite.Req(
        SysId=0xFF, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
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

    assert not command1.matches(c.SysCommands.NVWrite.Req(partial=True))
    assert c.SysCommands.NVWrite.Req(partial=True).matches(command1)

    # parameters can be specified explicitly as None
    assert c.SysCommands.NVWrite.Req(partial=True, SubId=None).matches(command1)
    assert c.SysCommands.NVWrite.Req(partial=True, SubId=0x7890).matches(command1)
    assert not c.SysCommands.NVWrite.Req(partial=True, SubId=123).matches(command1)

    # Different frame types do not match, even if they have the same structure
    assert not c.SysCommands.NVWrite.Rsp(Status=t.Status.Success).matches(
        c.SysCommands.NVDelete.Rsp(partial=True)
    )


def test_command_deserialization():
    command = c.SysCommands.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    assert type(command).from_frame(command.to_frame()) == command
    assert command.to_frame() == type(command).from_frame(command.to_frame()).to_frame()

    # Deserialization fails if there is unparsed data at the end of the frame
    with pytest.raises(ValueError):
        bad_frame = command.to_frame()
        bad_frame.data += b"\x00"

        type(command).from_frame(bad_frame)

    # Deserialization fails if you attempt to deserialize the wrong frame
    with pytest.raises(ValueError):
        c.SysCommands.NVWrite.Req.from_frame(c.SysCommands.Ping.Req().to_frame())
