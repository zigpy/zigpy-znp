import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types import nvids
from zigpy_znp.exceptions import SecurityError

pytestmark = [pytest.mark.asyncio]


async def test_writes_invalid(connected_znp):
    znp, _ = connected_znp

    # Passing in untyped integers is not allowed
    with pytest.raises(TypeError):
        await znp.nvram.osal_write(nvids.OsalNvIds.STARTUP_OPTION, 0xAB)

    # Neither is passing in an empty value
    with pytest.raises(ValueError):
        await znp.nvram.osal_write(nvids.OsalNvIds.STARTUP_OPTION, b"")

    # Or a type that serializes to an empty value
    class Empty:
        def serialize(self):
            return b""

    assert Empty().serialize() == b""

    with pytest.raises(ValueError):
        await znp.nvram.osal_write(nvids.OsalNvIds.STARTUP_OPTION, Empty())


@pytest.mark.parametrize(
    "value",
    [
        (t.StartupOptions.ClearConfig | t.StartupOptions.ClearState),
        (t.StartupOptions.ClearConfig | t.StartupOptions.ClearState).serialize(),
        bytearray(b"\x03"),
    ],
)
async def test_write_existing(connected_znp, value):
    znp, znp_server = connected_znp

    nvid = nvids.OsalNvIds.STARTUP_OPTION

    # The item is one byte long
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=1)],
    )

    write_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVWriteExt.Req(
            Id=nvid, Offset=0, Value=t.ShortBytes(b"\x03")
        ),
        responses=[c.SYS.OSALNVWriteExt.Rsp(Status=t.Status.SUCCESS)],
    )

    await znp.nvram.osal_write(nvid, value)

    await length_rsp
    await write_rsp


async def test_write_same_length(connected_znp):
    znp, znp_server = connected_znp

    nvid = nvids.OsalNvIds.STARTUP_OPTION
    value = b"\x01"

    # The existing item is also one byte long so we will not recreate it
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=1)],
    )

    write_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVWriteExt.Req(
            Id=nvid, Offset=0, Value=t.ShortBytes(b"\x01")
        ),
        responses=[c.SYS.OSALNVWriteExt.Rsp(Status=t.Status.SUCCESS)],
    )

    await znp.nvram.osal_write(nvid, value)

    await length_rsp
    await write_rsp


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"\x01\x02"])
@pytest.mark.parametrize("create", [True, False])
async def test_write_wrong_length(connected_znp, nvid, value, create):
    znp, znp_server = connected_znp

    # Pretend the item is one byte long so we will have to recreate it
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=1)],
    )

    delete_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVDelete.Req(Id=nvid, ItemLen=1),
        responses=[c.SYS.OSALNVDelete.Rsp(Status=t.Status.SUCCESS)],
    )

    init_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVItemInit.Req(Id=nvid, ItemLen=len(value), Value=value),
        responses=[c.SYS.OSALNVItemInit.Rsp(Status=t.Status.NV_ITEM_UNINIT)],
    )

    write_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVWriteExt.Req(Id=nvid, Offset=0, Value=value),
        responses=[c.SYS.OSALNVWriteExt.Rsp(Status=t.Status.SUCCESS)],
    )

    if create:
        await znp.nvram.osal_write(nvid, value, create=True)
        await length_rsp
        await delete_rsp
        await init_rsp
        await write_rsp
    else:
        with pytest.raises(ValueError):
            await znp.nvram.osal_write(nvid, value, create=False)

        await length_rsp
        assert not delete_rsp.done()
        assert not init_rsp.done()
        assert not write_rsp.done()


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"test"])
async def test_write_bad_length(connected_znp, nvid, value):
    znp, znp_server = connected_znp

    # The item is one byte long so we will have to recreate it
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=1)],
    )

    with pytest.raises(ValueError):
        await znp.nvram.osal_write(nvid, value)

    await length_rsp


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"test"])
async def test_read_success(connected_znp, nvid, value):
    znp, znp_server = connected_znp

    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=len(value))],
    )

    read_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVReadExt.Req(Id=nvid, Offset=0),
        responses=[c.SYS.OSALNVReadExt.Rsp(Status=t.Status.SUCCESS, Value=value)],
    )

    result = await znp.nvram.osal_read(nvid)
    await length_rsp
    await read_rsp

    assert result == value


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"test" * 62 + b"x"])  # 248 + 1 bytes, needs two
async def test_read_long_success(connected_znp, nvid, value):
    znp, znp_server = connected_znp

    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=len(value))],
    )

    read_rsp1 = znp_server.reply_once_to(
        request=c.SYS.OSALNVReadExt.Req(Id=nvid, Offset=0),
        responses=[c.SYS.OSALNVReadExt.Rsp(Status=t.Status.SUCCESS, Value=value[:-1])],
    )

    read_rsp2 = znp_server.reply_once_to(
        request=c.SYS.OSALNVReadExt.Req(Id=nvid, Offset=248),
        responses=[c.SYS.OSALNVReadExt.Rsp(Status=t.Status.SUCCESS, Value=b"x")],
    )

    result = await znp.nvram.osal_read(nvid)
    await length_rsp
    await read_rsp1
    await read_rsp2

    assert result == value


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
async def test_read_failure(connected_znp, nvid):
    znp, znp_server = connected_znp

    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=0)],
    )

    with pytest.raises(KeyError):
        await znp.nvram.osal_read(nvid)

    await length_rsp


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.STARTUP_OPTION])
async def test_write_nonexistent(connected_znp, nvid):
    znp, znp_server = connected_znp

    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=0)],
    )

    with pytest.raises(KeyError):
        await znp.nvram.osal_write(nvid, value=b"test", create=False)

    await length_rsp


@pytest.mark.parametrize("nvid", [nvids.OsalNvIds.PRECFGKEY, nvids.OsalNvIds.TCLK_SEED])
@pytest.mark.parametrize("value", [b"keydata"])
async def test_read_security_bypass(connected_znp, nvid, value):
    znp, znp_server = connected_znp
    znp._capabilities |= t.MTCapabilities.CAP_SAPI

    # Length is reported correctly
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=len(value))],
    )

    # But the read will fail
    read_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVReadExt.Req(Id=nvid, Offset=0),
        responses=[
            c.SYS.OSALNVReadExt.Rsp(Status=t.Status.INVALID_PARAMETER, Value=b"")
        ],
    )

    # Only 8-bit IDs can be extracted
    if nvid <= 0xFF:
        sapi_read_rsp = znp_server.reply_once_to(
            request=c.SAPI.ZBReadConfiguration.Req(ConfigId=nvid),
            responses=[
                c.SAPI.ZBReadConfiguration.Rsp(
                    Status=t.Status.SUCCESS, ConfigId=nvid, Value=value
                )
            ],
        )

        result = await znp.nvram.osal_read(nvid)
        assert result == value

        await length_rsp
        await read_rsp
        await sapi_read_rsp
    else:
        with pytest.raises(SecurityError):
            await znp.nvram.osal_read(nvid)

        await length_rsp
        await read_rsp
