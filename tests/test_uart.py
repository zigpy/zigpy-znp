import pytest

from unittest import mock

import zigpy_znp.types as t
import zigpy_znp.commands as c
import zigpy_znp.config as conf

from zigpy_znp import uart as znp_uart
from zigpy_znp.frames import TransportFrame

from serial_asyncio import SerialTransport
from serial.tools.list_ports_common import ListPortInfo

from test_api import pytest_mark_asyncio_timeout


def test_uart_rx_basic():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_str_repr():
    uart = znp_uart.ZnpMtProtocol(mock.Mock())
    str(uart)
    repr(uart)


def test_uart_rx_byte_by_byte():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_byte_by_byte_garbage():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_big_garbage():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    api.frame_received.assert_called_once_with(test_frame)


def test_uart_rx_corrupted_fcs():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    assert not api.frame_received.called


def test_uart_rx_sof_stress():
    api = mock.Mock()
    transport = mock.Mock()

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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
    api.frame_received.assert_called_once_with(test_frame)


def test_uart_frame_received_error():
    transport = mock.Mock()

    api = mock.Mock()
    api.frame_received = mock.Mock(side_effect=RuntimeError("An error"))

    with pytest.raises(RuntimeError):
        api.frame_received(None)

    uart = znp_uart.ZnpMtProtocol(api)
    uart.connection_made(transport)

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

    # Errors thrown by api.frame_received should not impact how many frames are handled
    uart.data_received(test_frame_bytes * 3)

    # We should have received all three frames
    api.frame_received.call_count == 3


PORT_INFO = [
    {
        "device": "/dev/ttyUSB1",
        "name": "ttyUSB1",
        "description": "HubZ Smart Home Controller",
        "hwid": "USB VID:PID=10C4:8A2A SER=C0F0034E LOCATION=3-1.2.3:1.1",
        "vid": 4292,
        "pid": 35370,
        "serial_number": "C0F0034E",
        "location": "3-1.2.3:1.1",
        "manufacturer": "Silicon Labs",
        "product": "HubZ Smart Home Controller",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.1/ttyUSB1",  # noqa: E501
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.1",  # noqa: E501
    },
    {
        "device": "/dev/ttyUSB0",
        "name": "ttyUSB0",
        "description": "HubZ Smart Home Controller",
        "hwid": "USB VID:PID=10C4:8A2A SER=C0F0034E LOCATION=3-1.2.3:1.0",
        "vid": 4292,
        "pid": 35370,
        "serial_number": "C0F0034E",
        "location": "3-1.2.3:1.0",
        "manufacturer": "Silicon Labs",
        "product": "HubZ Smart Home Controller",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.0/ttyUSB0",  # noqa: E501
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.0",  # noqa: E501
    },
    {
        "device": "/dev/ttyACM1",
        "name": "ttyACM1",
        "description": "XDS110 (03.00.00.05) Embed with CMSIS-DAP",
        "hwid": "USB VID:PID=0451:BEF3 SER=L1100H86 LOCATION=3-1.2.2:1.3",
        "vid": 1105,
        "pid": 48883,
        "serial_number": "L1100H86",
        "location": "3-1.2.2:1.3",
        "manufacturer": "Texas Instruments",
        "product": "XDS110 (03.00.00.05) Embed with CMSIS-DAP",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2/3-1.2.2:1.3",  # noqa: E501
        "subsystem": "usb",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2/3-1.2.2:1.3",  # noqa: E501
    },
    {
        "device": "/dev/ttyACM0",
        "name": "ttyACM0",
        "description": "XDS110 (03.00.00.05) Embed with CMSIS-DAP",
        "hwid": "USB VID:PID=0451:BEF3 SER=L1100H86 LOCATION=3-1.2.2:1.0",
        "vid": 1105,
        "pid": 48883,
        "serial_number": "L1100H86",
        "location": "3-1.2.2:1.0",
        "manufacturer": "Texas Instruments",
        "product": "XDS110 (03.00.00.05) Embed with CMSIS-DAP",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2/3-1.2.2:1.0",  # noqa: E501
        "subsystem": "usb",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.2/3-1.2.2:1.0",  # noqa: E501
    },
    {
        "device": "/dev/zwave",
        "name": "ttyUSB0",
        "description": "HubZ Smart Home Controller",
        "hwid": "USB VID:PID=10C4:8A2A SER=C0F0034E LOCATION=3-1.2.3:1.0 LINK=/dev/ttyUSB0",  # noqa: E501
        "vid": 4292,
        "pid": 35370,
        "serial_number": "C0F0034E",
        "location": "3-1.2.3:1.0",
        "manufacturer": "Silicon Labs",
        "product": "HubZ Smart Home Controller",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.0/ttyUSB0",  # noqa: E501
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.0",  # noqa: E501
    },
    {
        "device": "/dev/zigbee",
        "name": "ttyUSB1",
        "description": "HubZ Smart Home Controller",
        "hwid": "USB VID:PID=10C4:8A2A SER=C0F0034E LOCATION=3-1.2.3:1.1 LINK=/dev/ttyUSB1",  # noqa: E501
        "vid": 4292,
        "pid": 35370,
        "serial_number": "C0F0034E",
        "location": "3-1.2.3:1.1",
        "manufacturer": "Silicon Labs",
        "product": "HubZ Smart Home Controller",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.1/ttyUSB1",  # noqa: E501
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.3/3-1.2.3:1.1",  # noqa: E501
    },
]


def comports_from_dicts(info_dicts):
    ports = []

    for info_dict in info_dicts:
        info = ListPortInfo()

        for key, value in info_dict.items():
            setattr(info, key, value)

        ports.append(info)

    return ports


def test_guess_port():
    with mock.patch(
        "zigpy_znp.uart.list_com_ports", return_value=comports_from_dicts(PORT_INFO)
    ):
        assert znp_uart.guess_port() == "/dev/ttyACM0"

    # The order should not matter
    with mock.patch(
        "zigpy_znp.uart.list_com_ports",
        return_value=comports_from_dicts(PORT_INFO[::-1]),
    ):
        assert znp_uart.guess_port() == "/dev/ttyACM0"

    with mock.patch(
        "zigpy_znp.uart.list_com_ports", return_value=comports_from_dicts([])
    ):
        with pytest.raises(RuntimeError):
            znp_uart.guess_port()


@pytest_mark_asyncio_timeout()
async def test_connect_auto(mocker):
    device = "/dev/ttyACM0"

    def dummy_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        fut = loop.create_future()
        assert url == device

        transport = mock.Mock()
        protocol = protocol_factory()
        protocol.connection_made(transport)

        fut.set_result((transport, protocol))

        return fut

    mocker.patch("zigpy_znp.uart.guess_port", return_value=device)
    mocker.patch("serial_asyncio.create_serial_connection", new=dummy_serial_conn)

    api = mock.Mock()
    await znp_uart.connect(conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: "auto"}), api=api)


@pytest_mark_asyncio_timeout()
async def test_connection_lost(mocker, event_loop):
    device = "/dev/ttyACM0"
    serial_interface = mock.Mock()

    def dummy_serial_conn(loop, protocol_factory, url, *args, **kwargs):
        fut = loop.create_future()
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

    mocker.patch("serial_asyncio.create_serial_connection", new=dummy_serial_conn)

    api = mock.Mock()
    conn_lost_fut = event_loop.create_future()
    api.connection_lost = conn_lost_fut.set_result

    protocol = await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=api
    )

    exception = RuntimeError("Uh oh, something broke")
    protocol.connection_lost(exception)

    # Losing a connection propagates up to the api
    assert (await conn_lost_fut) == exception

    api.reset_mock()
    conn_closed_fut = event_loop.create_future()
    api.connection_lost = conn_closed_fut.set_result

    protocol = await znp_uart.connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: device}), api=api
    )
    protocol.close()

    # Closing a connection does as well
    assert (await conn_closed_fut) is None
