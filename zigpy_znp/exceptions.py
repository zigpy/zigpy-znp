class InvalidFrame(ValueError):
    pass


class SecurityError(Exception):
    pass


class CommandError(Exception):
    pass


class CommandNotRecognized(CommandError):
    pass


class InvalidCommandResponse(CommandError):
    def __init__(self, message, response):
        super().__init__(message)
        self.response = response
