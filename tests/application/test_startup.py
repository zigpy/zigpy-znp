import pytest

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
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


@pytest.mark.parametrize(
    "device,model,channel,channels,pan_id,ext_pan_id,network_key",
    [
        # zigpy-znp
        (
            FormedLaunchpadCC26X2R1,
            "CC13X2/CC26X2, Z-Stack 3.30.00/3.40.00/4.10.00",
            15,
            t.Channels.from_channel_list([15]),
            0x77AE,
            "24:a2:d7:77:97:47:a7:37",
            t.KeyData.deserialize(bytes.fromhex("c927e9ce1544c9aa42340e4d5dc4c257"))[0],
        ),
        # Z2M/zigpy-cc
        (
            FormedZStack3CC2531,
            "CC2531, Z-Stack 3.0.1/3.0.2",
            11,
            t.Channels.from_channel_list([11]),
            0x1A62,
            # Even though Z2M uses "dd:dd:dd:dd:dd:dd:dd:dd", Wireshark confirms the NIB
            # is correct.
            "00:12:4b:00:0f:ea:8e:05",
            t.KeyData.deserialize(bytes.fromhex("01030507090b0d0f00020406080a0c0d"))[0],
        ),
        # Z2M/zigpy-cc
        (
            FormedZStack1CC2531,
            "CC2531, Z-Stack Home 1.2",
            11,
            t.Channels.from_channel_list([11]),
            0x1A62,
            "dd:dd:dd:dd:dd:dd:dd:dd",
            t.KeyData.deserialize(bytes.fromhex("01030507090b0d0f00020406080a0c0d"))[0],
        ),
    ],
)
async def test_info(
    device, model, channel, channels, pan_id, ext_pan_id, network_key, make_application
):
    app, znp_server = make_application(server_cls=device)

    # These should not raise any errors even if our NIB is empty
    assert app.pan_id is None
    assert app.extended_pan_id is None
    assert app.channel is None
    assert app.channels is None
    assert app.network_key is None

    await app.startup(auto_form=False)

    assert app.pan_id == pan_id
    assert app.extended_pan_id == t.EUI64.convert(ext_pan_id)
    assert app.channel == channel
    assert app.channels == channels
    assert app.network_key == network_key

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
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK3] = b"\x00"
    znp_server.nvram[ExNvIds.LEGACY][OsalNvIds.HAS_CONFIGURED_ZSTACK1] = b"\x00"

    with pytest.raises(RuntimeError):
        await app.startup(auto_form=False)


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_reset(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)

    # `_reset` should be called at least once to put the radio into a consistent state
    mocker.spy(app, "_reset")
    await app.startup()

    assert app._reset.call_count >= 1

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_write_nvram(device, make_application, mocker):
    app, znp_server = make_application(server_cls=device)
    nvram = znp_server.nvram[ExNvIds.LEGACY]

    # Change NVRAM value we should change it back
    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    nvram[OsalNvIds.LOGICAL_TYPE] = t.DeviceLogicalType.EndDevice.serialize()

    mocker.spy(app, "_reset")
    await app.startup()

    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()

    await app.shutdown()


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_tx_power(device, make_application):
    app, znp_server = make_application(
        server_cls=device,
        client_config={conf.CONF_ZNP_CONFIG: {conf.CONF_TX_POWER: 19}},
    )

    set_tx_power = znp_server.reply_once_to(
        request=c.SYS.SetTxPower.Req(TXPower=19),
        responses=[c.SYS.SetTxPower.Rsp(Status=t.Status.SUCCESS)],
    )

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
        request=c.Util.LEDControl.Req(partial=True),
        responses=[]
        if device is FormedLaunchpadCC26X2R1
        else [c.Util.LEDControl.Rsp(Status=t.Status.SUCCESS)],
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

    nvram = znp_server.nvram[ExNvIds.LEGACY]

    if issubclass(device, BaseZStack3Device):
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK3] == b"\x55"
    else:
        assert nvram[OsalNvIds.HAS_CONFIGURED_ZSTACK1] == b"\x55"

    assert nvram[OsalNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    assert nvram[OsalNvIds.ZDO_DIRECT_CB] == t.Bool(True).serialize()

    await app.shutdown()
