import pytest
import voluptuous as vol
from zigpy.exceptions import NetworkNotFormed

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.exceptions import InvalidCommandResponse
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

from ..conftest import (
    ALL_DEVICES,
    EMPTY_DEVICES,
    FORMED_DEVICES,
    CoroutineMock,
    BaseZStack3Device,
    FormedZStack1CC2531,
    FormedZStack3CC2531,
    FormedLaunchpadCC26X2R1,
)

DEV_NETWORK_SETTINGS = {
    FormedLaunchpadCC26X2R1: (
        "CC2652",
        f"Z-Stack {FormedLaunchpadCC26X2R1.code_revision}",
        15,
        t.Channels.from_channel_list([15]),
        0x4402,
        t.EUI64.convert("A2:BA:38:A8:B5:E6:83:A0"),
        t.KeyData.convert("4C:4E:72:B8:41:22:51:79:9A:BF:35:25:12:88:CA:83"),
    ),
    FormedZStack3CC2531: (
        "CC2531",
        f"Z-Stack 3.0.x {FormedZStack3CC2531.code_revision}",
        15,
        t.Channels.from_channel_list([15]),
        0xB6AB,
        t.EUI64.convert("62:92:32:46:3C:77:2D:B2"),
        t.KeyData.convert("6D:DE:24:EA:E2:85:52:B6:DE:29:56:EB:05:85:1A:FA"),
    ),
    FormedZStack1CC2531: (
        "CC2531",
        f"Z-Stack Home 1.2 {FormedZStack1CC2531.code_revision}",
        11,
        t.Channels.from_channel_list([11]),
        0x1A62,
        t.EUI64.convert("DD:DD:DD:DD:DD:DD:DD:DD"),
        t.KeyData([1, 3, 5, 7, 9, 11, 13, 15, 0, 2, 4, 6, 8, 10, 12, 13]),
    ),
}


# These settings were extracted from beacon requests and key exchanges in Wireshark
@pytest.mark.parametrize(
    "device,model,version,channel,channels,pan_id,ext_pan_id,network_key",
    [(device_cls,) + settings for device_cls, settings in DEV_NETWORK_SETTINGS.items()],
)
async def test_info(
    device,
    model,
    version,
    channel,
    channels,
    pan_id,
    ext_pan_id,
    network_key,
    make_application,
    caplog,
):
    app, znp_server = make_application(server_cls=device)

    await app.startup(auto_form=False)

    if network_key == t.KeyData([1, 3, 5, 7, 9, 11, 13, 15, 0, 2, 4, 6, 8, 10, 12, 13]):
        assert "Your network is using the insecure" in caplog.text
    else:
        assert "Your network is using the insecure" not in caplog.text

    assert app.state.network_info.pan_id == pan_id
    assert app.state.network_info.extended_pan_id == ext_pan_id
    assert app.state.network_info.channel == channel
    assert app.state.network_info.channel_mask == channels
    assert app.state.network_info.network_key.key == network_key
    assert app.state.network_info.network_key.seq == 0

    assert app.state.node_info.manufacturer == "Texas Instruments"
    assert app.state.node_info.model == model
    assert app.state.node_info.version == version

    # Anything to make sure it's set
    assert app._device.node_desc.maximum_outgoing_transfer_size == 160

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_endpoints(device, make_application):
    app, znp_server = make_application(server_cls=device)

    endpoints = []
    znp_server.callback_for_response(c.AF.Register.Req(partial=True), endpoints.append)

    await app.startup(auto_form=False)

    # We currently just register two endpoints
    assert len(endpoints) == 2
    assert 1 in app._device.endpoints
    assert 2 in app._device.endpoints

    await app.shutdown()


@pytest.mark.parametrize("device", EMPTY_DEVICES)
async def test_not_configured(device, make_application):
    app, znp_server = make_application(server_cls=device)

    # We cannot start the application if Z-Stack is not configured and without auto_form
    with pytest.raises(NetworkNotFormed):
        await app.startup(auto_form=False)


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_reset(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    # `_reset` should be called at least once to put the radio into a consistent state
    mocker.spy(ZNP, "reset")
    assert ZNP.reset.call_count == 0
    await app.startup()
    assert ZNP.reset.call_count >= 1

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
@pytest.mark.parametrize("succeed", [True, False])
async def test_tx_power(device, succeed, make_application):
    app, znp_server = make_application(
        server_cls=device,
        client_config={conf.CONF_ZNP_CONFIG: {conf.CONF_TX_POWER: 19}},
    )

    if device.version == 3.30:
        if succeed:
            set_tx_power = znp_server.reply_once_to(
                request=c.SYS.SetTxPower.Req(TXPower=19),
                responses=[c.SYS.SetTxPower.Rsp(StatusOrPower=t.Status.SUCCESS)],
            )
        else:
            set_tx_power = znp_server.reply_once_to(
                request=c.SYS.SetTxPower.Req(TXPower=19),
                responses=[
                    c.SYS.SetTxPower.Rsp(
                        StatusOrPower=t.Status.MAC_INVALID_PARAMETER - 0xFF - 1
                    )
                ],
            )
    else:
        if succeed:
            set_tx_power = znp_server.reply_once_to(
                request=c.SYS.SetTxPower.Req(TXPower=19),
                responses=[c.SYS.SetTxPower.Rsp(StatusOrPower=19)],
            )
        else:
            set_tx_power = znp_server.reply_once_to(
                request=c.SYS.SetTxPower.Req(TXPower=19),
                responses=[c.SYS.SetTxPower.Rsp(StatusOrPower=-1)],  # adjusted
            )

    if device.version == 3.30 and not succeed:
        with pytest.raises(InvalidCommandResponse):
            await app.startup(auto_form=False)

        await set_tx_power
    else:
        await app.startup(auto_form=False)
        await set_tx_power

    await app.shutdown()


@pytest.mark.parametrize("led_mode", ["off", False, "on", True])
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_led_mode(device, led_mode, make_application):
    app, znp_server = make_application(
        server_cls=device,
        client_config={conf.CONF_ZNP_CONFIG: {conf.CONF_LED_MODE: led_mode}},
    )

    # Z-Stack just does not respond to this command if HAL_LED is not enabled
    # It does not send the usual "command not recognized" response
    set_led_mode = znp_server.reply_once_to(
        request=c.UTIL.LEDControl.Req(partial=True),
        responses=[]
        if device is FormedLaunchpadCC26X2R1
        else [c.UTIL.LEDControl.Rsp(Status=t.Status.SUCCESS)],
    )

    await app.startup(auto_form=False)
    led_req = await set_led_mode

    if led_mode in ("off", False):
        assert led_req.Mode == c.util.LEDMode.OFF
    else:
        assert led_req.Mode == c.util.LEDMode.ON

    assert led_req.LED == 0xFF

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_auto_form_unnecessary(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    mocker.patch.object(app, "form_network", new=CoroutineMock())

    await app.startup(auto_form=True)

    assert app.form_network.call_count == 0

    await app.shutdown()


@pytest.mark.parametrize("device", EMPTY_DEVICES)
async def test_auto_form_necessary(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    assert app.state.network_info.channel == 0
    assert app.state.network_info.channel_mask == t.Channels.NO_CHANNELS

    await app.startup(auto_form=True)

    assert app.state.network_info.channel != 0
    assert app.state.network_info.channel_mask != t.Channels.NO_CHANNELS

    nvram = znp_server._nvram[ExNvIds.LEGACY]

    if issubclass(device, BaseZStack3Device):
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK3] == b"\x55"
    else:
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK1] == b"\x55"

    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    assert nvram[OsalNvIds.ZDO_DIRECT_CB] == t.Bool(True).serialize()

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedZStack1CC2531])
async def test_zstack_build_id_empty(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    znp_server.reply_to(
        c.SYS.Version.Req(),
        responses=c.SYS.Version.Rsp(
            TransportRev=2,
            ProductId=0,
            MajorRel=2,
            MinorRel=6,
            MaintRel=3,
            # These are missing
            CodeRevision=None,
            BootloaderBuildType=None,
            BootloaderRevision=None,
        ),
        override=True,
    )

    await app.startup(auto_form=True)

    assert app._zstack_build_id is not None
    assert app._zstack_build_id == 0x00000000

    await app.shutdown()


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_deprecated_concurrency_config(device, make_application):
    with pytest.raises(vol.MultipleInvalid) as exc:
        app, znp_server = make_application(
            server_cls=device,
            client_config={
                conf.CONF_ZNP_CONFIG: {
                    conf.CONF_MAX_CONCURRENT_REQUESTS: 16,
                }
            },
        )

    assert "max_concurrent_requests" in str(exc.value)


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_reset_network_info(device, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.connect()
    await app.reset_network_info()

    with pytest.raises(NetworkNotFormed):
        await app.start_network()


@pytest.mark.parametrize(
    "device, concurrency",
    [
        (FormedLaunchpadCC26X2R1, 16),
        (FormedZStack1CC2531, 2),
    ],
)
async def test_concurrency_auto_config(device, concurrency, make_application):
    app, znp_server = make_application(server_cls=device)
    await app.connect()
    await app.start_network()

    assert app._concurrent_requests_semaphore.max_value == concurrency
