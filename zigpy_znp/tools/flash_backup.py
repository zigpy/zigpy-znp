import sys
import asyncio
import logging
import argparse
import coloredlogs
import async_timeout

import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA

coloredlogs.install(level=logging.DEBUG)
logging.getLogger("zigpy_znp").setLevel(logging.DEBUG)

LOGGER = logging.getLogger(__name__)


async def get_firmware_size(znp: ZNP, block_size: int) -> int:
    valid_index = 0x0000

    # Z-Stack lets you read beyond the end of the flash (???) if you go too high,
    # instead of throwing an error. We need to be careful.
    invalid_index = 0xFFFF // block_size

    while invalid_index - valid_index > 1:
        midpoint = (valid_index + invalid_index) // 2

        read_rsp = await znp.request_callback_rsp(
            request=c.UBL.ReadReq.Req(FlashWordAddr=midpoint * block_size),
            callback=c.UBL.ReadRsp.Callback(partial=True),
        )

        if read_rsp.Status == c.ubl.BootloaderStatus.SUCCESS:
            valid_index = midpoint
        elif read_rsp.Status == c.ubl.BootloaderStatus.FAILURE:
            invalid_index = midpoint
        else:
            raise ValueError(f"Unexpected read response: {read_rsp}")

    return invalid_index * block_size


async def read_firmware(radio_path: str) -> bytearray:
    znp = ZNP(CONFIG_SCHEMA({"device": {"path": radio_path}}))

    # The bootloader handshake must be the very first command
    await znp.connect(test_port=False)

    try:
        async with async_timeout.timeout(5):
            handshake_rsp = await znp.request_callback_rsp(
                request=c.UBL.HandshakeReq.Req(),
                callback=c.UBL.HandshakeRsp.Callback(partial=True),
            )
    except asyncio.TimeoutError:
        raise RuntimeError(
            "Did not receive a bootloader handshake response!"
            " Make sure your adapter has just been plugged in and"
            " nothing else has had a chance to communicate with it."
        )

    if handshake_rsp.Status != c.ubl.BootloaderStatus.SUCCESS:
        raise RuntimeError(f"Bad bootloader handshake response: {handshake_rsp}")

    # All reads and writes are this size
    buffer_size = handshake_rsp.BufferSize
    block_size = buffer_size // c.ubl.FLASH_WORD_SIZE
    firmware_size = await get_firmware_size(znp, buffer_size)

    LOGGER.info("Total firmware size is %d", firmware_size)

    data = bytearray()

    for address in range(0, firmware_size, block_size):
        LOGGER.info("Progress: %0.2f%%", (100.0 * address) / firmware_size)

        read_rsp = await znp.request_callback_rsp(
            request=c.UBL.ReadReq.Req(FlashWordAddr=address),
            callback=c.UBL.ReadRsp.Callback(partial=True),
        )

        assert read_rsp.Status == c.ubl.BootloaderStatus.SUCCESS
        assert read_rsp.FlashWordAddr == address
        assert len(read_rsp.Data) == buffer_size

        data.extend(read_rsp.Data)

    return data


async def main(argv):
    parser = argparse.ArgumentParser(description="Backup a radio's firmware")
    parser.add_argument("serial", type=argparse.FileType("rb"), help="Serial port path")
    parser.add_argument(
        "--output",
        "-o",
        type=argparse.FileType("wb"),
        help="Output .bin file",
        required=True,
    )

    args = parser.parse_args(argv)

    # We just want to make sure it exists
    args.serial.close()

    data = await read_firmware(args.serial.name)
    args.output.write(data)

    LOGGER.info("Unplug your adapter to leave bootloader mode!")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
