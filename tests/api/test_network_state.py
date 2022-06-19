import logging

import pytest

import zigpy_znp.types as t
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

from ..conftest import (
    ALL_DEVICES,
    FORMED_DEVICES,
    BaseZStack1CC2531,
    FormedZStack3CC2531,
)


@pytest.mark.parametrize("to_device", ALL_DEVICES)
@pytest.mark.parametrize("from_device", FORMED_DEVICES)
async def test_state_transfer(from_device, to_device, make_connected_znp):
    formed_znp, _ = await make_connected_znp(server_cls=from_device)

    await formed_znp.load_network_info()
    formed_znp.close()

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

    assert formed_znp.node_info == empty_znp.node_info


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

    znp.close()


@pytest.mark.parametrize("device", [FormedZStack3CC2531])
async def test_state_write_tclk_zstack3(device, make_connected_znp, caplog):
    formed_znp, _ = await make_connected_znp(server_cls=device)

    await formed_znp.load_network_info()
    formed_znp.close()

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
