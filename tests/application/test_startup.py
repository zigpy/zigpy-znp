import pytest

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

pytestmark = [pytest.mark.asyncio]

DEV_NETWORK_SETTINGS = {
    FormedLaunchpadCC26X2R1: (
        "CC1352/CC2652, Z-Stack 3.30+ (build 20200805)",
        15,
        t.Channels.from_channel_list([15]),
        0x4402,
        t.EUI64.convert("a2:ba:38:a8:b5:e6:83:a0"),
        t.KeyData(bytes.fromhex("4c4e72b8412251799abf35251288ca83")),
    ),
    FormedZStack3CC2531: (
        "CC2531, Z-Stack 3.0.x (build 20190425)",
        15,
        t.Channels.from_channel_list([15]),
        0xB6AB,
        t.EUI64.convert("62:92:32:46:3c:77:2d:b2"),
        t.KeyData(bytes.fromhex("6dde24eae28552b6de2956eb05851afa")),
    ),
    FormedZStack1CC2531: (
        "CC2531, Z-Stack Home 1.2 (build 20190608)",
        11,
        t.Channels.from_channel_list([11]),
        0x1A62,
        t.EUI64.convert("dd:dd:dd:dd:dd:dd:dd:dd"),
        t.KeyData([1, 3, 5, 7, 9, 11, 13, 15, 0, 2, 4, 6, 8, 10, 12, 13]),
    ),
}


# These settings were extracted from beacon requests and key exchanges in Wireshark
@pytest.mark.parametrize(
    "device,model,channel,channels,pan_id,ext_pan_id,network_key",
    [(device_cls,) + settings for device_cls, settings in DEV_NETWORK_SETTINGS.items()],
)
async def test_info(
    device,
    model,
    channel,
    channels,
    pan_id,
    ext_pan_id,
    network_key,
    make_application,
    caplog,
):
    app, znp_server = make_application(server_cls=device)

    # These should not raise any errors even if our NIB is empty
    assert app.pan_id is None
    assert app.extended_pan_id is None
    assert app.channel is None
    assert app.channels is None
    assert app.network_key is None
    assert app.network_key_seq is None

    await app.startup(auto_form=False)

    if network_key == t.KeyData([1, 3, 5, 7, 9, 11, 13, 15, 0, 2, 4, 6, 8, 10, 12, 13]):
        assert "Your network is using the insecure" in caplog.text
    else:
        assert "Your network is using the insecure" not in caplog.text

    assert app.pan_id == pan_id
    assert app.extended_pan_id == ext_pan_id
    assert app.channel == channel
    assert app.channels == channels
    assert app.network_key == network_key
    assert app.network_key_seq == 0

    assert app.zigpy_device.manufacturer == "Texas Instruments"
    assert app.zigpy_device.model == model

    # Anything to make sure it's set
    assert app.zigpy_device.node_desc.maximum_outgoing_transfer_size == 160

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_endpoints(device, make_application):
    app, znp_server = make_application(server_cls=device)

    endpoints = []
    znp_server.callback_for_response(c.AF.Register.Req(partial=True), endpoints.append)

    await app.startup(auto_form=False)

    # We currently just register two endpoints
    assert len(endpoints) == 2
    assert 1 in app.zigpy_device.endpoints
    assert 2 in app.zigpy_device.endpoints

    await app.shutdown()


@pytest.mark.parametrize("device", EMPTY_DEVICES)
async def test_not_configured(device, make_application):
    app, znp_server = make_application(server_cls=device)

    # We cannot start the application if Z-Stack is not configured and without auto_form
    with pytest.raises(RuntimeError):
        await app.startup(auto_form=False)


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_bad_nvram_value(device, make_application):
    app, znp_server = make_application(server_cls=device)

    # An invalid value is still bad
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK3] = b"\x00"
    znp_server._nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK1] = b"\x00"

    with pytest.raises(RuntimeError):
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
async def test_write_nvram(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    nvram = znp_server._nvram[ExNvIds.LEGACY]

    # Change NVRAM value we should change it back
    nvram[OsalNvIds.LOGICAL_TYPE] = t.DeviceLogicalType.EndDevice.serialize()

    assert nvram[OsalNvIds.LOGICAL_TYPE] != t.DeviceLogicalType.Coordinator.serialize()
    await app.startup()
    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()

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
                    c.SYS.SetTxPower.Rsp(StatusOrPower=t.Status.INVALID_PARAMETER)
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


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_led_mode(device, make_application):
    app, znp_server = make_application(
        server_cls=device,
        client_config={conf.CONF_ZNP_CONFIG: {conf.CONF_LED_MODE: "off"}},
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

    assert led_req.Mode == c.util.LEDMode.OFF
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

    assert app.channel is None
    assert app.channels is None

    await app.startup(auto_form=True)

    assert app.channel is not None
    assert app.channels is not None

    nvram = znp_server._nvram[ExNvIds.LEGACY]

    if issubclass(device, BaseZStack3Device):
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK3] == b"\x55"
    else:
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK1] == b"\x55"

    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    assert nvram[OsalNvIds.ZDO_DIRECT_CB] == t.Bool(True).serialize()

    await app.shutdown()
