import pytest

import zigpy_znp.types as t
import zigpy_znp.config as conf
from zigpy_znp.api import ZNP

from ..conftest import FAKE_SERIAL_PORT, BaseServerZNP


@pytest.fixture
def connected_znp(event_loop, make_znp_server, mocker):
    config = conf.CONFIG_SCHEMA(
        {
            conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: FAKE_SERIAL_PORT},
            conf.CONF_ZNP_CONFIG: {conf.CONF_SKIP_BOOTLOADER: False},
        }
    )

    mocker.patch("zigpy_znp.api.STARTUP_DELAY", 0)

    znp = ZNP(config)
    znp_server = make_znp_server(server_cls=BaseServerZNP)

    event_loop.run_until_complete(znp.connect(test_port=False))
    znp.capabilities = t.MTCapabilities(0)

    yield znp, znp_server

    znp.close()
