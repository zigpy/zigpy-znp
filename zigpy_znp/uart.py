import asyncio
import binascii
import logging
import typing

import serial
import serial_asyncio

import zigpy_znp.frames as frames

LOGGER = logging.getLogger(__name__)


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
        while self._buffer:
            frame = self._extract_frame()
            if frame is None:
                return

            LOGGER.debug("Received frame: %s", binascii.hexlify(frame))
            frame, _ = frames.TransportFrame.deserialize(frame)
            if frame.is_valid:
                self._api.frame_received(frame.payload)
            else:
                LOGGER.debug(
                    "Invalid fcs: 0x%02x != 0x%02x", frame.fcs, frame.get_fcs()
                )

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

    def _extract_frame(self):
        """Extracts frame from buffer."""
        sof = self._buffer.find(frames.TransportFrame.SOF)
        if sof < 0:
            return None
        self._buffer = self._buffer[sof:]
        length = self._buffer[1]
        # extra bytes of data: sof=1, LEN=1, CMD=2, FCS=1
        if len(self._buffer) < length + 5:
            return None

        frame = self._buffer[: length + 5]
        self._buffer = self._buffer[length + 5 :]
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
