from __future__ import annotations

import time
import asyncio
import logging
import itertools
import contextlib
from collections import Counter, defaultdict

import async_timeout

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.logger as log
import zigpy_znp.commands as c
from zigpy_znp import uart
from zigpy_znp.nvram import NVRAMHelper
from zigpy_znp.utils import (
    BaseResponseListener,
    OneShotResponseListener,
    CallbackResponseListener,
)
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.znp.utils import NetworkInfo, load_network_info, detect_zstack_version
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse

LOGGER = logging.getLogger(__name__)
AFTER_CONNECT_DELAY = 1  # seconds
STARTUP_DELAY = 1  # seconds


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
        self.network_info: NetworkInfo = None

    def set_application(self, app):
        assert self._app is None
        self._app = app

    async def load_network_info(self):
        self.network_info = await load_network_info(self)

    async def reset(self) -> None:
        """
        Performs a soft reset within Z-Stack.
        A hard reset resets the serial port, causing the device to disconnect.
        """

        await self.request_callback_rsp(
            request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
            callback=c.SYS.ResetInd.Callback(partial=True),
        )

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

                # We need to know how structs are packed to deserialize frames corectly
                await self.nvram.determine_alignment()
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

        if frame.header not in c.COMMANDS_BY_ID:
            LOGGER.error("Received an unknown frame: %s", frame)
            return

        command_cls = c.COMMANDS_BY_ID[frame.header]

        try:
            command = command_cls.from_frame(frame, align=self.nvram.align_structs)
        except ValueError:
            # Some commands can be received corrupted. They are not useful:
            # https://github.com/home-assistant/core/issues/50005
            if command_cls == c.ZDO.ParentAnnceRsp.Callback:
                LOGGER.warning("Failed to parse broken %s as %s", frame, command_cls)
                return

            raise

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
        listener = self.callback_for_responses(responses, callback=queue.put_nowait)

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

        # Construct a partial response out of the `Rsp*` kwargs if one is provided
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

        frame = request.to_frame(align=self.nvram.align_structs)

        # We should only be sending one SREQ at a time, according to the spec
        async with self._sync_request_lock:
            LOGGER.debug("Sending request: %s", request)

            # If our request has no response, we cannot wait for one
            if not request.Rsp:
                LOGGER.debug("Request has no response, not waiting for one.")
                self._uart.send(frame)
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

            self._uart.send(frame)

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
        self, *, request, callback, timeout=None, background=False, **response_params
    ):
        """
        Sends an SREQ, gets its SRSP confirmation, and waits for its real AREQ response.
        A bug-free version of:

            req_rsp = await req
            callback_rsp = await req_callback

        This is necessary because the SRSP and the AREQ may arrive in the same "chunk"
        from the UART and be handled in the same event loop step by ZNP.
        """

        # Every request should have a timeout to prevent deadlocks
        if timeout is None:
            timeout = self._config[conf.CONF_ZNP_CONFIG][conf.CONF_ARSP_TIMEOUT]

        callback_rsp, listener = self.wait_for_responses([callback], context=True)

        if not background:
            try:
                async with async_timeout.timeout(timeout):
                    await self.request(request, **response_params)

                    return await callback_rsp
            finally:
                self.remove_listener(listener)

        start_time = time.time()

        # If the SREQ/SRSP pair fails, we must cancel the AREQ listener
        try:
            async with async_timeout.timeout(timeout):
                request_rsp = await self.request(request, **response_params)
        except Exception:
            self.remove_listener(listener)
            raise

        async def callback_handler(timeout):
            try:
                async with async_timeout.timeout(timeout):
                    await callback_rsp
            finally:
                self.remove_listener(listener)

        # If it succeeds, create a background task to receive the AREQ but take into
        # account the time it took to start the SREQ to ensure we do not grossly exceed
        # the timeout
        asyncio.create_task(callback_handler(time.time() - start_time))

        return request_rsp
