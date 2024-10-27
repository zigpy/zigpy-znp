import asyncio
from unittest.mock import call

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP

from ..conftest import BaseServerZNP, CoroutineMock, config_for_port_path


async def test_connect_no_test(make_znp_server):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))

    await znp.connect(test_port=False)

    # Nothing will be sent
    assert znp_server._uart.data_received.call_count == 0

    await znp.disconnect()


@pytest.mark.parametrize("work_after_attempt", [1, 2, 3])
async def test_connect_skip_bootloader(make_znp_server, mocker, work_after_attempt):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))

    mocker.patch.object(znp.nvram, "determine_alignment", new=CoroutineMock())
    mocker.patch.object(znp, "detect_zstack_version", new=CoroutineMock())

    num_pings = 0

    def ping_rsp(req):
        nonlocal num_pings
        num_pings += 1

        # Ignore the first few pings
        if num_pings >= work_after_attempt:
            return c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)

    znp_server.reply_to(c.SYS.Ping.Req(), responses=[ping_rsp])

    await znp.connect(test_port=True)

    await znp.disconnect()


async def test_connect_skip_bootloader_batched_rsp(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))

    mocker.patch.object(znp.nvram, "determine_alignment", new=CoroutineMock())
    mocker.patch.object(znp, "detect_zstack_version", new=CoroutineMock())

    num_pings = 0

    def ping_rsp(req):
        nonlocal num_pings
        num_pings += 1

        if num_pings == 3:
            # CC253x radios sometimes buffer requests until they send a `ResetInd`
            return (
                [
                    c.SYS.ResetInd.Callback(
                        Reason=t.ResetReason.PowerUp,
                        TransportRev=0x00,
                        ProductId=0x12,
                        MajorRel=0x01,
                        MinorRel=0x02,
                        MaintRel=0x03,
                    )
                ]
                + [c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)] * num_pings,
            )
        elif num_pings >= 3:
            return c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)

    znp_server.reply_to(c.SYS.Ping.Req(), responses=[ping_rsp])

    await znp.connect(test_port=True)

    await znp.disconnect()


async def test_connect_skip_bootloader_failure(make_znp_server):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))

    with pytest.raises(asyncio.TimeoutError):
        await znp.connect(test_port=True)

    await znp.disconnect()


async def test_connect_skip_bootloader_rts_dtr_pins(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))

    mocker.patch.object(znp.nvram, "determine_alignment", new=CoroutineMock())
    mocker.patch.object(znp, "detect_zstack_version", new=CoroutineMock())

    znp_server.reply_to(
        c.SYS.Ping.Req(), responses=[c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)]
    )

    await znp.connect(test_port=True)

    serial = znp._uart._transport
    assert serial._mock_dtr_prop.mock_calls == [call(False), call(False), call(False)]
    assert serial._mock_rts_prop.mock_calls == [call(False), call(True), call(False)]

    await znp.disconnect()


async def test_connect_skip_bootloader_config(make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)
    znp = ZNP(config_for_port_path(znp_server.port_path))
    znp._znp_config["skip_bootloader"] = False

    mocker.patch.object(znp.nvram, "determine_alignment", new=CoroutineMock())
    mocker.patch.object(znp, "detect_zstack_version", new=CoroutineMock())

    znp_server.reply_to(
        c.SYS.Ping.Req(), responses=[c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS)]
    )

    await znp.connect(test_port=True)

    serial = znp._uart._transport
    assert serial._mock_dtr_prop.called is False
    assert serial._mock_rts_prop.called is False

    await znp.disconnect()


async def test_api_close(connected_znp, mocker):
    znp, znp_server = connected_znp
    uart = znp._uart
    mocker.spy(uart, "close")

    await znp.disconnect()

    # Make sure our UART was actually closed
    assert znp._uart is None
    assert znp._app is None
    assert uart.close.call_count == 1

    # ZNP.disconnect should not throw any errors if called multiple times
    await znp.disconnect()
    await znp.disconnect()

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

    await znp2.disconnect()
    await znp2.disconnect()

    assert dict_minus(znp.__dict__, ignored_keys) == dict_minus(
        znp2.__dict__, ignored_keys
    )
