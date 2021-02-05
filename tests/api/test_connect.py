import asyncio

import pytest

from zigpy_znp.api import ZNP

from ..conftest import FAKE_SERIAL_PORT, BaseServerZNP, config_for_port_path

pytestmark = [pytest.mark.asyncio]


async def test_connect_no_communication(connected_znp):
    znp, znp_server = connected_znp

    assert znp_server._uart.data_received.call_count == 0


async def test_connect_skip_bootloader(make_znp_server):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(FAKE_SERIAL_PORT))

    await znp.connect(test_port=False)

    # Nothing should have been sent except for bootloader skip bytes
    # NOTE: `c[-2][0]` is `c.args[0]`, just compatible with all Python versions
    data_written = b"".join(c[-2][0] for c in znp_server._uart.data_received.mock_calls)
    assert set(data_written) == {0xEF}
    assert len(data_written) >= 167

    znp.close()


async def wait_for_spy(spy):
    while True:
        if spy.called:
            return

        await asyncio.sleep(0.01)


async def test_api_close(connected_znp, mocker):
    znp, znp_server = connected_znp
    uart = znp._uart
    mocker.spy(uart, "close")

    znp.close()

    # Make sure our UART was actually closed
    assert znp._uart is None
    assert znp._app is None
    assert uart.close.call_count == 1

    # ZNP.close should not throw any errors if called multiple times
    znp.close()
    znp.close()

    def dict_minus(d, minus):
        return {k: v for k, v in d.items() if k not in minus}

    ignored_keys = ["_sync_request_lock", "nvram"]

    # Closing ZNP should reset it completely to that of a fresh object
    # We have to ignore our mocked method and the lock
    znp2 = ZNP(znp._config)
    assert znp2._sync_request_lock.locked() == znp._sync_request_lock.locked()
    assert dict_minus(znp.__dict__, ignored_keys) == dict_minus(
        znp2.__dict__, ignored_keys
    )

    znp2.close()
    znp2.close()

    assert dict_minus(znp.__dict__, ignored_keys) == dict_minus(
        znp2.__dict__, ignored_keys
    )
