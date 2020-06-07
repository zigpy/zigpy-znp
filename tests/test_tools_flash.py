import random
import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.tools.flash_read import main as flash_read
from zigpy_znp.tools.flash_write import main as flash_write

from test_api import pytest_mark_asyncio_timeout  # noqa: F401
from test_application import znp_server  # noqa: F401
from test_tools_nvram import openable_serial_znp_server  # noqa: F401


random.seed(12345)
FAKE_IMAGE_SIZE = 2 ** 10
FAKE_FLASH = random.getrandbits(FAKE_IMAGE_SIZE * 8).to_bytes(FAKE_IMAGE_SIZE, "little")
random.seed()


@pytest_mark_asyncio_timeout(seconds=5)
async def test_flash_backup_write(
    openable_serial_znp_server, tmp_path, mocker  # noqa: F811
):
    # It takes too long otherwise
    mocker.patch("zigpy_znp.commands.ubl.IMAGE_SIZE", FAKE_IMAGE_SIZE)

    WRITABLE_FLASH = bytearray(len(FAKE_FLASH))

    openable_serial_znp_server.reply_to(
        request=c.UBL.HandshakeReq.Req(partial=True),
        responses=[
            c.UBL.HandshakeRsp.Callback(
                Status=c.ubl.BootloaderStatus.SUCCESS,
                BootloaderRevision=0,
                DeviceType=c.ubl.BootloaderDeviceType.CC2530,
                BufferSize=64,
                PageSize=2048,
                BootloaderCodeRevision=0,
            )
        ],
    )

    def read_flash(req):
        offset = req.FlashWordAddr * 4
        data = WRITABLE_FLASH[offset : offset + 64]

        # We should not read partial blocks
        assert len(data) in (0, 64)

        if not data:
            return c.UBL.ReadRsp.Callback(Status=c.ubl.BootloaderStatus.FAILURE)

        return c.UBL.ReadRsp.Callback(
            Status=c.ubl.BootloaderStatus.SUCCESS,
            FlashWordAddr=req.FlashWordAddr,
            Data=t.TrailingBytes(data),
        )

    def write_flash(req):
        offset = req.FlashWordAddr * 4

        assert len(req.Data) == 64

        WRITABLE_FLASH[offset : offset + 64] = req.Data
        assert len(WRITABLE_FLASH) == FAKE_IMAGE_SIZE

        return c.UBL.WriteRsp.Callback(Status=c.ubl.BootloaderStatus.SUCCESS)

    openable_serial_znp_server.reply_to(
        request=c.UBL.ReadReq.Req(partial=True), responses=[read_flash]
    )

    openable_serial_znp_server.reply_to(
        request=c.UBL.WriteReq.Req(partial=True), responses=[write_flash]
    )

    openable_serial_znp_server.reply_to(
        request=c.UBL.EnableReq.Req(partial=True),
        responses=[c.UBL.EnableRsp.Callback(Status=c.ubl.BootloaderStatus.SUCCESS)],
    )

    # First we write the flash
    firmware_file = tmp_path / "firmware.bin"
    firmware_file.write_bytes(FAKE_FLASH)
    await flash_write([openable_serial_znp_server._port_path, "-i", str(firmware_file)])

    # And then make a backup
    backup_file = tmp_path / "backup.bin"
    await flash_read([openable_serial_znp_server._port_path, "-o", str(backup_file)])

    # They should be identical
    assert backup_file.read_bytes() == FAKE_FLASH
