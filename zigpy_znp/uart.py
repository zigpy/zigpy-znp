import typing
import asyncio
import logging
import threading

import serialpy as serial
import serialpy as serial_asyncio

import zigpy_znp.config as conf
import zigpy_znp.frames as frames
import zigpy_znp.logger as log
import zigpy_znp.async_utils as async_utils
from zigpy_znp.types import Bytes
from zigpy_znp.exceptions import InvalidFrame

LOGGER = logging.getLogger(__name__)


class BufferTooShort(Exception):
    pass


class ZnpMtProtocol(asyncio.Protocol):
    def __init__(self, api):
        self._buffer = bytearray()
        self._api = api
        self._transport = None
        self._connected_event = asyncio.Event()

    @async_utils.run_in_znp_loop
    def close(self) -> None:
        """Closes the port."""

        self._api = None
        self._buffer.clear()

        if self._transport is not None:
            LOGGER.debug("Closing serial port")

            def close_transport():
                LOGGER.warning(
                    "Closing serial port in thread %s" % threading.current_thread().name
                )
                self._transport.close()
                self._transport = None

            try:
                close_transport()
            except RuntimeError:
                LOGGER.warning("Trying to close transport in its own loop")
                close_transport_in_loop = async_utils.run_in_loop(
                    close_transport, self._transport._loop
                )
                try:
                    close_transport_in_loop()
                except RuntimeError:
                    LOGGER.warning("Trying to close transport in znp loop")
                    close_transport_in_loop = async_utils.run_in_loop(
                        close_transport, async_utils.get_znp_loop()
                    )

                    try:
                        close_transport_in_loop()
                    except RuntimeError:
                        LOGGER.warning("Trying to close transport in worker loop")
                        close_transport_in_loop = async_utils.run_in_loop(
                            close_transport, async_utils.get_worker_loop()
                        )

                        try:
                            close_transport_in_loop()
                        except RuntimeError as e:
                            LOGGER.error(
                                "Failed to close serial connection in any loop"
                            )
                            raise e

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        """Connection lost."""

        if exc is not None:
            LOGGER.warning("Lost connection", exc_info=exc)

        if self._api is not None:
            self._api.connection_lost(exc)

    def connection_made(self, transport: serial_asyncio.SerialTransport) -> None:
        """Opened serial port."""
        self._transport = transport
        LOGGER.debug("Opened %s serial port", transport.serial.name)

        self._connected_event.set()

        if self._api is not None:
            self._api.connection_made()

    def data_received(self, data: bytes) -> None:
        """Callback when data is received."""
        self._buffer += data

        LOGGER.log(log.TRACE, "Received data: %s", Bytes.__repr__(data))

        for frame in self._extract_frames():
            LOGGER.log(log.TRACE, "Parsed frame: %s", frame)

            try:

                async def _frame_received(payload):
                    self._api.frame_received(payload)

                async_utils.run_in_worker_loop(
                    _frame_received(frame.payload), wait_for_result=False
                )
            except Exception as e:
                LOGGER.error(
                    "Received an exception while passing frame to API: %s",
                    frame,
                    exc_info=e,
                )

    def send(self, payload: frames.GeneralFrame) -> None:
        """Sends data taking care of framing."""
        self.write(frames.TransportFrame(payload).serialize())

    def write(self, data: bytes) -> None:
        """
        Writes raw bytes to the transport. This method should be used instead of
        directly writing to the transport with `transport.write`.
        """

        LOGGER.log(log.TRACE, "Sending data: %s", Bytes.__repr__(data))
        self._transport.write(data)

    def set_dtr_rts(self, *, dtr: bool, rts: bool) -> None:
        LOGGER.debug("Setting serial pin states: DTR=%s, RTS=%s", dtr, rts)

        self._transport.serial.dtr = dtr
        self._transport.serial.rts = rts

    @property
    def name(self) -> str:
        return self._transport.serial.name

    @property
    def baudrate(self) -> int:
        return self._transport.serial.baudrate

    def _extract_frames(self) -> typing.Iterator[frames.TransportFrame]:
        """Extracts frames from the buffer until it is exhausted."""
        while True:
            try:
                yield self._extract_frame()
            except BufferTooShort:
                # If the buffer is too short, there is nothing more we can do
                break
            except InvalidFrame:
                # If the buffer contains invalid data, drop it until we find the SoF
                sof_index = self._buffer.find(frames.TransportFrame.SOF, 1)

                if sof_index < 0:
                    # If we don't have a SoF in the buffer, drop everything
                    self._buffer.clear()
                else:
                    del self._buffer[:sof_index]

    def _extract_frame(self) -> frames.TransportFrame:
        """Extracts a single frame from the buffer."""

        # The shortest possible frame is 5 bytes long
        if len(self._buffer) < 5:
            raise BufferTooShort()

        # The buffer must start with a SoF
        if self._buffer[0] != frames.TransportFrame.SOF:
            raise InvalidFrame()

        length = self._buffer[1]

        # If the packet length field exceeds 250, our packet is not valid
        if length > 250:
            raise InvalidFrame()

        # Don't bother deserializing anything if the packet is too short
        # [SoF:1] [Length:1] [Command:2] [Data:(Length)] [FCS:1]
        if len(self._buffer) < length + 5:
            raise BufferTooShort()

        # At this point we should have a complete frame
        # If not, deserialization will fail and the error will propapate up
        frame, rest = frames.TransportFrame.deserialize(self._buffer)

        # If we get this far then we have a valid frame. Update the buffer.
        del self._buffer[: len(self._buffer) - len(rest)]

        return frame

    def __repr__(self) -> str:
        return (
            f"<"
            f"{type(self).__name__} connected to {self.name!r}"
            f" at {self.baudrate} baud"
            f" (api: {self._api})"
            f">"
        )


@async_utils.run_in_znp_loop
async def connect(config: conf.ConfigType, api) -> ZnpMtProtocol:
    LOGGER.info("uart connecting in thread %s" % threading.current_thread().name)
    loop = async_utils.get_znp_loop()

    port = config[conf.CONF_DEVICE_PATH]
    baudrate = config[conf.CONF_DEVICE_BAUDRATE]
    flow_control = config[conf.CONF_DEVICE_FLOW_CONTROL]

    LOGGER.debug(
        "Connecting to %s at %s baud in thread %s",
        port,
        baudrate,
        threading.current_thread().name,
    )

    _, protocol = await serial_asyncio.create_serial_connection(
        loop=loop,
        protocol_factory=lambda: ZnpMtProtocol(api),
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=(flow_control == "software"),
        rtscts=(flow_control == "hardware"),
    )

    await protocol._connected_event.wait()

    LOGGER.debug("Connected to %s at %s baud", port, baudrate)

    return protocol
