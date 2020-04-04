import asyncio
import logging
import typing

import serial
import serial.tools
import serial_asyncio

from serial.tools.list_ports import comports as list_com_ports

import zigpy_znp.frames as frames

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

    @property
    def transport(self) -> typing.Optional[serial_asyncio.SerialTransport]:
        """Return current transport."""
        return self._transport

    def close(self) -> None:
        """Closes the port."""
        self._buffer.clear()
        self.transport.close()

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        """Connection lost."""

        self._buffer.clear()

        if exc is not None:
            LOGGER.warning(
                "Lost connection to %s", self._transport.serial.name, exc_info=exc
            )

        self._api.connection_lost(exc)

        LOGGER.debug("Closing %s serial port", self._transport.serial.name)

    def connection_made(self, transport: serial_asyncio.SerialTransport) -> None:
        """Opened serial port."""
        self._transport = transport
        LOGGER.debug("Opened %s serial port", transport.serial.name)

        self._connected_event.set()

    def data_received(self, data: bytes) -> None:
        """Callback when data is received."""
        self._buffer += data

        LOGGER.debug("Received data: %s", Bytes.__repr__(data))

        for frame in self._extract_frames():
            LOGGER.debug("Parsed frame: %s", frame)
            self._api.frame_received(frame.payload)

    def send(self, payload: frames.GeneralFrame) -> None:
        """Sends data taking care of framing."""
        data = frames.TransportFrame(payload).serialize()
        LOGGER.debug("Sending data: %s", Bytes.__repr__(data))
        self.transport.write(data)

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

    def __repr__(self):
        return f"<{type(self).__name__} for {self._api}>"


def guess_port() -> serial.tools.list_ports_common.ListPortInfo:
    """Picks the first USB port with a Texas Instruments vendor ID."""
    candidates = []

    for port in list_com_ports(include_links=True):
        # Add only TI devices
        if port.vid == 0x0451:
            candidates.append(port)

    if not candidates:
        raise RuntimeError("Could not auto detect any TI ports")

    # Is there no better heuristic than picking the first TI device?
    candidates.sort(key=lambda p: p.location)
    device = candidates[0].device

    if len(candidates) > 1:
        LOGGER.warning(
            "Found multiple Texas Instruments devices: %s",
            [c.__dict__ for c in candidates],
        )
        LOGGER.warning("Picking the first one: %s", device)

    return device


async def connect(port, baudrate, api, loop=None) -> typing.Tuple[ZnpMtProtocol, str]:
    if loop is None:
        loop = asyncio.get_event_loop()

    if port == "auto":
        port = guess_port()

    LOGGER.debug("Connecting to %s at %s baud", port, baudrate)

    transport, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: ZnpMtProtocol(api),
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
    )

    await protocol._connected_event.wait()

    LOGGER.debug("Connected to %s at %s baud", port, baudrate)

    return protocol, port
