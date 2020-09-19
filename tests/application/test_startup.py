import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
import zigpy_znp.config as conf

from zigpy_znp.types.nvids import NwkNvIds


from ..conftest import (
    CoroutineMock,
    FormedLaunchpadCC26X2R1,
    FormedZStack3CC2531,
    FormedZStack1CC2531,
    BaseZStack3Device,
    EMPTY_DEVICES,
    FORMED_DEVICES,
    ALL_DEVICES,
)


pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


@pytest.mark.parametrize(
    "device,model,channel,channels,pan_id,ext_pan_id",
    [
        # zigpy-znp
        (
            FormedLaunchpadCC26X2R1,
            "CC13X2/CC26X2, Z-Stack 3.30.00/3.40.00/4.10.00",
            15,
            t.Channels.from_channel_list([15, 20, 25]),
            0x1C0E,
            "ca:4e:c6:ac:c3:c8:63:01",
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
        ),
        # Z2M/zigpy-cc
        (
            FormedZStack1CC2531,
            "CC2531, Z-Stack Home 1.2",
            11,
            t.Channels.from_channel_list([11]),
            0x1A62,
            "dd:dd:dd:dd:dd:dd:dd:dd",
        ),
    ],
)
async def test_info(
    device, model, channel, channels, pan_id, ext_pan_id, make_application
):
    app, znp_server = make_application(server_cls=device)

    # These should not raise any errors even if our NIB is empty
    assert app.pan_id is None
    assert app.ext_pan_id is None
    assert app.channel is None
    assert app.channels is None

    await app.startup(auto_form=False)

    assert app.pan_id == pan_id
    assert app.ext_pan_id == t.EUI64.convert(ext_pan_id)
    assert app.channel == channel

    # XXX: CC2531's channel mask in the NIB is never correct???
    assert app.channels == channels

    assert app.zigpy_device.manufacturer == "Texas Instruments"
    assert app.zigpy_device.model == model

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
    znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK3] = b"\x00"
    znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK1] = b"\x00"

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
    nvram = znp_server.nvram["nwk"]

    # Change NVRAM value we should change it back
    assert nvram[NwkNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()
    nvram[NwkNvIds.LOGICAL_TYPE] = t.DeviceLogicalType.EndDevice.serialize()

    mocker.spy(app, "_reset")
    await app.startup()

    assert nvram[NwkNvIds.LOGICAL_TYPE] == t.DeviceLogicalType.Coordinator.serialize()

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

    set_led_mode = znp_server.reply_once_to(
        request=c.Util.LEDControl.Req(partial=True),
        responses=[c.Util.LEDControl.Rsp(Status=t.Status.SUCCESS)],
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

    if issubclass(device, BaseZStack3Device):
        assert znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK3] == b"\x55"
    else:
        assert znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK1] == b"\x55"

    assert (
        znp_server.nvram["nwk"][NwkNvIds.LOGICAL_TYPE]
        == t.DeviceLogicalType.Coordinator.serialize()
    )
    assert znp_server.nvram["nwk"][NwkNvIds.ZDO_DIRECT_CB] == t.Bool(True).serialize()

    await app.shutdown()
