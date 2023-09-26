"""Serial bootloader interface. Implemented in sb_exec_v2.c
"""

import zigpy_znp.types as t

# Size of internal flash less 4 pages for boot loader,
# 6 pages for NV, & 1 page for lock bits.
IMAGE_SIZE = 0x40000 - 0x2000 - 0x3000 - 0x0800
IMAGE_CRC_OFFSET = 0x90

FLASH_WORD_SIZE = 4


class BootloaderStatus(t.enum8):
    SUCCESS = 0
    FAILURE = 1
    INVALID_FCS = 2
    INVALID_FILE = 3
    FILESYSTEM_ERROR = 4
    ALREADY_STARTED = 5
    NO_RESPOSNE = 6
    VALIDATE_FAILED = 7
    CANCELED = 8


class BootloaderDeviceType(t.enum8):
    CC2538 = 1
    CC2530 = 2


class BootloaderRunMode(t.enum8):
    # Read the code, not the spec
    FORCE_BOOT = 0x10
    FORCE_RUN = FORCE_BOOT ^ 0xFF


class UBL(t.CommandsBase, subsystem=t.Subsystem.UBL_FUNC):
    WriteReq = t.CommandDef(
        t.CommandType.AREQ,
        0x01,
        req_schema=(
            (
                t.Param("FlashWordAddr", t.uint16_t, "Write address, in flash words"),
                t.Param(
                    "Data", t.TrailingBytes, "HandshakeRsp.BufferSize bytes of data"
                ),
            )
        ),
    )

    WriteRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x81,
        rsp_schema=((t.Param("Status", BootloaderStatus, "Write status"),)),
    )

    ReadReq = t.CommandDef(
        t.CommandType.AREQ,
        0x02,
        req_schema=(
            t.Param("FlashWordAddr", t.uint16_t, "Read address, in flash words"),
        ),
    )

    ReadRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x82,
        rsp_schema=(
            t.Param("Status", BootloaderStatus, "Read status"),
            # These are missing if the request is bad
            t.Param(
                "FlashWordAddr",
                t.uint16_t,
                "Address read from, in flash words",
                optional=True,
            ),
            t.Param(
                "Data",
                t.TrailingBytes,
                "HandshakeRsp.BufferSize bytes of data",
                optional=True,
            ),
        ),
    )

    EnableReq = t.CommandDef(t.CommandType.AREQ, 0x03, req_schema=())

    EnableRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x83,
        rsp_schema=(t.Param("Status", BootloaderStatus, "Enable status"),),
    )

    HandshakeReq = t.CommandDef(t.CommandType.AREQ, 0x04, req_schema=())

    HandshakeRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x84,
        rsp_schema=(
            t.Param("Status", BootloaderStatus, "Handshake status"),
            t.Param("BootloaderRevision", t.uint32_t, "Bootloader revision"),
            t.Param("DeviceType", BootloaderDeviceType, "Device type"),
            t.Param("BufferSize", t.uint32_t, "Read/write buffer size"),
            t.Param("PageSize", t.uint32_t, "Device page size"),
            t.Param("BootloaderCodeRevision", t.uint32_t, "Bootloader code revision"),
        ),
    )
