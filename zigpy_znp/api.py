import attr
import typing
import asyncio
import logging

from collections import defaultdict

import zigpy_znp.commands
import zigpy_znp.types as t

from zigpy_znp import uart
from zigpy_znp.commands import SysCommands
from zigpy_znp.commands.types import CommandBase
from zigpy_znp.frames import GeneralFrame


LOGGER = logging.getLogger(__name__)


@attr.s(frozen=True)
class BaseResponseListener:
    matching_commands: typing.Tuple[CommandBase] = attr.ib(converter=tuple)

    @matching_commands.validator
    def check(self, attribute, commands):
        response_types = (
            zigpy_znp.commands.types.CommandType.SRSP,
            zigpy_znp.commands.types.CommandType.AREQ,
        )

        if commands[0].header.type not in response_types:
            raise ValueError(
                f"Can only wait for SRSPs and AREQs. Got: {commands[0].header.type}"
            )

    def matching_headers(self):
        for command in self.matching_commands:
            yield command.header

    def resolve(self, command: CommandBase) -> bool:
        if not any(c.matches(command) for c in self.matching_commands):
            return False

        self._resolve(command)
        return True

    def _resolve(self, command: CommandBase) -> None:
        raise NotImplementedError()


@attr.s(frozen=True)
class OneShotResponseListener(BaseResponseListener):
    future: asyncio.Future = attr.ib(
        default=attr.Factory(lambda: asyncio.get_running_loop().create_future())
    )

    def _resolve(self, command: CommandBase) -> None:
        self.future.set_result(command)


@attr.s(frozen=True)
class CallbackResponseListener(BaseResponseListener):
    callback: typing.Callable[[CommandBase], typing.Any] = attr.ib()

    def _resolve(self, command: CommandBase) -> None:
        try:
            result = self.callback(command)

            # Run coroutines in the background
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            LOGGER.warning(
                "Caught an exception while executing callback", exc_info=True
            )


class ZNP:
    def __init__(self):
        self._uart = None
        self._response_listeners = defaultdict(list)

    def set_application(self, app):
        self._app = app

    async def connect(self, device, baudrate=115_200):
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def connection_lost(self, exc):
        raise NotImplementedError()

    def close(self):
        return self._uart.close()

    def frame_received(self, frame: GeneralFrame):
        LOGGER.debug("Frame received: %s", frame)

        command_cls = zigpy_znp.commands.COMMANDS_BY_ID[frame.header]
        command = command_cls.from_frame(frame)

        if command.header not in self._response_listeners:
            LOGGER.warning("Received an unsolicited command: %s", command)
            return

        removed_listeners = []
        matched_listeners = set()

        for listener in self._response_listeners[command.header]:
            LOGGER.debug("Testing if %s matches %s", command, listener)

            if listener in matched_listeners:
                LOGGER.debug(
                    "Listener %s has already been triggered. Ignoring...", listener
                )
                continue

            if not listener.resolve(command):
                continue

            matched_listeners.add(listener)

            LOGGER.debug("Match found: %s ~ %s", command, listener)

            # Callbacks never expire
            if isinstance(listener, CallbackResponseListener):
                continue

            # We can't just break on the first match because we have callbacks
            removed_listeners.append(listener)

        # Remove our dead listeners after we've gone through all the rest
        for listener in removed_listeners:
            LOGGER.debug("Removing listener %s", listener)

            for header in listener.matching_headers():
                self._response_listeners[header].remove(listener)

                if not self._response_listeners[header]:
                    del self._response_listeners[header]

    def callback_for_responses(self, commands, callback) -> None:
        listener = CallbackResponseListener(commands, callback=callback)

        for header in listener.matching_headers():
            self._response_listeners[header].append(listener)

    def callback_for_response(self, command, callback) -> None:
        return self.callback_for_responses([command], callback)

    def wait_for_responses(self, commands) -> asyncio.Future:
        listener = OneShotResponseListener(commands)

        for header in listener.matching_headers():
            self._response_listeners[header].append(listener)

        return listener.future

    def wait_for_response(
        self, command: zigpy_znp.commands.types.CommandBase
    ) -> asyncio.Future:
        return self.wait_for_responses([command])

    async def command(self, command, *, ignore_response=False, **response_params):
        if ignore_response and response_params:
            raise KeyError(f"Cannot have both response_params and ignore_response")

        if command.header.type != zigpy_znp.commands.types.CommandType.SREQ:
            raise ValueError(f"Cannot send a command that isn't a request: {command!r}")

        # Construct our response before we send the request, ensuring we fail early
        response = command.Rsp(partial=True, **response_params)
        self._uart.send(command.to_frame())

        if ignore_response:
            return

        return await self.wait_for_response(response)

    async def nvram_write(self, nv_id: t.uint16_t, value, *, offset: t.uint8_t = 0):
        if not isinstance(value, bytes):
            value = value.serialize()

        return await self.command(
            SysCommands.OSALNVWrite.Req(
                Id=nv_id, Offset=offset, Value=t.ShortBytes(value)
            )
        )
