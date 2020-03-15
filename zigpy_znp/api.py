import asyncio
import logging

from collections import defaultdict

import zigpy_znp.commands
import zigpy_znp.types as t

from zigpy_znp import uart
from zigpy_znp.commands.sys import SysCommands
from zigpy_znp.frames import GeneralFrame


LOGGER = logging.getLogger(__name__)


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

        for partial_commands, future in self._response_futures[command.header]:
            LOGGER.debug("Testing if %s matches any of %s", command, partial_commands)

            for partial_command in partial_commands:
                if partial_command.matches(command):
                    LOGGER.debug("Match found: %s ~ %s", command, partial_command)

                    self._response_futures[command.header].remove((partial_commands, future))
                    future.set_result(command)
                    break
        else:
            LOGGER.warning("No listener matched command: %s", command)

    def wait_for_responses(self, commands):
        if len({type(c) for c in commands}) != 1:
            raise ValueError(f"All partial commands must be the same type: {commands}")

        response_types = (zigpy_znp.commands.types.CommandType.SRSP, zigpy_znp.commands.types.CommandType.AREQ)

        if commands[0].header.type not in response_types:
            raise ValueError(f"Only SRSP and AREQ responses can be waited for. Got: {commands[0].header.type}")

        future = asyncio.get_running_loop().create_future()
        self._response_futures[commands[0].header].append((commands, future))

        return future

    def wait_for_response(self, command: zigpy_znp.commands.types.CommandBase):
        return self.wait_for_responses([command])

    async def command(self, command, *, ignore_response=False):
        if command.header.type != zigpy_znp.commands.types.CommandType.SREQ:
            raise ValueError(f"Cannot send a command that isn't a request: {command!r}")

        self._uart.send(command.to_frame())

        if ignore_response:
            return

        # By default, wait for any corresponding response to our request
        return await self.wait_for_response(command.Rsp(partial=True))

    async def nvram_write(self, nv_id: t.uint16_t, value, *, offset: t.uint8_t=0):
        if not isinstance(value, bytes):
            value = value.serialize()

        return await self.command(SysCommands.OSALNVWrite.Req(Id=nv_id, Offset=offset, Value=t.ShortBytes(value)))
