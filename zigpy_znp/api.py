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


def _deduplicate_commands(commands):
    # Command matching as a relation forms a partially ordered set.
    # To avoid triggering our callbacks multiple times per packet, we
    # should remove redundant partial commands.
    maximal_commands = []

    for command in commands:
        for index, other_command in enumerate(maximal_commands):
            if other_command.matches(command):
                # If the other command matches us, we are redundant
                break
            elif command.matches(other_command):
                # If we match another command, we replace it
                maximal_commands[index] = command
                break
            else:
                # Otherwise, we keep looking
                pass  # pragma: no cover
        else:
            # If we matched nothing and nothing matched us, we extend the list
            maximal_commands.append(command)

    # The start of each chain is the maximal element
    return tuple(maximal_commands)


@attr.s(frozen=True)
class BaseResponseListener:
    matching_commands: typing.Tuple[CommandBase] = attr.ib(
        converter=_deduplicate_commands
    )

    @matching_commands.validator
    def check(self, attribute, commands):
        if not commands:
            raise ValueError("Listener must have at least one command")

        response_types = (
            zigpy_znp.commands.types.CommandType.SRSP,
            zigpy_znp.commands.types.CommandType.AREQ,
        )

        if commands[0].header.type not in response_types:
            raise ValueError(
                f"Can only wait for SRSPs and AREQs. Got: {commands[0].header.type}"
            )

    def matching_headers(self):
        return {command.header for command in self.matching_commands}

    def resolve(self, command: CommandBase) -> bool:
        if not any(c.matches(command) for c in self.matching_commands):
            return False

        if not self._resolve(command):
            return False

        return True

    def _resolve(self, command: CommandBase) -> bool:
        """
        Implemented by subclasses to handle matched commands.

        Return value indicates whether or not the listener has actually resolved,
        which can sometimes be unavoidable.
        """
        raise NotImplementedError()  # pragma: no cover


@attr.s(frozen=True)
class OneShotResponseListener(BaseResponseListener):
    future: asyncio.Future = attr.ib(
        default=attr.Factory(lambda: asyncio.get_running_loop().create_future())
    )

    def _resolve(self, command: CommandBase) -> bool:
        if self.future.done():
            # This happens if the UART receives multiple packets during the same
            # event loop step and all of them match this listener. Our Future's
            # add_done_callback will not fire synchronously and thus the listener
            # is never properly removed. This isn't going to break anything.
            LOGGER.debug("Future already has a result set: %s", self.future)
            return False

        self.future.set_result(command)
        return True


@attr.s(frozen=True)
class CallbackResponseListener(BaseResponseListener):
    callback: typing.Callable[[CommandBase], typing.Any] = attr.ib()

    def _resolve(self, command: CommandBase) -> bool:
        try:
            result = self.callback(command)

            # Run coroutines in the background
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            LOGGER.warning(
                "Caught an exception while executing callback", exc_info=True
            )

        # Returning False could cause our callback to be called multiple times in a row
        return True


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

    def _remove_listener(self, listener: BaseResponseListener) -> None:
        LOGGER.debug("Removing listener %s", listener)

        for header in listener.matching_headers():
            self._response_listeners[header].remove(listener)

            if not self._response_listeners[header]:
                del self._response_listeners[header]

    def frame_received(self, frame: GeneralFrame) -> None:
        """
        Called when a frame has been received.
        Can be called multiple times in a single step.
        """

        LOGGER.debug("Frame received: %s", frame)

        command_cls = zigpy_znp.commands.COMMANDS_BY_ID[frame.header]
        command = command_cls.from_frame(frame)

        LOGGER.debug("Command received: %s", command)

        if command.header not in self._response_listeners:
            LOGGER.warning("Received an unsolicited command: %s", command)
            return

        for listener in self._response_listeners[command.header]:
            if not listener.resolve(command):
                LOGGER.debug("%s does not match %s", command, listener)
                continue

            LOGGER.debug("%s matches %s", command, listener)

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

        # Remove the listener when the future is done, not only when it gets a result
        listener.future.add_done_callback(lambda _: self._remove_listener(listener))

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
