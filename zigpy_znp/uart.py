import asyncio
import binascii
import logging
import typing

import serial
import serial_asyncio

import zigpy_znp.frames as frames
from zigpy_znp.exceptions import InvalidFrame

LOGGER = logging.getLogger(__name__)


class BufferTooShort(Exception):
    pass


class Gateway(asyncio.Protocol):
    def __init__(self, api):
        self._buffer = b""
        self._api = api
        self._transport = None

    def close(self) -> None:
        """Closes the port."""
        self.transport.close()

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        """Connection lost."""
        if exc is not None:
            LOGGER.info("Lost connection to %s: %s", self._transport.serial.name, exc)
            self._api.connection_lost(exc)
        LOGGER.debug("Closing %s serial port", self._transport.serial.name)

    def connection_made(self, transport: serial_asyncio.SerialTransport) -> None:
        """Opened serial port."""
        self._transport = transport
        LOGGER.debug("Opened %s serial port", transport.serial.name)

    def data_received(self, data: bytes) -> None:
        """Callback when data is received."""
        self._buffer += data

        for frame in self._extract_frames():
            LOGGER.debug("Received frame: %s", frame)
            self._api.frame_received(frame.payload)

    def send(self, payload: frames.GeneralFrame) -> None:
        """Sends data taking care of framing."""
        data = frames.TransportFrame(payload).serialize()
        LOGGER.debug("Sending: %s", binascii.hexlify(data))
        self.transport.write(data)

    def skip_bootloader(self) -> None:
        """Send magic byte to skip Serial Boot Loader."""
        LOGGER.debug("Skipping bootloader: 0xFE")
        self.transport.write(b"\xFE")

    @property
    def transport(self) -> typing.Optional[serial_asyncio.SerialTransport]:
        """Return current transport."""
        return self._transport

    def _extract_frames(self):
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
                    self._buffer = b""
                else:
                    self._buffer = self._buffer[sof_index:]

    def _extract_frame(self) -> typing.Optional[frames.TransportFrame]:
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
        frame, rest = frames.TransportFrame.deserialize(self._buffer)

        if not frame.is_valid:
            LOGGER.warning(
                "Received an invalid frame: %s. Correct FCS is 0x%02X, got 0x%02X.",
                frame,
                frame.get_fcs(),
                frame.fcs,
            )
            raise InvalidFrame()

        # Finally, we have a valid frame
        self._buffer = rest

        return frame


async def connect(port, baudrate, api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    transport, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: Gateway(api),
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
    )

    return protocol
