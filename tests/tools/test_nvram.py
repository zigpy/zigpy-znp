import json
import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.types.nvids import NwkNvIds

from zigpy_znp.tools.nvram_read import main as nvram_read
from zigpy_znp.tools.nvram_write import main as nvram_write
from zigpy_znp.tools.nvram_reset import main as nvram_reset


from ..conftest import ALL_DEVICES


pytestmark = [pytest.mark.timeout(3), pytest.mark.asyncio]


def not_recognized(req):
    return c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=req.header
    )


def dump_nvram(znp):
    obj = {
        "nwk": {k.name: v.hex() for k, v in znp.nvram["nwk"].items()},
        "osal": {k.name: v.hex() for k, v in znp.nvram["osal"].items()},
    }

    if znp.nib is not None:
        obj["nwk"]["NIB"] = znp.nib.serialize().hex()

    return obj


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_read(device, make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=device)

    # Make one reaaally long, requiring multiple writes to read it
    znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK3] = b"\xFF" * 300

    # XXX: this is not a great way to do it but deepcopy won't work here
    old_nvram_repr = repr(znp_server.nvram)

    backup_file = tmp_path / "backup.json"
    await nvram_read([znp_server._port_path, "-o", str(backup_file), "-vvv"])

    # No NVRAM was modified during the read
    assert repr(znp_server.nvram) == old_nvram_repr

    # The backup JSON written to disk should be an exact copy
    assert json.loads(backup_file.read_text()) == dump_nvram(znp_server)

    znp_server.close()


@pytest.mark.timeout(5)
@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_write(device, make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=device)

    # Create a dummy backup
    backup = dump_nvram(znp_server)

    # Change some values
    backup["nwk"]["HAS_CONFIGURED_ZSTACK1"] = "ff"

    # Make one with a long value
    backup["nwk"]["HAS_CONFIGURED_ZSTACK3"] = "ffee" * 400

    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup))

    # And clear out all of our NVRAM
    znp_server.nvram["nwk"].clear()
    znp_server.nvram["osal"].clear()

    # This has a differing length
    znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK1] = b"\xEE\xEE"

    # This already exists
    znp_server.nvram["nwk"][NwkNvIds.HAS_CONFIGURED_ZSTACK3] = b"\xBB"

    await nvram_write([znp_server._port_path, "-i", str(backup_file)])

    nvram_obj = dump_nvram(znp_server)

    # XXX: should we check that the NVRAMs are *identical*, or that every item in the
    #      backup was completely restored?
    for key, d in backup.items():
        for item, value in d.items():
            # The NIB is handled differently within tests
            if item == "NIB":
                continue

            assert nvram_obj[key][item] == value

    znp_server.close()


@pytest.mark.parametrize("device", ALL_DEVICES)
async def test_nvram_reset(device, make_znp_server, mocker):
    znp_server = make_znp_server(server_cls=device)

    # So we know when it has been changed
    znp_server.nvram["nwk"][NwkNvIds.STARTUP_OPTION] = b"\xFF"

    await nvram_reset([znp_server._port_path])

    # We've instructed Z-Stack to reset on next boot
    znp_server.nvram["nwk"][NwkNvIds.STARTUP_OPTION] = (
        t.StartupOptions.ClearConfig | t.StartupOptions.ClearState
    ).serialize()

    # And none of the "CONFIGURED" values exist
    assert NwkNvIds.HAS_CONFIGURED_ZSTACK1 not in znp_server.nvram["nwk"]
    assert NwkNvIds.HAS_CONFIGURED_ZSTACK3 not in znp_server.nvram["nwk"]

    znp_server.close()
