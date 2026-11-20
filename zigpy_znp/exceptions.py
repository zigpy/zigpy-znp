from __future__ import annotations

import typing

from zigpy.exceptions import DeliveryError

if typing.TYPE_CHECKING:
    import zigpy_znp.types as t


class InvalidFrame(ValueError):
    pass


class SecurityError(Exception):
    pass


class CommandNotRecognized(Exception):
    pass


class InvalidCommandResponse(DeliveryError):
    def __init__(self, message: str, response: t.CommandBase) -> None:
        super().__init__(message)
        self.response = response
