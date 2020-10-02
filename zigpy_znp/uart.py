import typing
import asyncio
import logging
import warnings
from collections import defaultdict

import serial
import serial.tools
from serial.tools.list_ports import comports as list_com_ports

import zigpy_znp.config as conf
import zigpy_znp.frames as frames
import zigpy_znp.logger as log
from zigpy_znp.types import Bytes
from zigpy_znp.exceptions import InvalidFrame

with warnings.catch_warnings():
    warnings.filterwarnings(
        action="ignore",
        module="serial_asyncio",
        message='"@coroutine" decorator is deprecated',
        category=DeprecationWarning,
    )
    import serial_asyncio  # noqa: E402


LOGGER = logging.getLogger(__name__)
RTS_TOGGLE_DELAY = 0.15  # seconds


class BufferTooShort(Exception):
    pass


class ZnpMtProtocol(asyncio.Protocol):
    def __init__(self, api):
        self._buffer = bytearray()
        self._api = api
        self._transport = None
        self._connected_event = asyncio.Event()

    def close(self) -> None:
        """Closes the port."""
        self._buffer.clear()

        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        """Connection lost."""

        if exc is not None:
            LOGGER.warning("Lost connection", exc_info=exc)

        LOGGER.debug("Closing serial port")

        self.close()
        self._api.connection_lost(exc)

    def connection_made(self, transport: serial_asyncio.SerialTransport) -> None:
        """Opened serial port."""
        self._transport = transport
        LOGGER.debug("Opened %s serial port", transport.serial.name)

        self._connected_event.set()

        self._api.connection_made()

    def data_received(self, data: bytes) -> None:
        """Callback when data is received."""
        self._buffer += data

        LOGGER.log(log.TRACE, "Received data: %s", Bytes.__repr__(data))

        for frame in self._extract_frames():
            LOGGER.log(log.TRACE, "Parsed frame: %s", frame)

            try:
                self._api.frame_received(frame.payload)
            except Exception as e:
                LOGGER.error(
                    "Received an exception while passing frame to API", exc_info=e
                )

    def send(self, payload: frames.GeneralFrame) -> None:
        """Sends data taking care of framing."""
        self._transport_write(frames.TransportFrame(payload).serialize())

    def _transport_write(self, data: bytes) -> None:
        LOGGER.log(log.TRACE, "Sending data: %s", Bytes.__repr__(data))
        self._transport.write(data)

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
        return f"<{type(self).__name__} for {self._api}>"


def find_ti_ports() -> typing.Iterable[
    typing.Tuple[str, serial.tools.list_ports_common.ListPortInfo]
]:
    """
    Finds all TI serial ports and yields an iterable of tuples, where the first element
    is the serial number of the device.
    """

    # Each dev kit has two serial ports, one of which is a debugger
    found_ports = defaultdict(list)

    for port in list_com_ports():
        if (port.vid, port.pid) == (0x0451, 0x16A8):
            # CC2531
            found_ports[port.serial_number].append(port)
        elif (port.vid, port.pid) == (0x0451, 0xBEF3):
            # LAUNCHXL-CC26X2R1
            found_ports[port.serial_number].append(port)
        elif (port.vid, port.pid) == (0x10C4, 0xEA60):
            # slae.sh CC2652RB stick
            if "slae.sh cc2652rb stick" in (port.product or ""):
                found_ports[port.serial_number].append(port)
            else:
                found_ports["CP210x"].append(port)
        elif (port.vid, port.pid) == (0x1A86, 0x7523):
            # ZZH (CH340, no way to distinguish it from any other CH340 device)
            found_ports["CH340"].append(port)

    # Python guarantees insertion order for dictionaries
    for serial_number, ports in found_ports.items():
        first_port = sorted(ports, key=lambda p: p.device)[0]

        yield serial_number, first_port


def guess_port() -> str:
    """
    Autodetects the best TI radio.

    The CH340 used by the ZZH adapter has no distinguishing information so it is not
    possible to tell whether or not a port belongs to a cheap Arduino clone or the ZZH.
    Known TI serial ports are picked over the CH340, which may belong to a cheap Arduino
    clone instead of the ZZH.
    """

    # Move generic serial adapters to the bottom of the list but keep the order of the
    # rest because Python's sort is stable.
    candidates = sorted(find_ti_ports(), key=lambda p: p[0] in ("CH340", "CP210x"))

    if not candidates:
        raise RuntimeError("Failed to detect any TI ports")

    _, port = candidates[0]

    if len(candidates) > 1:
        LOGGER.warning(
            "Found multiple possible Texas Instruments devices: %s",
            candidates,
        )
        LOGGER.warning("Picking the first one: %s", port)

    return port.device


async def connect(config: conf.ConfigType, api, *, toggle_rts=True) -> ZnpMtProtocol:
    loop = asyncio.get_running_loop()

    port = config[conf.CONF_DEVICE_PATH]
    baudrate = config[conf.CONF_DEVICE_BAUDRATE]
    flow_control = config[conf.CONF_DEVICE_FLOW_CONTROL]

    if port == "auto":
        port = guess_port()

    LOGGER.debug("Connecting to %s at %s baud", port, baudrate)

    transport, protocol = await serial_asyncio.create_serial_connection(
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

    # Skips the bootloader on slaesh's CC2652R USB stick
    if toggle_rts:
        LOGGER.debug("Toggling RTS/CTS to skip CC2652R bootloader")
        transport.serial.dtr = False
        transport.serial.rts = False

        await asyncio.sleep(RTS_TOGGLE_DELAY)

        transport.serial.dtr = False
        transport.serial.rts = True

        await asyncio.sleep(RTS_TOGGLE_DELAY)

        transport.serial.dtr = False
        transport.serial.rts = False

        await asyncio.sleep(RTS_TOGGLE_DELAY)

    LOGGER.debug("Connected to %s at %s baud", port, baudrate)

    return protocol
