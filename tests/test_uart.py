import pytest
from serial_asyncio import SerialTransport

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp import uart as znp_uart
from zigpy_znp.frames import TransportFrame


@pytest.fixture
def connected_uart(mocker):
    znp = mocker.Mock()

    uart = znp_uart.ZnpMtProtocol(znp)
    uart.connection_made(mocker.Mock())

    yield znp, uart


@pytest.fixture
def dummy_serial_conn(event_loop, mocker):
    device = "/dev/ttyACM0"

    serial_interface = mocker.Mock()
    serial_interface.name = device

    def create_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        fut = event_loop.create_future()
        assert url == device

        protocol = protocol_factory()

        # Our event loop doesn't really do anything
        event_loop.add_writer = lambda *args, **kwargs: None
        event_loop.add_reader = lambda *args, **kwargs: None
        event_loop.remove_writer = lambda *args, **kwargs: None
        event_loop.remove_reader = lambda *args, **kwargs: None

        transport = SerialTransport(event_loop, protocol, serial_interface)

        protocol.connection_made(transport)

        fut.set_result((transport, protocol))

        return fut

    mocker.patch("serial_asyncio.create_serial_connection", new=create_serial_conn)

    return device, serial_interface


def test_uart_rx_basic(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    uart.data_received(test_frame_bytes)

    znp.frame_received.assert_called_once_with(test_frame)


def test_uart_str_repr(connected_uart):
    znp, uart = connected_uart

    str(uart)
    repr(uart)


def test_uart_rx_byte_by_byte(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    for byte in test_frame_bytes:
        uart.data_received(bytes([byte]))

    znp.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_byte_by_byte_garbage(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    data = b""
    data += bytes.fromhex("58 4a 72 35 51 da 60 ed 1f")
    data += bytes.fromhex("03 6d b6")
    data += bytes.fromhex("ee 90")
    data += test_frame_bytes
    data += bytes.fromhex("00 00")
    data += bytes.fromhex("e4 4f 51 b2 39 4b 8d e3 ca 61")
    data += bytes.fromhex("8c 56 8a 2c d8 22 64 9e 9d 7b")

    # The frame should be parsed identically regardless of framing
    for byte in data:
        uart.data_received(bytes([byte]))

    znp.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_big_garbage(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    data = b""
    data += bytes.fromhex("58 4a 72 35 51 da 60 ed 1f")
    data += bytes.fromhex("03 6d b6")
    data += bytes.fromhex("ee 90")
    data += test_frame_bytes
    data += bytes.fromhex("00 00")
    data += bytes.fromhex("e4 4f 51 b2 39 4b 8d e3 ca 61")
    data += bytes.fromhex("8c 56 8a 2c d8 22 64 9e 9d 7b")

    # The frame should be parsed identically regardless of framing
    uart.data_received(data)

    znp.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_corrupted_fcs(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    # Almost, but not quite
    uart.data_received(test_frame_bytes[:-1])
    uart.data_received(b"\x00")

    assert not znp.frame_received.called


def test_uart_rx_sof_stress(connected_uart):
    znp, uart = connected_uart

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    # We include an almost-valid frame and many stray SoF markers
    uart.data_received(b"\xFE" + b"\xFE" + b"\xFE" + test_frame_bytes[:-1] + b"\x00")
    uart.data_received(b"\xFE\xFE\x00\xFE\x01")
    uart.data_received(b"\xFE" + b"\xFE" + b"\xFE" + test_frame_bytes + b"\x00\x00")

    # We should see the valid frame exactly once
    znp.frame_received.assert_called_once_with(test_frame)


def test_uart_frame_received_error(connected_uart, mocker):
    znp, uart = connected_uart
    znp.frame_received = mocker.Mock(side_effect=RuntimeError("An error"))

    test_command = c.SYS.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        ProductId=0x45,
        MajorRel=0x01,
        MinorRel=0x02,
        MaintRel=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    # Errors thrown by znp.frame_received should not impact how many frames are handled
    uart.data_received(test_frame_bytes * 3)

    # We should have received all three frames
    znp.frame_received.call_count == 3


@pytest.mark.asyncio
async def test_connection_lost(dummy_serial_conn, mocker, event_loop):
    device, _ = dummy_serial_conn

    znp = mocker.Mock()
    conn_lost_fut = event_loop.create_future()
    znp.connection_lost = conn_lost_fut.set_result

    protocol = await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=znp, toggle_rts=False
    )

    exception = RuntimeError("Uh oh, something broke")
    protocol.connection_lost(exception)

    # Losing a connection propagates up to the ZNP object
    assert (await conn_lost_fut) == exception


@pytest.mark.asyncio
async def test_connection_made(dummy_serial_conn, mocker):
    device, _ = dummy_serial_conn
    znp = mocker.Mock()

    await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=znp, toggle_rts=False
    )

    znp.connection_made.assert_called_once_with()


@pytest.mark.asyncio
async def test_no_toggle_rts(dummy_serial_conn, mocker):
    device, serial = dummy_serial_conn

    type(serial).dtr = dtr = mocker.PropertyMock()
    type(serial).rts = rts = mocker.PropertyMock()

    znp = mocker.Mock()

    await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=znp, toggle_rts=False
    )

    assert dtr.mock_calls == []
    assert rts.mock_calls == []


@pytest.mark.asyncio
async def test_toggle_rts(dummy_serial_conn, mocker):
    device, serial = dummy_serial_conn

    type(serial).dtr = dtr = mocker.PropertyMock()
    type(serial).rts = rts = mocker.PropertyMock()

    znp = mocker.Mock()

    await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=znp, toggle_rts=True
    )

    assert dtr.mock_calls == [
        mocker.call(False),
        mocker.call(False),
        mocker.call(False),
    ]
    assert rts.mock_calls == [
        mocker.call(False),
        mocker.call(True),
        mocker.call(False),
    ]
