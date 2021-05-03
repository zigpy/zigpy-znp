import sys
import asyncio
import logging

import async_timeout

import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.tools.common import ClosableFileType, setup_parser

LOGGER = logging.getLogger(__name__)


async def read_firmware(znp: ZNP) -> bytearray:
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
            " nothing else has had a chance to communicate with it. Alternatively,"
            " press the button furthest from the USB port. The LED should turn red."
        )

    if handshake_rsp.Status != c.ubl.BootloaderStatus.SUCCESS:
        raise RuntimeError(f"Bad bootloader handshake response: {handshake_rsp}")

    # All reads and writes are this size
    buffer_size = handshake_rsp.BufferSize

    data = bytearray()

    for offset in range(0, c.ubl.IMAGE_SIZE, buffer_size):
        address = offset // c.ubl.FLASH_WORD_SIZE
        LOGGER.info("Progress: %0.2f%%", (100.0 * offset) / c.ubl.IMAGE_SIZE)

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
    parser = setup_parser("Backup a radio's firmware")
    parser.add_argument(
        "--output",
        "-o",
        type=ClosableFileType("wb"),
        help="Output .bin file",
        required=True,
    )

    args = parser.parse_args(argv)

    with args.output as f:
        znp = ZNP(
            CONFIG_SCHEMA(
                {
                    "znp_config": {"skip_bootloader": False},
                    "device": {"path": args.serial},
                }
            )
        )

        # The bootloader handshake must be the very first command
        await znp.connect(test_port=False)

        data = await read_firmware(znp)
        znp.close()

        f.write(data)

        LOGGER.info("Unplug your adapter to leave bootloader mode!")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
