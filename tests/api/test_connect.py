import pytest
import logging
import asyncio

from zigpy_znp.api import ZNP

from ..conftest import (
    FAKE_SERIAL_PORT,
    config_for_port_path,
    BaseServerZNP,
    BlankZStack1CC2531,
)


pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


async def test_connect_no_communication(connected_znp):
    znp, znp_server = connected_znp

    assert znp_server._uart.data_received.call_count == 0


async def test_connect_skip_bootloader(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(FAKE_SERIAL_PORT))

    await znp.connect(test_port=False)

    # Nothing should have been sent except for bootloader skip bytes
    # XXX: `c[-2][0] == c.args[0]`
    data_written = b"".join(c[-2][0] for c in znp_server._uart.data_received.mock_calls)
    assert set(data_written) == {0xEF}
    assert len(data_written) >= 167

    znp.close()


@pytest.mark.parametrize("device", [BlankZStack1CC2531])
@pytest.mark.parametrize("check_version", [True, False])
async def test_connect_old_version(device, check_version, make_znp_server, caplog):
    _ = make_znp_server(server_cls=device)
    znp = ZNP(config_for_port_path(FAKE_SERIAL_PORT))

    if check_version:
        with pytest.raises(RuntimeError):
            await znp.connect(check_version=True)
    else:
        with caplog.at_level(logging.WARNING):
            await znp.connect(check_version=False)

        assert "old version" in caplog.text

    znp.close()


async def wait_for_spy(spy):
    while True:
        if spy.called:
            return

        await asyncio.sleep(0.01)


async def test_api_close(connected_znp, mocker):
    znp, znp_server = connected_znp

    mocker.spy(znp, "connection_lost")
    znp.close()

    await wait_for_spy(znp.connection_lost)

    # connection_lost with no exc indicates the port was closed
    znp.connection_lost.assert_called_once_with(None)

    # Make sure our UART was actually closed
    assert znp._uart is None
    assert znp._app is None

    # ZNP.close should not throw any errors if called multiple times
    znp.close()
    znp.close()

    def dict_minus(d, minus):
        return {k: v for k, v in d.items() if k not in minus}

    # Closing ZNP should reset it completely to that of a fresh object
    # We have to ignore our mocked method and the lock
    znp2 = ZNP(znp._config)
    assert znp2._sync_request_lock.locked() == znp._sync_request_lock.locked()
    assert dict_minus(
        znp.__dict__, ["_sync_request_lock", "connection_lost"]
    ) == dict_minus(znp2.__dict__, ["_sync_request_lock", "connection_lost"])

    znp2.close()
    znp2.close()

    assert dict_minus(
        znp.__dict__, ["_sync_request_lock", "connection_lost"]
    ) == dict_minus(znp2.__dict__, ["_sync_request_lock", "connection_lost"])
