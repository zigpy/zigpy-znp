import random

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.tools.flash_read import main as flash_read
from zigpy_znp.tools.flash_write import main as flash_write, get_firmware_crcs

from ..conftest import BaseServerZNP, CoroutineMock

random.seed(12345)
FAKE_IMAGE_SIZE = 2**10
FAKE_FLASH = bytearray(
    random.getrandbits(FAKE_IMAGE_SIZE * 8).to_bytes(FAKE_IMAGE_SIZE, "little")
)
FAKE_FLASH[c.ubl.IMAGE_CRC_OFFSET : c.ubl.IMAGE_CRC_OFFSET + 2] = get_firmware_crcs(
    FAKE_FLASH
)[1].to_bytes(2, "little")
random.seed()


@pytest.mark.parametrize("reset", [False, True])
async def test_flash_backup_write(reset, make_znp_server, mocker, tmp_path):
    znp_server = make_znp_server(server_cls=BaseServerZNP)

    # It takes too long otherwise
    mocker.patch("zigpy_znp.commands.ubl.IMAGE_SIZE", FAKE_IMAGE_SIZE)

    WRITABLE_FLASH = bytearray(len(FAKE_FLASH))

    znp_server.reply_to(
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

    znp_server.reply_to(request=c.UBL.ReadReq.Req(partial=True), responses=[read_flash])

    znp_server.reply_to(
        request=c.UBL.WriteReq.Req(partial=True), responses=[write_flash]
    )

    znp_server.reply_to(
        request=c.UBL.EnableReq.Req(partial=True),
        responses=[c.UBL.EnableRsp.Callback(Status=c.ubl.BootloaderStatus.SUCCESS)],
    )

    # First we write the flash
    firmware_file = tmp_path / "firmware.bin"
    firmware_file.write_bytes(FAKE_FLASH)

    reset_func = mocker.patch(
        "zigpy_znp.tools.flash_write.nvram_reset", new=CoroutineMock()
    )
    args = [znp_server._port_path, "-i", str(firmware_file)]

    if reset:
        args.append("--reset")

        # Prevent the 5 second delay from causing the unit test to fail
        mocker.patch("zigpy_znp.tools.flash_write.asyncio.sleep", new=CoroutineMock())

    await flash_write(args)

    if reset:
        assert reset_func.call_count == 1
    else:
        assert reset_func.call_count == 0

    # And then make a backup
    backup_file = tmp_path / "backup.bin"
    await flash_read([znp_server._port_path, "-o", str(backup_file)])

    # They should be identical
    assert backup_file.read_bytes() == FAKE_FLASH


async def test_flash_write_bad_crc(make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)

    # It takes too long otherwise
    mocker.patch("zigpy_znp.commands.ubl.IMAGE_SIZE", FAKE_IMAGE_SIZE)

    # Flip the bits in one byte, the CRC should fail
    BAD_FIRMWARE = bytearray(len(FAKE_FLASH))
    BAD_FIRMWARE[FAKE_IMAGE_SIZE - 1] = BAD_FIRMWARE[FAKE_IMAGE_SIZE - 1] ^ 0xFF

    # No communication will happen because the CRC will be invalid
    firmware_file = tmp_path / "bad-firmware.bin"
    firmware_file.write_bytes(BAD_FIRMWARE)

    with pytest.raises(ValueError) as e:
        await flash_write([znp_server._port_path, "-i", str(firmware_file)])

    assert "Firmware CRC is incorrect" in str(e)


async def test_flash_write_bad_size(make_znp_server, tmp_path, mocker):
    znp_server = make_znp_server(server_cls=BaseServerZNP)

    # It takes too long otherwise
    mocker.patch("zigpy_znp.commands.ubl.IMAGE_SIZE", FAKE_IMAGE_SIZE)

    # Add an extra byte
    BAD_FIRMWARE = bytearray(len(FAKE_FLASH))
    BAD_FIRMWARE += b"\xFF"

    # No communication will happen because the CRC will be invalid
    firmware_file = tmp_path / "bad-firmware.bin"
    firmware_file.write_bytes(BAD_FIRMWARE)

    with pytest.raises(ValueError) as e:
        await flash_write([znp_server._port_path, "-i", str(firmware_file)])

    assert "Firmware is the wrong size" in str(e)
