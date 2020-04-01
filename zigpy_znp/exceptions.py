class InvalidFrame(ValueError):
    pass


class CommandError(Exception):
    pass


class CommandNotRecognized(CommandError):
    pass


class InvalidCommandResponse(CommandError):
    pass
