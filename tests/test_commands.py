import zigpy_znp.commands as cmds


def test_command():
    """Test command class."""
    data = b"\x02\x61"
    extra = b"the rest of data\xaa\x55"
    r, rest = cmds.Command.deserialize(data + extra)
    assert rest == extra
    assert r.cmd0 == 0x02
    assert r.id == 0x61

    r = cmds.Command(0x02, 0x61)
    assert r.cmd0 == 0x02


def test_command_subsystem():
    """Test subsystem setter."""
    # setting subsystem shouldn't change type
    command = cmds.Command(0xff, 0xff)
    for cmd_type in cmds.CommandType:
        command.type = cmd_type
        for subsys in cmds.Subsystem:
            command.subsystem = subsys
            assert command.subsystem == subsys
            assert command.type == cmd_type


def test_command_type():
    """Test subsystem setter."""
    # setting type shouldn't change subsystem
    command = cmds.Command(0xff, 0xff)
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
