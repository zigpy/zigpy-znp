import pytest

from contextlib import contextmanager
from serial.tools.list_ports_common import ListPortInfo

from zigpy_znp import uart as znp_uart


COMMON_LINUX = [
    # HUSBZB-1's Z-Wave serial
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
]

LAUNCHXL_LINUX_PATH = "/dev/ttyACM0"
LAUNCHXL_LINUX = [
    # LAUNCHXL debugger
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
    # LAUNCHXL
    {
        "device": LAUNCHXL_LINUX_PATH,
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
]

ZZH_LINUX_PATH = "/dev/ttyUSB2"
ZZH_LINUX = [
    # ZZH
    {
        "device": ZZH_LINUX_PATH,
        "name": "ttyUSB2",
        "description": "USB2.0-Serial",
        "hwid": "USB VID:PID=1A86:7523 LOCATION=3-1.2.4",
        "vid": 0x1A86,
        "pid": 0x7523,
        "serial_number": None,
        "location": "3-1.2.4",
        "manufacturer": None,
        "product": "USB2.0-Serial",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.4",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.4/3-1.2.4:1.0/ttyUSB0",  # noqa: E501
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.4/3-1.2.4:1.0",  # noqa: E501
    }
]

CC2531_LINUX_PATH = "/dev/ttyACM2"
CC2531_LINUX = [
    # CC2531
    {
        "device": CC2531_LINUX_PATH,
        "name": "ttyACM2",
        "description": "TI CC2531 USB CDC",
        "hwid": "USB VID:PID=0451:16A8 SER=__0X00124B001CCE3385 LOCATION=3-1.2.1.3:1.0",
        "vid": 0x0451,
        "pid": 0x16A8,
        "serial_number": "__0X00124B001CCE3385",
        "location": "3-1.2.1.3:1.0",
        "manufacturer": "Texas Instruments",
        "product": "TI CC2531 USB CDC",
        "interface": None,
        "usb_device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.1/3-1.2.1.3",  # noqa: E501
        "device_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.1/3-1.2.1.3/3-1.2.1.3:1.0",  # noqa: E501
        "subsystem": "usb",
        "usb_interface_path": "/sys/devices/platform/soc/soc:usb3-0/12000000.dwc3/xhci-hcd.3.auto/usb3/3-1/3-1.2/3-1.2.1/3-1.2.1.3/3-1.2.1.3:1.0",  # noqa: E501
    }
]

SLAESH_CC25RB_LINUX_PATH = "/dev/ttyUSB3"
SLAESH_CC25RB_LINUX = [
    # slae.sh cc2652rb stick
    {
        "device": "/dev/ttyUSB3",
        "name": "ttyUSB3",
        "description": "slae.sh cc2652rb stick - slaesh's iot stuff",
        "hwid": "USB VID:PID=10C4:EA60 SER=00_12_4B_00_21_CB_F0_61 LOCATION=1-3",
        "vid": 4292,
        "pid": 60000,
        "serial_number": "00_12_4B_00_21_CB_F0_61",
        "location": "1-3",
        "manufacturer": "Silicon Labs",
        "product": "slae.sh cc2652rb stick - slaesh's iot stuff",
        "interface": None,
        "usb_device_path": "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-3",
        "device_path": "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3:1.0/ttyUSB3",
        "subsystem": "usb-serial",
        "usb_interface_path": "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-3/1-3:1.0",
    },
]


@pytest.fixture
def mock_ports(mocker):
    @contextmanager
    def manager(port_dicts):
        ports = []

        for info_dict in port_dicts:
            info = ListPortInfo()

            for key, value in info_dict.items():
                setattr(info, key, value)

            ports.append(info)

        mocker.patch("zigpy_znp.uart.list_com_ports", return_value=ports)
        yield

    return manager


def test_guess_port_no_ti_radios(mock_ports):
    with mock_ports(COMMON_LINUX):
        with pytest.raises(RuntimeError):
            znp_uart.guess_port()

    with mock_ports([]):
        with pytest.raises(RuntimeError):
            znp_uart.guess_port()


def test_guess_port_launchxl(mock_ports):
    # Order shouldn't matter
    with mock_ports(COMMON_LINUX + LAUNCHXL_LINUX):
        assert znp_uart.guess_port() == LAUNCHXL_LINUX_PATH

    with mock_ports(LAUNCHXL_LINUX + COMMON_LINUX):
        assert znp_uart.guess_port() == LAUNCHXL_LINUX_PATH

    with mock_ports((LAUNCHXL_LINUX + COMMON_LINUX)[::-1]):
        assert znp_uart.guess_port() == LAUNCHXL_LINUX_PATH


def test_guess_port_cc2531(mock_ports):
    with mock_ports(COMMON_LINUX + CC2531_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH


def test_guess_port_zzh(mock_ports):
    with mock_ports(COMMON_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == ZZH_LINUX_PATH


def test_guess_port_zzh_and_cc2531(mock_ports):
    # CH340 is never picked if another radio exists
    with mock_ports(COMMON_LINUX + ZZH_LINUX + CC2531_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH

    with mock_ports(ZZH_LINUX + COMMON_LINUX + CC2531_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH

    with mock_ports(CC2531_LINUX + COMMON_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH


def test_guess_port_all(mock_ports):
    # If there are duplicates then the first one is picked, but never the CH340
    with mock_ports(COMMON_LINUX + CC2531_LINUX + LAUNCHXL_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH

    with mock_ports(ZZH_LINUX + COMMON_LINUX + CC2531_LINUX + LAUNCHXL_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH

    with mock_ports(COMMON_LINUX + LAUNCHXL_LINUX + CC2531_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == LAUNCHXL_LINUX_PATH

    with mock_ports(COMMON_LINUX + SLAESH_CC25RB_LINUX + CC2531_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == SLAESH_CC25RB_LINUX_PATH


def test_guess_port_cp210x(mock_ports):
    # Bare CP210x should be treated like the CH340
    no_product_slasesh = SLAESH_CC25RB_LINUX[0].copy()
    no_product_slasesh["product"] = ""

    with mock_ports(COMMON_LINUX + ZZH_LINUX + [no_product_slasesh]):
        assert znp_uart.guess_port() == ZZH_LINUX_PATH

    with mock_ports(COMMON_LINUX + [no_product_slasesh] + ZZH_LINUX):
        assert znp_uart.guess_port() == SLAESH_CC25RB_LINUX_PATH

    with mock_ports(COMMON_LINUX + ZZH_LINUX + [no_product_slasesh] + CC2531_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH

    with mock_ports(COMMON_LINUX + [no_product_slasesh] + CC2531_LINUX + ZZH_LINUX):
        assert znp_uart.guess_port() == CC2531_LINUX_PATH
