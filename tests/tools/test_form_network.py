import pytest

from zigpy_znp.types.nvids import ExNvIds, OsalNvIds
from zigpy_znp.tools.form_network import main as form_network

from ..conftest import ALL_DEVICES, EMPTY_DEVICES


@pytest.mark.asyncio
@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_form_network(device, make_znp_server):
    znp_server = make_znp_server(server_cls=device)
    legacy = znp_server._nvram[ExNvIds.LEGACY]

    if device in EMPTY_DEVICES:
        assert OsalNvIds.HAS_CONFIGURED_ZSTACK1 not in legacy
        assert OsalNvIds.HAS_CONFIGURED_ZSTACK3 not in legacy

    await form_network([znp_server._port_path])

    assert (
        OsalNvIds.HAS_CONFIGURED_ZSTACK1 in legacy
        or OsalNvIds.HAS_CONFIGURED_ZSTACK3 in legacy
    )
