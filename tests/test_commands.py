import zigpy_znp.commands as cmds


def test_command():
    """Test command class."""
    data = b"\x61\x02"
    extra = b"the rest of data\xaa\x55"
    r, rest = cmds.Command.deserialize(data + extra)
    assert rest == extra
    assert r.cmd0 == 0x61
    assert r.id == 0x02

    r = cmds.Command(0x0261)
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
    command = cmds.Command(0xFFFF)
    for cmd_type in cmds.CommandType:
        command.type = cmd_type
        for subsys in cmds.Subsystem:
            command.subsystem = subsys
            assert command.subsystem == subsys
            assert command.type == cmd_type


def test_command_type():
    """Test subsystem setter."""
    # setting type shouldn't change subsystem
    command = cmds.Command(0xFFFF)
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
    for command in commands:
        command = command.value
        assert command.command_type in (cmds.CommandType.AREQ, cmds.CommandType.SREQ)
        assert isinstance(command.command_id, int)
        _validate_schema(command.req_schema)
        _validate_schema(command.rsp_schema)
    cmd_ids = set((cmd.value.command_id for cmd in commands))
    assert len(cmd_ids) == len(commands)


def test_commands_schema():
    for commands in (
        cmds.af.AFCommands,
        cmds.app.APPCommands,
        cmds.app_config.APPConfigCommands,
        cmds.mac.MacCommands,
        cmds.sapi.SAPICommands,
        cmds.sys.SysCommands,
        cmds.util.UtilCommands,
        cmds.zdo.ZDOCommands,
        cmds.zgp.ZGPCommands,
    ):
        _test_commands(commands)
