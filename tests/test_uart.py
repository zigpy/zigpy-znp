from unittest.mock import Mock

import zigpy_znp.commands as c
import zigpy_znp.types as t

from zigpy_znp.uart import Gateway
from zigpy_znp.frames import TransportFrame


def test_uart_rx_basic():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    uart.data_received(test_frame_bytes)

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_byte_by_byte():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    for byte in test_frame_bytes:
        uart.data_received(bytes([byte]))

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_byte_by_byte_garbage():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_big_garbage():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_corrupted_fcs():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    # Almost, but not quite
    uart.data_received(test_frame_bytes[:-1])
    uart.data_received(b"\x00")

    assert not api.frame_received.called


def test_uart_rx_sof_stress():
    api = Mock()
    transport = Mock()

    uart = Gateway(api)
    uart.connection_made(transport)

    test_command = c.SysCommands.ResetInd.Callback(
        Reason=t.ResetReason.PowerUp,
        TransportRev=0x00,
        MajorRel=0x01,
        MinorRel=0x02,
        HwRev=0x03,
    )
    test_frame = test_command.to_frame()
    test_frame_bytes = TransportFrame(test_frame).serialize()

    # We include an almost-valid frame and many stray SoF markers
    uart.data_received(b"\xFE" + b"\xFE" + b"\xFE" + test_frame_bytes[:-1] + b"\x00")
    uart.data_received(b"\xFE\xFE\x00\xFE\x01")
    uart.data_received(b"\xFE" + b"\xFE" + b"\xFE" + test_frame_bytes + b"\x00\x00")

    # We should see the valid frame exactly once
    api.frame_received.assert_called_once_with(test_frame)
