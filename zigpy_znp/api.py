import typing
import asyncio
import logging
import itertools
import contextlib
import dataclasses
from collections import Counter, defaultdict

import async_timeout

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.logger as log
import zigpy_znp.commands as c
from zigpy_znp import uart
from zigpy_znp.nvram import NVRAMHelper
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse
from zigpy_znp.types.nvids import ExNvIds, NvSysIds

LOGGER = logging.getLogger(__name__)
AFTER_CONNECT_DELAY = 1  # seconds
STARTUP_DELAY = 1  # seconds


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


async def detect_zstack_version(znp) -> float:
    """
    Feature detects the major version of Z-Stack running on the device.
    """

    # Z-Stack 1.2 does not have the AppConfig subsystem
    if not znp.capabilities & t.MTCapabilities.CAP_APP_CNF:
        return 1.2

    try:
        # Only Z-Stack 3.30+ has the new NVRAM system
        await znp.nvram.read(
            sys_id=NvSysIds.ZSTACK,
            item_id=ExNvIds.TCLK_TABLE,
            sub_id=0x0000,
        )
        return 3.30
    except KeyError:
        return 3.30
    except CommandNotRecognized:
        return 3.0


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

        self.capabilities = None
        self.version = None

        self.nvram = NVRAMHelper(self)

    def set_application(self, app):
        assert self._app is None
        self._app = app

    @property
    def _port_path(self) -> str:
        return self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH]

    async def connect(self, *, test_port=True) -> None:
        """
        Connects to the device specified by the "device" section of the config dict.

        The `test_port` kwarg allows port testing to be disabled, mainly to get into the
        bootloader.
        """

        # So we cannot connect twice
        assert self._uart is None

        try:
            self._uart = await uart.connect(self._config[conf.CONF_DEVICE], self)

            LOGGER.debug("Waiting %ss before sending anything", AFTER_CONNECT_DELAY)
            await asyncio.sleep(AFTER_CONNECT_DELAY)

            if self._config[conf.CONF_ZNP_CONFIG][conf.CONF_SKIP_BOOTLOADER]:
                LOGGER.debug("Sending bootloader skip byte")

                # XXX: Z-Stack locks up if other radios try probing it first.
                #      Writing the bootloader skip byte a bunch of times (at least 167)
                #      appears to reset it.
                skip = bytes([c.ubl.BootloaderRunMode.FORCE_RUN])
                self._uart._transport_write(skip * 256)

            # We have to disable all non-bootloader commands to enter the serial
            # bootloader upon connecting to the UART.
            if test_port:
                # Some Z-Stack 3 devices don't like you sending data immediately after
                # opening the serial port. A small delay helps, but they also sometimes
                # send a reset indication message when they're ready.
                LOGGER.debug(
                    "Waiting %ss or until a reset indication is received", STARTUP_DELAY
                )

                try:
                    async with async_timeout.timeout(STARTUP_DELAY):
                        await self.wait_for_response(
                            c.SYS.ResetInd.Callback(partial=True)
                        )
                except asyncio.TimeoutError:
                    pass

                LOGGER.debug("Testing connection to %s", self._port_path)

                # Make sure that our port works
                self.capabilities = (await self.request(c.SYS.Ping.Req())).Capabilities
                self.version = await detect_zstack_version(self)

                LOGGER.debug("Detected Z-Stack %s", self.version)
        except (Exception, asyncio.CancelledError):
            LOGGER.debug("Connection to %s failed, cleaning up", self._port_path)
            self.close()
            raise

        LOGGER.debug(
            "Connected to %s at %s baud",
            self._uart._transport.serial.name,
            self._uart._transport.serial.baudrate,
        )

    def connection_made(self) -> None:
        """
        Called by the UART object when a connection has been made.
        """
        pass

    def connection_lost(self, exc) -> None:
        """
        Called by the UART object to indicate that the port was closed. Propagates up
        to the `ControllerApplication` that owns this ZNP instance.
        """

        LOGGER.debug("We were disconnected from %s: %s", self._port_path, exc)

        if self._app is not None:
            self._app.connection_lost(exc)

    def close(self) -> None:
        """
        Cleans up resources, namely the listener queues.

        Calling this will reset ZNP to the same internal state as a fresh ZNP instance.
        """

        self._app = None

        for header, listeners in self._listeners.items():
            for listener in listeners:
                listener.cancel()

        self._listeners.clear()
        self.version = None
        self.capabilities = None

        if self._uart is not None:
            self._uart.close()
            self._uart = None

    def remove_listener(self, listener: BaseResponseListener) -> None:
        """
        Unbinds a listener from ZNP.

        Used by `wait_for_responses` to remove listeners for completed futures,
        regardless of their completion reason.
        """

        # If ZNP is closed while it's still running, `self._listeners` will be empty.
        if not self._listeners:
            return

        LOGGER.log(log.TRACE, "Removing listener %s", listener)

        for header in listener.matching_headers():
            try:
                self._listeners[header].remove(listener)
            except ValueError:
                pass

            if not self._listeners[header]:
                LOGGER.log(
                    log.TRACE, "Cleaning up empty listener list for header %s", header
                )
                del self._listeners[header]

        counts = Counter()

        for listener in itertools.chain.from_iterable(self._listeners.values()):
            counts[type(listener)] += 1

        LOGGER.log(
            log.TRACE,
            "There are %d callbacks and %d one-shot listeners remaining",
            counts[CallbackResponseListener],
            counts[OneShotResponseListener],
        )

    def frame_received(self, frame: GeneralFrame) -> bool:
        """
        Called when a frame has been received. Returns whether or not the frame was
        handled by any listener.

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
                LOGGER.log(log.TRACE, "%s does not match %s", command, listener)
                continue

            matched = True
            LOGGER.log(log.TRACE, "%s matches %s", command, listener)

            if isinstance(listener, OneShotResponseListener):
                one_shot_matched = True

        if not matched:
            self._unhandled_command(command)

        return matched

    def _unhandled_command(self, command: t.CommandBase):
        """
        Called when a command that is not handled by any listener is received.
        """

        LOGGER.warning("Received an unhandled command: %s", command)

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

    @contextlib.asynccontextmanager
    async def capture_responses_once(self, responses):
        """
        Captures all matched responses in a queue within the context manager.
        """

        future, listener = self.wait_for_responses(responses, context=True)

        try:
            yield future
        finally:
            self.remove_listener(listener)

    def callback_for_responses(self, responses, callback) -> CallbackResponseListener:
        """
        Creates a callback listener that matches any of the provided responses.

        Only exists for consistency with `wait_for_responses`, since callbacks can be
        executed more than once.
        """

        listener = CallbackResponseListener(responses, callback=callback)

        LOGGER.log(log.TRACE, "Creating callback %s", listener)

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

    def wait_for_responses(self, responses, *, context=False) -> asyncio.Future:
        """
        Creates a one-shot listener that matches any *one* of the given responses.
        """

        listener = OneShotResponseListener(responses)

        LOGGER.log(log.TRACE, "Creating one-shot listener %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].append(listener)

        # Remove the listener when the future is done, not only when it gets a result
        listener.future.add_done_callback(lambda _: self.remove_listener(listener))

        if context:
            return listener.future, listener
        else:
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

        # We should only be sending one SREQ at a time, according to the spec
        async with self._sync_request_lock:
            LOGGER.debug("Sending request: %s", request)

            # If our request has no response, we cannot wait for one
            if not request.Rsp:
                LOGGER.debug("Request has no response, not waiting for one.")
                self._uart.send(request.to_frame())
                return

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

    async def request_callback_rsp(
        self, *, request, callback, timeout=None, **response_params
    ):
        """
        Sends an SREQ, gets its SRSP confirmation, and waits for its real AREQ response.
        A bug-free version of:

            req_rsp = await req
            callback_rsp = await req_callback

        This is necessary because the SRSP and the AREQ may arrive in the same "chunk"
        from the UART and be handled in the same event loop step by ZNP.
        """

        if timeout is None:
            timeout = self._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT]

        # The async context manager allows us to clean up resources upon cancellation
        async with self.capture_responses_once([callback]) as callback_rsp:
            await self.request(request, **response_params)

            async with async_timeout.timeout(timeout):
                return await callback_rsp
