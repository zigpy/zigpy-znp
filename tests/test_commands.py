import pytest
import logging
import keyword
import dataclasses

import zigpy.types as zigpy_t
import zigpy.zdo.types
import zigpy_znp.commands as c
import zigpy_znp.frames as frames
from zigpy_znp import types as t

from collections import defaultdict


def test_command_header():
    """Test CommandHeader class."""
    data = b"\x61\x02"
    extra = b"the rest of data\xaa\x55"
    r, rest = t.CommandHeader.deserialize(data + extra)
    assert rest == extra
    assert r.cmd0 == 0x61
    assert r.id == 0x02

    r = t.CommandHeader(0x0261)
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
    command = t.CommandHeader(0xFFFF)
    for cmd_type in t.CommandType:
        for subsys in t.Subsystem:
            # There's probably no need to iterate over all 256 possible values
            for cmd_id in (0x00, 0xFF, 0x10, 0x01, 0xF0, 0x0F, 0x22, 0xEE):
                perms = [
                    command.with_id(cmd_id).with_type(cmd_type).with_subsystem(subsys),
                    command.with_type(cmd_type).with_id(cmd_id).with_subsystem(subsys),
                    command.with_type(cmd_type).with_subsystem(subsys).with_id(cmd_id),
                    command.with_subsystem(subsys).with_type(cmd_type).with_id(cmd_id),
                    command.with_subsystem(subsys).with_id(cmd_id).with_type(cmd_type),
                    command.with_id(cmd_id).with_subsystem(subsys).with_type(cmd_type),
                    t.CommandHeader(0xFFFF, id=cmd_id, subsystem=subsys, type=cmd_type),
                ]

                assert len(set(perms)) == 1
                assert perms[0].id == cmd_id
                assert perms[0].subsystem == subsys
                assert perms[0].type == cmd_type


def test_error_code():
    data = b"\x03"
    extra = b"the rest of the owl\x00\xff"

    r, rest = t.ErrorCode.deserialize(data + extra)
    assert rest == extra
    assert r == 0x03
    assert r.name == "INVALID_PARAMETER"

    r, rest = t.ErrorCode.deserialize(b"\xaa" + extra)
    assert rest == extra
    assert r.name == "unknown_0xAA"


def _validate_schema(schema):
    for index, param in enumerate(schema):
        assert isinstance(param.name, str)
        assert param.name.isidentifier()
        assert not keyword.iskeyword(param.name)
        assert isinstance(param.type, type)
        assert isinstance(param.description, str)

        # All optional params must be together at the end
        if param.optional:
            assert all(p.optional for p in schema[index:])

        # Trailing bytes must be at the very end
        if issubclass(param.type, t.TrailingBytes):
            assert not schema[index + 1 :]


def test_commands_schema():
    commands_by_id = defaultdict(list)

    for commands in c.ALL_COMMANDS:
        for cmd in commands:
            if cmd.type == t.CommandType.SREQ:
                assert cmd.type == cmd.Req.header.type
                assert cmd.Rsp.header.type == t.CommandType.SRSP
                assert (
                    cmd.subsystem
                    == cmd.Req.header.subsystem
                    == cmd.Rsp.header.subsystem
                )
                assert isinstance(cmd.Req.header, t.CommandHeader)
                assert isinstance(cmd.Rsp.header, t.CommandHeader)

                assert cmd.Req.Rsp is cmd.Rsp
                assert cmd.Rsp.Req is cmd.Req
                assert cmd.Callback is None

                _validate_schema(cmd.Req.schema)
                _validate_schema(cmd.Rsp.schema)

                commands_by_id[cmd.Req.header].append(cmd.Req)
                commands_by_id[cmd.Rsp.header].append(cmd.Rsp)
            elif cmd.type == t.CommandType.AREQ:
                # we call the AREQ Rsp a Callback
                assert cmd.Rsp is None

                # only one of them can be set
                assert (cmd.Callback is not None) ^ (cmd.Req is not None)

                if cmd.Callback is not None:
                    assert cmd.type == cmd.Callback.header.type
                    assert cmd.subsystem == cmd.Callback.header.subsystem
                    assert isinstance(cmd.Callback.header, t.CommandHeader)

                    _validate_schema(cmd.Callback.schema)

                    commands_by_id[cmd.Callback.header].append(cmd.Callback)
                elif cmd.Req is not None:
                    assert cmd.type == cmd.Req.header.type
                    assert cmd.subsystem == cmd.Req.header.subsystem
                    assert isinstance(cmd.Req.header, t.CommandHeader)

                    _validate_schema(cmd.Req.schema)

                    commands_by_id[cmd.Req.header].append(cmd.Req)
                else:
                    assert False, "Command is empty"
            elif cmd.type == t.CommandType.SRSP:
                # The one command like this is RPCError
                assert cmd is c.RPCError.CommandNotRecognized

                assert cmd.type == cmd.Rsp.header.type
                assert cmd.Req is None
                assert cmd.Callback is None
                assert cmd.Rsp.header.type == t.CommandType.SRSP
                assert cmd.subsystem == cmd.Rsp.header.subsystem
                assert isinstance(cmd.Rsp.header, t.CommandHeader)

                _validate_schema(cmd.Rsp.schema)

                commands_by_id[cmd.Rsp.header].append(cmd.Rsp)
            else:
                assert False, "Command has unknown type"

    duplicate_commands = {
        cmd: commands for cmd, commands in commands_by_id.items() if len(commands) > 1
    }
    assert not duplicate_commands

    assert len(commands_by_id.keys()) == len(c.COMMANDS_BY_ID.keys())


def test_command_param_binding():
    # No params
    c.SYS.Ping.Req()

    # Invalid param name
    with pytest.raises(KeyError):
        c.SYS.Ping.Rsp(asd=123)

    # Valid param name
    c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)

    # Too many params, one valid
    with pytest.raises(KeyError):
        c.SYS.Ping.Rsp(foo="asd", Capabilities=t.MTCapabilities.CAP_SYS)

    # Not enough params
    with pytest.raises(KeyError):
        c.SYS.Ping.Rsp()

    # Invalid type
    with pytest.raises(ValueError):
        c.Util.TimeAlive.Rsp(Seconds=b"asd")

    # Valid type but invalid value
    with pytest.raises(ValueError):
        c.Util.SetPreConfigKey.Req(PreConfigKey=t.KeyData([1, 2, 3]))

    # Coerced numerical type
    a = c.Util.TimeAlive.Rsp(Seconds=12)
    b = c.Util.TimeAlive.Rsp(Seconds=t.uint32_t(12))

    assert a == b
    assert a.Seconds == b.Seconds
    assert type(a.Seconds) == type(b.Seconds) == t.uint32_t  # noqa: E721

    # Overflowing integer types
    with pytest.raises(ValueError):
        c.Util.TimeAlive.Rsp(Seconds=10 ** 20)

    # Integers will not be coerced to enums
    assert t.MTCapabilities.CAP_SYS == 0x0001

    with pytest.raises(ValueError):
        c.SYS.Ping.Rsp(Capabilities=0x0001)

    # Parameters can be looked up by name
    ping_rsp = c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.CAP_SYS)
    assert ping_rsp.Capabilities == t.MTCapabilities.CAP_SYS

    # Invalid ones cannot
    with pytest.raises(AttributeError):
        ping_rsp.Oops

    # bytes are converted into t.ShortBytes
    cmd = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x0000, Value=b"asdfoo"
    )
    assert isinstance(cmd.Value, t.ShortBytes)

    # Lists are converted to typed LVLists
    c.Util.BindAddEntry.Req(
        DstAddrModeAddr=t.AddrModeAddress(mode=t.AddrMode.NWK, address=0x1234),
        DstEndpoint=0x56,
        ClusterIdList=[0x12, 0x45],
    )

    # Type errors within containers are also caught
    with pytest.raises(ValueError):
        c.Util.BindAddEntry.Req(
            DstAddrModeAddr=t.AddrModeAddress(mode=t.AddrMode.NWK, address=0x1234),
            DstEndpoint=0x56,
            ClusterIdList=[0x12, 0x457890],  # 0x457890 doesn't fit into a uint8_t
        )


def test_command_optional_params():
    # Optional params values don't need a value
    short_version_rsp = c.SYS.Version.Rsp(
        TransportRev=0, ProductId=1, MajorRel=2, MinorRel=3, MaintRel=4,
    )

    # Some can still be passed
    medium_version_rsp = c.SYS.Version.Rsp(
        TransportRev=0, ProductId=1, MajorRel=2, MinorRel=3, MaintRel=4, CodeRevision=5
    )

    # As can all
    long_version_rsp = c.SYS.Version.Rsp(
        TransportRev=0,
        ProductId=1,
        MajorRel=2,
        MinorRel=3,
        MaintRel=4,
        CodeRevision=5,
        BootloaderBuildType=c.sys.BootloaderBuildType.NON_BOOTLOADER_BUILD,
        BootloaderRevision=0xFFFFFFFF,
    )

    short_data = short_version_rsp.to_frame().data
    medium_data = medium_version_rsp.to_frame().data
    long_data = long_version_rsp.to_frame().data

    assert len(long_data) == len(medium_data) + 5 == len(short_data) + 9

    assert long_data.startswith(medium_data)
    assert medium_data.startswith(short_data)

    # Deserialization is greedy
    Version = c.SYS.Version.Rsp
    assert Version.from_frame(long_version_rsp.to_frame()) == long_version_rsp
    assert Version.from_frame(medium_version_rsp.to_frame()) == medium_version_rsp
    assert Version.from_frame(short_version_rsp.to_frame()) == short_version_rsp

    # Deserialization still fails if the frame is incomplete
    with pytest.raises(ValueError):
        Version.from_frame(
            frames.GeneralFrame(
                header=long_version_rsp.to_frame().header, data=long_data[:-1]
            )
        )

    # Deserialization will fail if the frame is incomplete but has no truncated fields
    with pytest.raises(ValueError):
        Version.from_frame(
            frames.GeneralFrame(
                header=long_version_rsp.to_frame().header, data=long_data[:4]
            )
        )

    with pytest.raises(ValueError):
        Version.from_frame(
            frames.GeneralFrame(
                header=long_version_rsp.to_frame().header, data=long_data + b"\x00"
            )
        )


def test_command_optional_params_failures():
    with pytest.raises(KeyError):
        # Optional params cannot be skipped over
        c.SYS.Version.Rsp(
            TransportRev=0,
            ProductId=1,
            MajorRel=2,
            MinorRel=3,
            MaintRel=4,
            # CodeRevision=5,
            BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_HEX,
        )

    # Unless it's a partial command
    partial = c.SYS.Version.Rsp(
        TransportRev=0,
        ProductId=1,
        MajorRel=2,
        MinorRel=3,
        MaintRel=4,
        # CodeRevision=5,
        BootloaderBuildType=c.sys.BootloaderBuildType.BUILT_AS_HEX,
        partial=True,
    )

    # In which case, it cannot be serialized
    with pytest.raises(ValueError):
        partial.to_frame()


def test_simple_descriptor():
    # Support both old and new zigpy types
    try:
        lvlist16_type = zigpy_t.LVList(t.uint16_t)
    except TypeError:
        lvlist16_type = zigpy_t.LVList[t.uint16_t]

    simple_descriptor = zigpy.zdo.types.SimpleDescriptor()
    simple_descriptor.endpoint = zigpy_t.uint8_t(1)
    simple_descriptor.profile = zigpy_t.uint16_t(260)
    simple_descriptor.device_type = zigpy_t.uint16_t(257)
    simple_descriptor.device_version = zigpy_t.uint8_t(0)
    simple_descriptor.input_clusters = lvlist16_type([0, 3, 4, 5, 6, 8, 2821, 1794])
    simple_descriptor.output_clusters = lvlist16_type([10, 25])

    c1 = c.ZDO.SimpleDescRsp.Callback(
        Src=t.NWK(0x1234),
        Status=t.ZDOStatus.SUCCESS,
        NWK=t.NWK(0x1234),
        SimpleDescriptor=simple_descriptor,
    )

    sp_simple_descriptor = zigpy.zdo.types.SizePrefixedSimpleDescriptor()
    sp_simple_descriptor.endpoint = zigpy_t.uint8_t(1)
    sp_simple_descriptor.profile = zigpy_t.uint16_t(260)
    sp_simple_descriptor.device_type = zigpy_t.uint16_t(257)
    sp_simple_descriptor.device_version = zigpy_t.uint8_t(0)
    sp_simple_descriptor.input_clusters = lvlist16_type([0, 3, 4, 5, 6, 8, 2821, 1794])
    sp_simple_descriptor.output_clusters = lvlist16_type([10, 25])

    c2 = c.ZDO.SimpleDescRsp.Callback(
        Src=t.NWK(0x1234),
        Status=t.ZDOStatus.SUCCESS,
        NWK=t.NWK(0x1234),
        SimpleDescriptor=sp_simple_descriptor,
    )

    assert c1.to_frame() == c2.to_frame()
    # assert c1 == c2


def test_command_str_repr():
    command = c.Util.BindAddEntry.Req(
        DstAddrModeAddr=t.AddrModeAddress(mode=t.AddrMode.NWK, address=0x1234),
        DstEndpoint=0x56,
        ClusterIdList=[0x12, 0x34],
    )

    assert repr(command) == str(command)
    assert str([command]) == f"[{str(command)}]"


def test_command_immutability():
    command1 = c.SYS.NVWrite.Req(
        partial=True, SysId=None, ItemId=0x1234, SubId=None, Offset=None, Value=None
    )

    command2 = c.SYS.NVWrite.Req(
        partial=True, SysId=None, ItemId=0x1234, SubId=None, Offset=None, Value=None
    )

    d = {command1: True}

    assert command1 == command2
    assert command2 in d
    assert {command1: True} == {command2: True}

    with pytest.raises(RuntimeError):
        command1.partial = False

    with pytest.raises(RuntimeError):
        command1.SysId = 0x10

    with pytest.raises(RuntimeError):
        command1.ItemId = 0x1234

    with pytest.raises(RuntimeError):
        del command1.ItemId

    assert command1 == command2


def test_command_serialization():
    command = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x0000, Value=b"asdfoo"
    )
    frame = command.to_frame()

    assert frame.data == bytes.fromhex("12 5634 9078 0000 06") + b"asdfoo"

    # Partial frames cannot be serialized
    with pytest.raises(ValueError):
        partial1 = c.SYS.NVWrite.Req(partial=True, SysId=0x12)
        partial1.to_frame()

    # Partial frames cannot be serialized, even if all params are filled out
    with pytest.raises(ValueError):
        partial2 = c.SYS.NVWrite.Req(
            partial=True, SysId=None, ItemId=0x1234, SubId=None, Offset=None, Value=None
        )
        partial2.to_frame()


def test_command_equality():
    command1 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    command2 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    command3 = c.SYS.NVWrite.Req(
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

    assert not command1.matches(c.SYS.NVWrite.Req(partial=True))
    assert c.SYS.NVWrite.Req(partial=True).matches(command1)

    # parameters can be specified explicitly as None
    assert c.SYS.NVWrite.Req(partial=True, SubId=None).matches(command1)
    assert c.SYS.NVWrite.Req(partial=True, SubId=0x7890).matches(command1)
    assert not c.SYS.NVWrite.Req(partial=True, SubId=123).matches(command1)

    # Different frame types do not match, even if they have the same structure
    assert not c.SYS.NVWrite.Rsp(Status=t.Status.SUCCESS).matches(
        c.SYS.NVDelete.Rsp(partial=True)
    )


def test_command_deserialization(caplog):
    command = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    assert type(command).from_frame(command.to_frame()) == command
    assert command.to_frame() == type(command).from_frame(command.to_frame()).to_frame()

    # Deserialization fails if there is unparsed data at the end of the frame
    with pytest.raises(ValueError):
        frame = command.to_frame()
        bad_frame = dataclasses.replace(frame, data=frame.data + b"\x00")

        type(command).from_frame(bad_frame)

    # But it does succeed with a warning if you explicitly allow it
    with caplog.at_level(logging.WARNING):
        type(command).from_frame(bad_frame, ignore_unparsed=True)

    assert "Unparsed" in caplog.text

    # Deserialization fails if you attempt to deserialize the wrong frame
    with pytest.raises(ValueError):
        c.SYS.NVWrite.Req.from_frame(c.SYS.Ping.Req().to_frame())


def test_command_not_recognized():
    command = c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidSubsystem,
        RequestHeader=t.CommandHeader(0xABCD),
    )

    transport_frame = frames.TransportFrame(command.to_frame())

    assert transport_frame.serialize()[:-1] == bytes.fromhex("FE  03  60 00  01  CD AB")


def test_command_replace_normal():
    command1 = c.SYS.NVWrite.Req(
        SysId=0x12, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoo"
    )

    command2 = c.SYS.NVWrite.Req(
        SysId=0x13, ItemId=0x3456, SubId=0x7890, Offset=0x00, Value=b"asdfoos"
    )

    assert command1.replace() == command1
    assert command1.replace(SysId=0x13, Value=b"asdfoos") == command2


def test_command_replace_partial():
    command1 = c.SYS.NVWrite.Req(partial=True, SysId=0x12)

    command2 = c.SYS.NVWrite.Req(partial=True, SysId=0x13)

    assert command1.replace() == command1
    assert command1.replace(SysId=0x13) == command2
