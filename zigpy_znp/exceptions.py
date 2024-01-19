from zigpy.exceptions import DeliveryError, ControllerException


class InvalidFrame(ValueError):
    pass


class SecurityError(Exception):
    pass


class CommandNotRecognized(Exception):
    pass


class InvalidCommandResponse(DeliveryError):
    def __init__(self, message, response):
        super().__init__(message)
        self.response = response


class ShuttingDown(ControllerException):
    pass
