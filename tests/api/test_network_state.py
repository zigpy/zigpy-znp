import logging
from unittest import mock

import pytest
from zigpy.exceptions import FormationFailure

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

from ..conftest import (
    ALL_DEVICES,
    FORMED_DEVICES,
    BaseZStack1CC2531,
    FormedZStack3CC2531,
    FormedLaunchpadCC26X2R1,
)


@pytest.mark.parametrize("to_device", ALL_DEVICES)
@pytest.mark.parametrize("from_device", FORMED_DEVICES)
async def test_state_transfer(from_device, to_device, make_connected_znp):
    formed_znp, _ = await make_connected_znp(server_cls=from_device)

    await formed_znp.load_network_info()
    await formed_znp.disconnect()

    empty_znp, _ = await make_connected_znp(server_cls=to_device)

    await empty_znp.write_network_info(
        network_info=formed_znp.network_info,
        node_info=formed_znp.node_info,
    )
    await empty_znp.load_network_info()

    # Z-Stack 1 devices can't have some security info read out
    if issubclass(from_device, BaseZStack1CC2531):
        assert formed_znp.network_info == empty_znp.network_info.replace(
            stack_specific={},
            metadata=formed_znp.network_info.metadata,
        )
    elif issubclass(to_device, BaseZStack1CC2531):
        assert (
            formed_znp.network_info.replace(
                stack_specific={},
                metadata=empty_znp.network_info.metadata,
            )
            == empty_znp.network_info
        )
    else:
        assert formed_znp.network_info == empty_znp.network_info.replace(
            metadata=formed_znp.network_info.metadata
        )

    assert formed_znp.node_info == empty_znp.node_info.replace(
        version=formed_znp.node_info.version,
        model=formed_znp.node_info.model,
        manufacturer=formed_znp.node_info.manufacturer,
    )


@pytest.mark.parametrize("device", [FormedZStack3CC2531])
async def test_broken_cc2531_load_state(device, make_connected_znp, caplog):
    znp, znp_server = await make_connected_znp(server_cls=device)

    # "Bad" TCLK seed is a TCLK from Z-Stack 1 with the first 16 bytes overwritten
    znp_server._nvram[ExNvIds.LEGACY][
        OsalNvIds.TCLK_SEED
    ] += b"liance092\x00\x00\x00\x00\x00\x00\x00"

    caplog.set_level(logging.ERROR)
    await znp.load_network_info()
    assert "inconsistent" in caplog.text

    await znp.disconnect()


@pytest.mark.parametrize("device", [FormedZStack3CC2531])
async def test_state_write_tclk_zstack3(device, make_connected_znp, caplog):
    formed_znp, _ = await make_connected_znp(server_cls=device)

    await formed_znp.load_network_info()
    await formed_znp.disconnect()

    empty_znp, _ = await make_connected_znp(server_cls=device)

    caplog.set_level(logging.WARNING)
    await empty_znp.write_network_info(
        network_info=formed_znp.network_info.replace(
            tc_link_key=formed_znp.network_info.tc_link_key.replace(
                # Non-standard TCLK
                key=t.KeyData.convert("AA:BB:CC:DD:AA:BB:CC:DD:AA:BB:CC:DD:AA:BB:CC:DD")
            )
        ),
        node_info=formed_znp.node_info,
    )
    assert "TC link key is configured at build time in Z-Stack 3" in caplog.text

    await empty_znp.load_network_info()

    # TCLK was not changed
    assert formed_znp.network_info == empty_znp.network_info


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_write_settings_fast(device, make_connected_znp):
    formed_znp, _ = await make_connected_znp(server_cls=FormedLaunchpadCC26X2R1)
    await formed_znp.load_network_info()
    await formed_znp.disconnect()

    znp, _ = await make_connected_znp(server_cls=device)

    formed_znp.network_info.stack_specific["form_quickly"] = True

    with mock.patch("zigpy_znp.znp.security.write_devices") as mock_write_devices:
        await znp.write_network_info(
            network_info=formed_znp.network_info,
            node_info=formed_znp.node_info,
        )

    # We don't waste time writing device info
    assert len(mock_write_devices.mock_awaits) == 0


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_formation_failure_on_corrupted_nvram(device, make_connected_znp):
    formed_znp, _ = await make_connected_znp(server_cls=FormedLaunchpadCC26X2R1)
    await formed_znp.load_network_info()
    await formed_znp.disconnect()

    znp, znp_server = await make_connected_znp(server_cls=device)

    # Instead of accepting the write, fail
    write_reset_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVWriteExt.Req(
            Id=OsalNvIds.STARTUP_OPTION,
            Offset=0,
            Value=t.ShortBytes(
                (t.StartupOptions.ClearState | t.StartupOptions.ClearConfig).serialize()
            ),
        ),
        responses=[c.SYS.OSALNVWriteExt.Rsp(Status=t.Status.NV_OPER_FAILED)],
        override=True,
    )

    with pytest.raises(FormationFailure):
        await znp.write_network_info(
            network_info=formed_znp.network_info,
            node_info=formed_znp.node_info,
        )

    await write_reset_rsp
