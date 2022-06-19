import asyncio
from unittest.mock import patch

import pytest

import zigpy_znp.config as conf
from zigpy_znp.uart import connect as uart_connect
from zigpy_znp.zigbee.application import ControllerApplication

from ..conftest import FORMED_DEVICES, FormedLaunchpadCC26X2R1


async def test_no_double_connect(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=FormedLaunchpadCC26X2R1)

    app = mocker.Mock()
    await uart_connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port}), app
    )

    with pytest.raises(RuntimeError):
        await uart_connect(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port}), app
        )


async def test_leak_detection(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=FormedLaunchpadCC26X2R1)

    def count_connected():
        return sum(t._is_connected for t in znp_server._transports)

    # Opening and closing one connection will keep the count at zero
    assert count_connected() == 0
    app = mocker.Mock()
    protocol1 = await uart_connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port}), app
    )
    assert count_connected() == 1
    protocol1.close()
    assert count_connected() == 0

    # Once more for good measure
    protocol2 = await uart_connect(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port}), app
    )
    assert count_connected() == 1
    protocol2.close()
    assert count_connected() == 0


async def test_probe_unsuccessful():
    assert not (
        await ControllerApplication.probe(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: "/dev/null"})
        )
    )


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_probe_unsuccessful_slow1(device, make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=device, shorten_delays=False)

    # Don't respond to anything
    znp_server._listeners.clear()

    mocker.patch("zigpy_znp.api.CONNECT_PROBE_TIMEOUT", new=0.1)

    assert not (
        await ControllerApplication.probe(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port})
        )
    )

    assert not any([t._is_connected for t in znp_server._transports])


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_probe_unsuccessful_slow2(device, make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=device, shorten_delays=False)

    # Don't respond to anything
    znp_server._listeners.clear()

    mocker.patch("zigpy_znp.zigbee.application.PROBE_TIMEOUT", new=0.1)

    assert not (
        await ControllerApplication.probe(
            conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port})
        )
    )

    assert not any([t._is_connected for t in znp_server._transports])


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_probe_successful(device, make_znp_server):
    znp_server = make_znp_server(server_cls=device, shorten_delays=False)

    assert await ControllerApplication.probe(
        conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port})
    )
    assert not any([t._is_connected for t in znp_server._transports])


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_probe_multiple(device, make_znp_server):
    # Make sure that our listeners don't get cleaned up after each probe
    znp_server = make_znp_server(server_cls=device, shorten_delays=False)
    znp_server.close = lambda: None

    config = conf.SCHEMA_DEVICE({conf.CONF_DEVICE_PATH: znp_server.serial_port})

    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)
    assert await ControllerApplication.probe(config)
    assert not any([t._is_connected for t in znp_server._transports])


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_reconnect(device, make_application):
    app, znp_server = await make_application(
        server_cls=device,
        client_config={
            # Make auto-reconnection happen really fast
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_AUTO_RECONNECT_RETRY_DELAY: 0.01,
                conf.CONF_SREQ_TIMEOUT: 0.1,
            }
        },
        shorten_delays=False,
    )

    # Start up the server
    await app.startup(auto_form=False)
    assert app._znp is not None

    # Don't reply to anything for a bit
    with patch.object(znp_server, "frame_received", lambda _: None):
        # Now that we're connected, have the server close the connection
        znp_server._uart._transport.close()

        # ZNP should be closed
        assert app._znp is None

        # Wait for more than the SREQ_TIMEOUT to pass, we should still fail to reconnect
        await asyncio.sleep(0.3)

        assert not app._reconnect_task.done()
        assert app._znp is None

    # Our reconnect task should complete a moment after we send the ping reply
    while app._znp is None:
        await asyncio.sleep(0.1)

    assert app._znp is not None
    assert app._znp._uart is not None

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_shutdown_from_app(device, mocker, make_application):
    app, znp_server = await make_application(server_cls=device)

    await app.startup(auto_form=False)

    # It gets deleted but we save a reference to it
    transport = app._znp._uart._transport
    mocker.spy(transport, "close")

    # Close the connection application-side
    await app.shutdown()

    # And the serial connection should have been closed
    assert transport.close.call_count >= 1


async def test_clean_shutdown(make_application):
    app, znp_server = await make_application(server_cls=FormedLaunchpadCC26X2R1)
    await app.startup(auto_form=False)

    # This should not throw
    await app.shutdown()

    assert app._znp is None
    assert app._reconnect_task.cancelled()


async def test_multiple_shutdown(make_application):
    app, znp_server = await make_application(server_cls=FormedLaunchpadCC26X2R1)
    await app.startup(auto_form=False)

    await app.shutdown()
    await app.shutdown()
    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_reconnect_lockup(device, make_application, mocker):
    mocker.patch("zigpy_znp.zigbee.application.WATCHDOG_PERIOD", 0.1)

    app, znp_server = await make_application(
        server_cls=device,
        client_config={
            # Make auto-reconnection happen really fast
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_AUTO_RECONNECT_RETRY_DELAY: 0.01,
                conf.CONF_SREQ_TIMEOUT: 0.1,
            }
        },
    )

    # Start up the server
    await app.startup(auto_form=False)

    # Stop responding
    with patch.object(znp_server, "frame_received", lambda _: None):
        assert app._znp is not None
        assert app._reconnect_task.done()

        # Wait for more than the SREQ_TIMEOUT to pass, the watchdog will notice
        await asyncio.sleep(0.3)

        # We will treat this as a disconnect
        assert app._znp is None
        assert app._watchdog_task.done()
        assert not app._reconnect_task.done()

    # Our reconnect task should complete after that
    while app._znp is None:
        await asyncio.sleep(0.1)

    assert app._znp is not None
    assert app._znp._uart is not None

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_reconnect_lockup_pyserial(device, make_application, mocker):
    mocker.patch("zigpy_znp.zigbee.application.WATCHDOG_PERIOD", 0.1)

    app, znp_server = await make_application(
        server_cls=device,
        client_config={
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_AUTO_RECONNECT_RETRY_DELAY: 0.01,
                conf.CONF_SREQ_TIMEOUT: 0.1,
            }
        },
    )

    # Start up the server
    await app.startup(auto_form=False)

    # On Linux, a connection error during read with queued writes will cause PySerial to
    # swallow the exception. This makes it appear like we intentionally closed the
    # connection.

    # We are connected
    assert app._znp is not None

    did_start_network = asyncio.get_running_loop().create_future()

    async def patched_start_network(old_start_network=app.start_network, **kwargs):
        try:
            return await old_start_network(**kwargs)
        finally:
            did_start_network.set_result(True)

    with patch.object(app, "start_network", patched_start_network):
        # "Drop" the connection like PySerial
        app._znp._uart.connection_lost(exc=None)

        # Wait until we are reconnecting
        await did_start_network

    # "Drop" the connection like PySerial again, but during connect
    app._znp._uart.connection_lost(exc=None)

    # We should reconnect soon
    mocker.spy(app, "_watchdog_loop")

    while app._watchdog_loop.call_count == 0:
        await asyncio.sleep(0.1)

    assert app._znp and app._znp._uart

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_disconnect(device, make_application):
    app, znp_server = await make_application(
        server_cls=device,
        client_config={
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_SREQ_TIMEOUT: 0.1,
            }
        },
    )

    assert app._znp is None
    await app.connect()

    assert app._znp is not None

    await app.disconnect()
    assert app._znp is None

    await app.disconnect()
    await app.disconnect()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_disconnect_failure(device, make_application):
    app, znp_server = await make_application(
        server_cls=device,
        client_config={
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_SREQ_TIMEOUT: 0.1,
            }
        },
    )

    assert app._znp is None
    await app.connect()

    assert app._znp is not None

    with patch.object(app._znp, "reset", side_effect=RuntimeError("An error")):
        # Runs without error
        await app.disconnect()

    assert app._znp is None
