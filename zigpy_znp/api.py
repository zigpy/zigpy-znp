import typing
import asyncio
import logging
import itertools
import contextlib
import dataclasses
import async_timeout

from collections import Counter, defaultdict

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c

from zigpy_znp.types import nvids
from zigpy_znp.logger import TRACE

from zigpy_znp import uart
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse


LOGGER = logging.getLogger(__name__)


def _deduplicate_commands(
    commands: typing.Iterable[t.CommandBase],
) -> typing.Tuple[t.CommandBase]:
    """
    Deduplicates an iterable of commands by folding more-specific commands into less-
    specific commands. Used to avoid triggering callbacks multiple times per packet.
    """

    # We essentially need to find the "maximal" commands, if you treat the relationship
    # between two commands as a partial order.
    maximal_commands = []

    # Command matching as a relation forms a partially ordered set.
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
                continue  # pragma: no cover
        else:
            # If we matched nothing and nothing matched us, we extend the list
            maximal_commands.append(command)

    # The start of each chain is the maximal element
    return tuple(maximal_commands)


@dataclasses.dataclass(frozen=True)
class BaseResponseListener:
    matching_commands: typing.Tuple[t.CommandBase]

    def __post_init__(self):
        commands = _deduplicate_commands(self.matching_commands)

        if not commands:
            raise ValueError("Cannot create a listener without any matching commands")

        # We're frozen so __setattr__ is disallowed
        object.__setattr__(self, "matching_commands", commands)

    def matching_headers(self) -> typing.Set[t.CommandHeader]:
        """
        Returns the set of Z-Stack MT command headers for all the matching commands.
        """

        return {response.header for response in self.matching_commands}

    def resolve(self, response: t.CommandBase) -> bool:
        """
        Attempts to resolve the listener with a given response. Can be called with any
        command as an argument, including ones we don't match.
        """

        if not any(c.matches(response) for c in self.matching_commands):
            return False

        return self._resolve(response)

    def _resolve(self, response: t.CommandBase) -> bool:
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


@dataclasses.dataclass(frozen=True)
class OneShotResponseListener(BaseResponseListener):
    """
    A response listener that resolves a single future exactly once.
    """

    future: asyncio.Future = dataclasses.field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    def _resolve(self, response: t.CommandBase) -> bool:
        if self.future.done():
            # This happens if the UART receives multiple packets during the same
            # event loop step and all of them match this listener. Our Future's
            # add_done_callback will not fire synchronously and thus the listener
            # is never properly removed. This isn't going to break anything.
            LOGGER.debug("Future already has a result set: %s", self.future)
            return False

        self.future.set_result(response)
        return True

    def cancel(self):
        if not self.future.done():
            self.future.cancel()

        return True


@dataclasses.dataclass(frozen=True)
class CallbackResponseListener(BaseResponseListener):
    """
    A response listener with a sync or async callback that is never resolved.
    """

    callback: typing.Callable[[t.CommandBase], typing.Any]

    def _resolve(self, response: t.CommandBase) -> bool:
        try:
            result = self.callback(response)

            # Run coroutines in the background
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            LOGGER.warning(
                "Caught an exception while executing callback", exc_info=True
            )

        # Callbacks are always resolved
        return True

    def cancel(self):
        # You can't cancel a callback
        return False


class ZNP:
    def __init__(self, config: conf.ConfigType):
        self._uart = None
        self._app = None
        self._config = config

        self._listeners = defaultdict(list)
        self._sync_request_lock = asyncio.Lock()

    def set_application(self, app):
        assert self._app is None
        self._app = app

    @property
    def _port_path(self) -> str:
        return self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH]

    async def connect(self, *, test_port=True, check_version=True) -> None:
        """
        Connects to the device specified by the "device" section of the config dict.

        The `test_port` kwarg allows port testing to be disabled, mainly to get into the
        bootloader.
        """

        # So we cannot connect twice
        assert self._uart is None

        try:
            self._uart = await uart.connect(self._config[conf.CONF_DEVICE], self)

            if self._config[conf.CONF_ZNP_CONFIG][conf.CONF_SKIP_BOOTLOADER]:
                LOGGER.debug("Sending special byte to skip the bootloader")
                self._uart._transport_write(bytes([c.ubl.BootloaderRunMode.FORCE_RUN]))

            # We have to disable all non-bootloader commands to enter the
            # bootloader upon connecting to the UART.
            if test_port:
                LOGGER.debug(
                    "Testing connection to %s", self._uart.transport.serial.name
                )

                # Make sure that our port works
                ping_rsp = await self.request(c.SYS.Ping.Req())

                if not ping_rsp.Capabilities & t.MTCapabilities.CAP_APP_CNF:
                    old_version_msg = (
                        "Your device appears to be running an old version of Z-Stack."
                        " The earliest supported release is Z-Stack 3.0.1."
                    )

                    if check_version:
                        raise RuntimeError(old_version_msg)
                    else:
                        LOGGER.warning(old_version_msg)
        except Exception:
            self.close()
            raise

        LOGGER.debug(
            "Connected to %s at %s baud",
            self._uart.transport.serial.name,
            self._uart.transport.serial.baudrate,
        )

    def connection_lost(self, exc) -> None:
        """
        Called by the UART object to indicate that the port was closed. Propagates up
        to the `ControllerApplication` that owns this ZNP instance.
        """

        LOGGER.debug("We were disconnected from %s: %s", self._port_path, exc)

        # The UART is already closed, there is no point in closing it again
        self._uart = None

        if self._app is not None:
            self._app.connection_lost(exc)

        self.close()

    def close(self) -> None:
        """
        Cleans up resources, namely the listener queues.

        Calling this will reset ZNP to the same internal state as a fresh ZNP instance.
        """

        for header, listeners in self._listeners.items():
            for listener in listeners:
                listener.cancel()

        self._listeners.clear()

        if self._uart is not None:
            self._uart.close()
            self._uart = None

        self._app = None

    def remove_listener(self, listener: BaseResponseListener) -> None:
        """
        Unbinds a listener from ZNP.

        Used by `wait_for_responses` to remove listeners for completed futures,
        regardless of their completion reason.
        """

        # If ZNP is closed while it's still running, `self._listeners` will be empty.
        if not self._listeners:
            return

        LOGGER.log(TRACE, "Removing listener %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].remove(listener)

            if not self._listeners[header]:
                LOGGER.log(
                    TRACE, "Cleaning up empty listener list for header %s", header
                )
                del self._listeners[header]

        counts = Counter()

        for listener in itertools.chain.from_iterable(self._listeners.values()):
            counts[type(listener)] += 1

        LOGGER.debug(
            "There are %d callbacks and %d one-shot listeners remaining",
            counts[CallbackResponseListener],
            counts[OneShotResponseListener],
        )

    def frame_received(self, frame: GeneralFrame) -> None:
        """
        Called when a frame has been received.

        XXX: Can be called multiple times in a single event loop step!
        """

        command_cls = c.COMMANDS_BY_ID[frame.header]
        command = command_cls.from_frame(frame)

        LOGGER.debug("Received command: %s", command)

        matched = False
        one_shot_matched = False

        for listener in self._listeners[command.header]:
            # XXX: A single response should *not* resolve multiple one-shot listeners!
            #      `future.add_done_callback` doesn't remove our listeners synchronously
            #      so doesn't prevent this from happening.
            if one_shot_matched and isinstance(listener, OneShotResponseListener):
                continue

            if not listener.resolve(command):
                LOGGER.log(TRACE, "%s does not match %s", command, listener)
                continue

            matched = True
            LOGGER.log(TRACE, "%s matches %s", command, listener)

            if isinstance(listener, OneShotResponseListener):
                one_shot_matched = True

        if not matched:
            LOGGER.warning("Received an unhandled command: %s", command)

    async def iterator_for_responses(
        self, responses
    ) -> typing.AsyncGenerator[t.CommandBase, None]:
        """
        Yields all matching responses as long as the async iterator is active.
        """

        async with self.capture_responses(responses) as queue:
            while True:
                yield await queue.get()

    @contextlib.asynccontextmanager
    async def capture_responses(self, responses):
        """
        Captures all matched responses in a queue within the context manager.
        """

        queue = asyncio.Queue()
        listener = self.callback_for_responses(responses, queue.put_nowait)

        try:
            yield queue
        finally:
            self.remove_listener(listener)

    def callback_for_responses(self, responses, callback) -> CallbackResponseListener:
        """
        Creates a callback listener that matches any of the provided responses.

        Only exists for consistency with `wait_for_responses`, since callbacks can be
        executed more than once.
        """

        listener = CallbackResponseListener(responses, callback=callback)

        LOGGER.log(TRACE, "Creating callback %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].append(listener)

        return listener

    def callback_for_response(
        self, response: t.CommandBase, callback
    ) -> CallbackResponseListener:
        """
        Creates a callback listener for a single response.
        """

        return self.callback_for_responses([response], callback)

    def wait_for_responses(self, responses) -> asyncio.Future:
        """
        Creates a one-shot listener that matches any *one* of the given responses.
        """

        listener = OneShotResponseListener(responses)

        LOGGER.log(TRACE, "Creating one-shot listener %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].append(listener)

        # Remove the listener when the future is done, not only when it gets a result
        listener.future.add_done_callback(lambda _: self.remove_listener(listener))

        return listener.future

    def wait_for_response(self, response: t.CommandBase) -> asyncio.Future:
        """
        Creates a one-shot listener for a single response.
        """

        return self.wait_for_responses([response])

    async def request(self, request: t.CommandBase, **response_params) -> t.CommandBase:
        """
        Sends a SREQ/AREQ request and returns its SRSP (only for SREQ), failing if any
        of the SRSP's parameters don't match `response_params`.
        """

        # Common mistake is to do `znp.request(c.SYS.Ping())`
        if type(request) is not request.Req:
            raise ValueError(f"Cannot send a command that isn't a request: {request!r}")

        # Construct a partial response out of the `Rsp*` kwargs if one is provded
        if request.Rsp:
            renamed_response_params = {}

            for param, value in response_params.items():
                if not param.startswith("Rsp"):
                    raise KeyError(
                        f"All response params must start with 'Rsp': {param!r}"
                    )

                renamed_response_params[param.replace("Rsp", "", 1)] = value

            # Construct our response before we send the request so that we fail early
            partial_response = request.Rsp(partial=True, **renamed_response_params)
        elif response_params:
            raise ValueError(
                f"Command has no response so response_params={response_params} "
                f"will have no effect"
            )

        LOGGER.debug("Sending request: %s", request)

        # If our request has no response, we cannot wait for one
        if not request.Rsp:
            LOGGER.debug("Request has no response, not waiting for one.")
            self._uart.send(request.to_frame())
            return

        # We should only be sending one SREQ at a time, according to the spec
        async with self._sync_request_lock:
            # We need to create the response listener before we send the request
            response_future = self.wait_for_responses(
                [
                    request.Rsp(partial=True),
                    c.RPCError.CommandNotRecognized.Rsp(
                        partial=True, RequestHeader=request.header
                    ),
                ]
            )
            self._uart.send(request.to_frame())

            # We should get a SRSP in a reasonable amount of time
            async with async_timeout.timeout(
                self._config[conf.CONF_ZNP_CONFIG][conf.CONF_SREQ_TIMEOUT]
            ):
                # We lock until either a sync response is seen or an error occurs
                response = await response_future

        if isinstance(response, c.RPCError.CommandNotRecognized.Rsp):
            raise CommandNotRecognized(
                f"Fatal request error {response} in response to {request}"
            )

        # If the sync response we got is not what we wanted, this is an error
        if not partial_response.matches(response):
            raise InvalidCommandResponse(
                f"Expected SRSP response {partial_response}, got {response}", response
            )

        return response

    async def request_callback_rsp(self, *, request, callback, **response_params):
        """
        Sends an SREQ, gets its SRSP confirmation, and waits for its real AREQ response.
        A bug-free version of:

            req_rsp = await req
            callback_rsp = await req_callback

        This is necessary because the SRSP and the AREQ may arrive in the same "chunk"
        from the UART and be handled in the same event loop step by ZNP.
        """

        callback_response = self.wait_for_response(callback)
        response = self.request(request, **response_params)

        await response

        async with async_timeout.timeout(
            self._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT]
        ):
            return await callback_response

    async def nvram_write(
        self, nv_id: nvids.BaseNvIds, value, *, offset: t.uint8_t = 0
    ):
        """
        Convenience function for writing a value to NVRAM. Serializes all serializable
        values and passes bytes directly.
        """

        if not isinstance(nv_id, nvids.BaseNvIds):
            raise ValueError(
                "The nv_id param must be an instance of BaseNvIds. "
                "Extend one of the tables in zigpy_znp.types.nvids."
            )

        if hasattr(value, "serialize"):
            value = value.serialize()
        elif not isinstance(value, (bytes, bytearray)):
            raise TypeError(
                f"Only bytes or serializable types can be written to NVRAM."
                f" Got {nv_id!r}={value!r} (type {type(value)})"
            )

        return await self.request(
            c.SYS.OSALNVWrite.Req(Id=nv_id, Offset=offset, Value=t.ShortBytes(value)),
            RspStatus=t.Status.SUCCESS,
        )

    async def nvram_read(
        self, nv_id: nvids.BaseNvIds, *, offset: t.uint8_t = 0
    ) -> bytes:
        """
        Reads a value from NVRAM.

        Raises an `InvalidCommandResponse` error if the NVID doesn't exist.
        """

        response = await self.request(
            c.SYS.OSALNVRead.Req(Id=nv_id, Offset=offset), RspStatus=t.Status.SUCCESS,
        )

        return response.Value
