import attr
import typing
import asyncio
import logging
import async_timeout

from collections import defaultdict

import zigpy_znp.commands
import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types import nvids

from zigpy_znp import uart
from zigpy_znp.commands import SysCommands, RPCErrorCommands
from zigpy_znp.commands.types import CommandBase
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse


LOGGER = logging.getLogger(__name__)
RECONNECT_RETRY_TIME = 5  # seconds
SREQ_TIMEOUT = 5  # seconds


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

    def cancel(self):
        """
        Implement by subclasses to cancel the listener.

        Return value indicates whether or not the listener is cancelable.
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

    def cancel(self):
        if not self.future.done():
            self.future.cancel()

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

    def cancel(self):
        # You can't cancel a callback
        return False


class ZNP:
    def __init__(self, *, auto_reconnect=True):
        self._uart = None
        self._response_listeners = defaultdict(list)

        self._auto_reconnect = auto_reconnect
        self._device = None
        self._baudrate = None

        self._reconnect_task = None
        self._sync_request_lock = asyncio.Lock()

    def set_application(self, app):
        self._app = app

    async def connect(self, device, baudrate=115_200):
        assert self._uart is None

        self._uart, device = await uart.connect(device, baudrate, self)

        LOGGER.debug("Testing connection to %s", device)

        # Make sure that our port works
        async with async_timeout.timeout(2):
            await self.command(c.SysCommands.Ping.Req())

        # We want to reuse the same device when reconnecting
        self._device = device
        self._baudrate = baudrate

    def _cancel_all_listeners(self):
        for header, listeners in self._response_listeners.items():
            for listener in listeners:
                listener.cancel()

    async def _reconnect(self):
        while True:
            assert self._device is not None and self._baudrate is not None
            assert self._uart is None

            try:
                self._cancel_all_listeners()

                await self.connect(self._device, self._baudrate)
                await self._app.startup()

                self._reconnect_task = None
                break
            except Exception as e:
                LOGGER.error("Failed to reconnect", exc_info=e)
                await asyncio.sleep(RECONNECT_RETRY_TIME)

    def connection_lost(self, exc):
        self._uart = None

        if not self._auto_reconnect:
            return

        self._cancel_all_listeners()

        assert self._reconnect_task is None

        # Reconnect in the background using our previous device info
        # Note that this will reuse the same port as before
        self._reconnect_task = asyncio.create_task(self._reconnect())

    def close(self):
        return self._uart.close()

    def _remove_listener(self, listener: BaseResponseListener) -> None:
        LOGGER.debug("Removing listener %s", listener)

        for header in listener.matching_headers():
            self._response_listeners[header].remove(listener)

            if not self._response_listeners[header]:
                LOGGER.debug("Cleaning up empty listener list for header %s", header)
                del self._response_listeners[header]

    def frame_received(self, frame: GeneralFrame) -> None:
        """
        Called when a frame has been received.
        Can be called multiple times in a single step.
        """

        command_cls = zigpy_znp.commands.COMMANDS_BY_ID[frame.header]
        command = command_cls.from_frame(frame)

        LOGGER.debug("Received command: %s", command)

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

    async def command(self, command, **response_params):
        if type(command) is not command.Req:
            raise ValueError(f"Cannot send a command that isn't a request: {command!r}")

        if command.Rsp:
            # Construct our response before we send the request so that we fail early
            partial_response = command.Rsp(partial=True, **response_params)
        elif response_params:
            raise ValueError(
                f"Command has no response so response_params={response_params}"
                f"will have no effect"
            )

        LOGGER.debug("Sending command: %s", command)

        # If our command has no response, we cannot wait for one
        if not command.Rsp:
            self._uart.send(command.to_frame())
            return

        # We should only be sending one SREQ at a time, according to the spec
        async with self._sync_request_lock:
            self._uart.send(command.to_frame())

            # We should get a SRSP in a reasonable amount of time
            async with async_timeout.timeout(SREQ_TIMEOUT):
                # We lock until either a sync response is seen or an error occurs
                response = await self.wait_for_responses(
                    [
                        command.Rsp(partial=True),
                        RPCErrorCommands.CommandNotRecognized.Rsp(
                            partial=True, RequestHeader=command.header
                        ),
                    ]
                )

        if isinstance(response, RPCErrorCommands.CommandNotRecognized.Rsp):
            raise CommandNotRecognized(f"Fatal command error: {response}")

        # If the sync response we got is not what we wanted, this is an error
        if not partial_response.matches(response):
            raise InvalidCommandResponse(
                f"SRSP was not what we expected: {response} !~ {partial_response}"
            )

        return response

    async def nvram_write(
        self, nv_id: nvids.BaseNvIds, value, *, offset: t.uint8_t = 0
    ):
        # While unpythonic, explicit type checking here means we can detect overflows
        if not isinstance(nv_id, nvids.BaseNvIds):
            raise ValueError(
                "The nv_id param must be an instance of BaseNvIds. "
                "Extend one of the tables in zigpy_znp.types.nvids."
            )

        if not isinstance(value, bytes):
            value = value.serialize()

        # Find the next NVID in the table to check that our write doesn't overflow
        # It's not foolproof, but it will catch simple mistakes
        all_enum_values = list(type(nv_id))
        index = all_enum_values.index(nv_id)

        if index == len(all_enum_values) - 1:
            LOGGER.warning(
                "NVID is at end of table, cannot check for overflow"
            )  # pragma: no cover
        else:
            next_nvid = all_enum_values[index + 1]
            end_address = nv_id + offset + len(value)

            if end_address > next_nvid:
                raise ValueError("OSALNVWrite command overflows into %s", next_nvid)

        return await self.command(
            SysCommands.OSALNVWrite.Req(
                Id=nv_id, Offset=offset, Value=t.ShortBytes(value)
            )
        )
