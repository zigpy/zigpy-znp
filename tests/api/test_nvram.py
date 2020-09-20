import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.types import nvids


pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


async def test_wrong_order(connected_znp, event_loop):
    znp, _ = connected_znp

    class TestNvIds(nvids.BaseNvIds):
        SECOND = 0x0002
        FIRST = 0x0001
        LAST = 0x0004
        THIRD = 0x0003

    # Writing too big of a value should fail, regardless of the definition order
    with pytest.raises(ValueError):
        await znp.nvram_write(TestNvIds.THIRD, t.uint16_t(0xAABB))


async def test_writes_invalid(connected_znp):
    znp, _ = connected_znp

    # Passing numerical addresses is disallowed
    with pytest.raises(ValueError):
        await znp.nvram_write(0x0003, t.uint8_t(0xAB))

    # So is passing in untyped integers
    with pytest.raises(TypeError):
        await znp.nvram_write(nvids.NwkNvIds.STARTUP_OPTION, 0xAB)


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

    nvid = nvids.NwkNvIds.STARTUP_OPTION

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

    await znp.nvram_write(nvid, value)

    await length_rsp
    await write_rsp


async def test_write_same_length(connected_znp):
    znp, znp_server = connected_znp

    nvid = nvids.NwkNvIds.STARTUP_OPTION
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

    await znp.nvram_write(nvid, value)

    await length_rsp
    await write_rsp


@pytest.mark.parametrize("nvid", [nvids.NwkNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"\x01\x02"])
async def test_write_wrong_length(connected_znp, nvid, value):
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

    await znp.nvram_write(nvid, value, create=True)

    await length_rsp
    await delete_rsp
    await init_rsp
    await write_rsp


@pytest.mark.parametrize("nvid", [nvids.NwkNvIds.STARTUP_OPTION])
@pytest.mark.parametrize("value", [b"test"])
async def test_write_bad_length(connected_znp, nvid, value):
    znp, znp_server = connected_znp

    # The item is one byte long so we will have to recreate it
    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=1)],
    )

    with pytest.raises(ValueError):
        await znp.nvram_write(nvid, value)

    await length_rsp


@pytest.mark.parametrize("nvid", [nvids.NwkNvIds.STARTUP_OPTION])
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

    result = await znp.nvram_read(nvid)
    await length_rsp
    await read_rsp

    assert result == value


@pytest.mark.parametrize("nvid", [nvids.NwkNvIds.STARTUP_OPTION])
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

    result = await znp.nvram_read(nvid)
    await length_rsp
    await read_rsp1
    await read_rsp2

    assert result == value


@pytest.mark.parametrize("nvid", [nvids.NwkNvIds.STARTUP_OPTION])
async def test_read_failure(connected_znp, nvid):
    znp, znp_server = connected_znp

    length_rsp = znp_server.reply_once_to(
        request=c.SYS.OSALNVLength.Req(Id=nvid),
        responses=[c.SYS.OSALNVLength.Rsp(ItemLen=0)],
    )

    with pytest.raises(KeyError):
        await znp.nvram_read(nvid)

    await length_rsp
