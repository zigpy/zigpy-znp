"""This interface allows the tester to interact with the target at system level such
as reset, read/write memory, read/write extended address…etc.
"""

import enum

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    CommandDef,
    CommandType,
    MTCapabilities,
)
import zigpy_znp.types as t


class SysCommands(enum.Enum):
    # reset the target device
    ResetReq = CommandDef(
        CommandType.AREQ,
        0x00,
        req_schema=t.Schema(
            (
                t.Param(
                    "Type",
                    t.uint8_t,
                    (
                        "This command will reset the device by using a hardware reset "
                        "(i.e. watchdog reset) if ‘Type’ is zero. Otherwise a soft "
                        "reset(i.e. a jump to the reset vector) vice is effected. This "
                        "is especially useful in the CC2531, for instance, so that the "
                        "USB host does not have to contend with the USB H/W resetting "
                        "(and thus causing the USB host to reenumerate the device "
                        "which can cause an open virtual serial port to hang.)"
                    ),
                ),
            )
        ),
    )

    # issue PING requests to verify if a device is active and check the capability of
    # the device
    Ping = CommandDef(
        CommandType.SREQ,
        0x01,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Capabilities",
                    MTCapabilities,
                    "Represents the intefaces this device can handle",
                ),
            )
        ),
    )

    # request for the device’s version string
    Version = CommandDef(
        CommandType.SREQ,
        0x02,
        req_schema=t.Schema(
            (
                t.Param(
                    "Type",
                    t.uint8_t,
                    # the description does not make sense for this command
                    (
                        "Requests a target device reset (0) or serial boot loader "
                        "reset (1). If the target device does not support serial boot "
                        "loading, boot loader reset commands are ignored and no "
                        "response is sent from the target"
                    ),
                ),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param("TransportRev", t.uint8_t, "Transport protocol revision"),
                t.Param("ProductId", t.uint8_t, "Product ID"),
                t.Param("MajorRel", t.uint8_t, "Software major release number"),
                t.Param("MinorRel", t.uint8_t, "Software minor release number"),
                t.Param("HwRev", t.uint8_t, "Chip hardware revision"),
            )
        ),
    )

    # set the extended address of the device
    SetExtAddr = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(
            (t.Param("ExtAddr", t.EUI64, "The device's extended address"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # get the extended address of the device
    getExtAddr = CommandDef(
        CommandType.SREQ,
        0x04,
        req_schema=STATUS_SCHEMA,
        rsp_schema=t.Schema(
            (t.Param("ExtAddr", t.EUI64, "The device's extended address"),)
        ),
    )

    # read a single memory location in the target RAM. The command accepts an address
    # value and returns the memory value present in the target RAM at that address
    RamRead = CommandDef(
        CommandType.SREQ,
        0x05,
        req_schema=t.Schema(
            (
                t.Param("Address", t.uint16_t, "Address of the memory to read"),
                t.Param("Len", t.uint8_t, "The number of bytes to read"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Value", t.LongBytes, "The value read from memory address"),
            )
        ),
    )

    # write to a particular location in the target RAM. The command accepts an
    # address location and a memory value. The memory value is written to the address
    # location in the target RAM
    RamWrite = CommandDef(
        CommandType.SREQ,
        0x06,
        req_schema=t.Schema(
            (
                t.Param("Address", t.uint16_t, "Address of the memory to read"),
                t.Param("Value", t.LongBytes, "The value read from memory address"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # read a single memory item in the target non-volatile memory. The command accepts
    # an attribute Id value and returns the memory value present in the target for the
    # specified attribute Id
    OSALNVRead = CommandDef(
        CommandType.SREQ,
        0x08,
        req_schema=t.Schema(
            (
                t.Param("Id", t.uint16_t, "The Id of the NV item"),
                t.Param(
                    "Offset",
                    t.uint8_t,
                    "Number of bytes offset from the beginning of the NV value",
                ),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Value", t.LongBytes, "The value of the NV item"),
            )
        ),
    )

    # write to a particular item in non-volatile memory. The command accepts an
    # attribute Id and an attribute value. The attribute value is written to the
    # location specified for the attribute Id in the target
    OSALNVWrite = CommandDef(
        CommandType.SREQ,
        0x09,
        req_schema=t.Schema(
            (
                t.Param("Id", t.uint16_t, "The Id of the NV item"),
                t.Param(
                    "Offset",
                    t.uint8_t,
                    "Number of bytes offset from the beginning of the NV value",
                ),
                t.Param("Value", t.LongBytes, "The value of the NV item"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # start a timer event. The event will expired after the indicated amount of time
    # and a notification will be sent back to the tester
    OSALStartTimer = CommandDef(
        CommandType.SREQ,
        0x0A,
        req_schema=t.Schema(
            (
                t.Param("Id", t.uint16_t, "The Id of the timer event (0-3)"),
                t.Param("Timeout", t.uint16_t, "Timer timeout in millliseconds"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # stop a timer event
    OSALStopTimer = CommandDef(
        CommandType.SREQ,
        0x0B,
        req_schema=t.Schema(
            (t.Param("Id", t.uint16_t, "The Id of the timer event (0-3)"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    #  get a random 16-bit number
    Random = CommandDef(
        CommandType.SREQ,
        0x0C,
        rsp_schema=t.Schema((t.Param("Value", t.uint16_t, "The random value"),)),
    )

    # read a value from the ADC based on specified channel and resolution
    ADCRead = CommandDef(
        CommandType.SREQ,
        0x0D,
        req_schema=t.Schema(
            (
                t.Param("Channel", t.ADCChannel, "The channel of ADC to read"),
                t.Param(
                    "Resolution",
                    t.ADCResolution,
                    "Resolution of the reading: 8/10/12/14 bits",
                ),
            )
        ),
        rsp_schema=t.Schema((t.Param("Value", t.uint16_t, "Value of ADC channel"),)),
    )

    # control the 4 GPIO pins on the CC2530-ZNP build
    GPIO = CommandDef(
        CommandType.SREQ,
        0x0E,
        req_schema=t.Schema(
            (
                t.Param(
                    "Operation", t.uint8_t, "Specifies type of operation on GPIO pins"
                ),
                t.Param("Value", t.uint8_t, "GPIO value"),
            )
        ),
        rsp_schema=t.Schema((t.Param("Value", t.uint8_t, "GPIO value"),)),
    )

    # tune intricate or arcane settings at runtime
    StackTune = CommandDef(
        CommandType.SREQ,
        0x0F,
        req_schema=t.Schema(
            (
                t.Param(
                    "Operation", t.uint8_t, "Specifies type of operation on GPIO pins"
                ),
                t.Param("Value", t.uint8_t, "Tuning value"),
            )
        ),
        rsp_schema=t.Schema(
            (t.Param("Value", t.uint8_t, "Applicable status of the tuning operation"),)
        ),
    )

    # MT SYS Callbacks
    # This command is sent by the device to indicate the reset
    ResetInd = CommandDef(
        CommandType.AREQ,
        0x80,
        req_schema=t.Schema(
            (
                t.Param("Reason", t.ResetReason, "Reason for the reset"),
                t.Param("TransportRev", t.uint8_t, "Transport protocol revision"),
                t.Param("MajorRel", t.uint8_t, "Software major release number"),
                t.Param("MinorRel", t.uint8_t, "Software minor release number"),
                t.Param("HwRev", t.uint8_t, "Chip hardware revision"),
            )
        ),
    )

    # This command is sent by the device to indicate a specific time has been expired
    OSALTimerExpired = CommandDef(
        CommandType.AREQ,
        0x81,
        req_schema=t.Schema(
            (t.Param("Id", t.uint16_t, "The Id of the timer event (0-3)"),)
        ),
    )
