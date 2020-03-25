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
    matching_commands: typing.Iterable[CommandBase] = attr.ib()

    @matching_commands.validator
    def check(self, attribute, commands):
        if len({type(c) for c in commands}) != 1:
            raise ValueError(f"All partial commands must be the same type: {commands}")

        response_types = (
            zigpy_znp.commands.types.CommandType.SRSP,
            zigpy_znp.commands.types.CommandType.AREQ,
        )

        if commands[0].header.type not in response_types:
            raise ValueError(
                f"Can only wait for SRSPs and AREQs. Got: {commands[0].header.type}"
            )

    @property
    def matching_header(self):
        return self.matching_commands[0].header

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
        self._response_futures = defaultdict(list)

    def set_application(self, app):
        self._app = app

    async def connect(self, device, baudrate=115_200):
        assert self._uart is None
        self._uart = await uart.connect(device, baudrate, self)

    def close(self):
        return self._uart.close()

    def frame_received(self, frame: GeneralFrame):
        LOGGER.debug("Frame received: %s", frame)

        command_cls = zigpy_znp.commands.COMMANDS_BY_ID[frame.header]
        command = command_cls.from_frame(frame)

        if command.header not in self._response_futures:
            LOGGER.warning("Received an unsolicited command: %s", command)
            return

        removed_listeners = []

        for listener in self._response_futures[command.header]:
            LOGGER.debug("Testing if %s matches %s", command, listener)

            if not listener.resolve(command):
                continue

            LOGGER.debug("Match found: %s ~ %s", command, listener)

            # Callbacks never expire
            if isinstance(listener, CallbackResponseListener):
                continue

            # We can't just break on the first match because we have callbacks
            removed_listeners.append(listener)

        # Remove our dead listeners after we've gone through all the rest
        for listener in removed_listeners:
            LOGGER.debug("Removing listener %s", listener)
            self._response_futures[command.header].remove(listener)

        # Clean up if we have no more listeners for this command
        if not self._response_futures[command.header]:
            del self._response_futures[command.header]

    def callback_for_responses(self, commands, callback) -> None:
        listener = CallbackResponseListener(commands, callback=callback)
        self._response_futures[listener.matching_header].append(listener)

    def callback_for_response(self, command, callback) -> None:
        return self.callback_for_responses([command], callback)

    def wait_for_responses(self, commands) -> asyncio.Future:
        listener = OneShotResponseListener(commands)
        self._response_futures[listener.matching_header].append(listener)

        return listener.future

    def wait_for_response(
        self, command: zigpy_znp.commands.types.CommandBase
    ) -> asyncio.Future:
        return self.wait_for_responses([command])

    async def command(self, command, *, ignore_response=False):
        if command.header.type != zigpy_znp.commands.types.CommandType.SREQ:
            raise ValueError(f"Cannot send a command that isn't a request: {command!r}")

        self._uart.send(command.to_frame())

        if ignore_response:
            return

        # By default, wait for any corresponding response to our request
        return await self.wait_for_response(command.Rsp(partial=True))

    async def nvram_write(self, nv_id: t.uint16_t, value, *, offset: t.uint8_t = 0):
        if not isinstance(value, bytes):
            value = value.serialize()

        return await self.command(
            SysCommands.OSALNVWrite.Req(
                Id=nv_id, Offset=offset, Value=t.ShortBytes(value)
            )
        )
