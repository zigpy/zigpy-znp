import zigpy_znp.commands as cmds
import zigpy_znp.commands.af as af


def _validate_schema(schema):
    for param in schema.parameters:
        assert isinstance(param.name, str)
        assert isinstance(param.type, type)
        assert isinstance(param.description, str)


def test_af_commands():
    for command in af.AFCommands:
        command = command.value
        assert command.command_type in (cmds.CommandType.AREQ, cmds.CommandType.SREQ)
        assert isinstance(command.command_id, int)
        _validate_schema(command.req_schema)
        _validate_schema(command.rsp_schema)
