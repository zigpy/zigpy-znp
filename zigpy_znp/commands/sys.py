"""This interface allows the tester to interact with the target at system level such
as reset, read/write memory, read/write extended address…etc.
"""

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    CommandDef,
    CommandType,
    MTCapabilities,
    CommandsBase,
    Subsystem,
)
import zigpy_znp.types as t


class SysCommands(CommandsBase, subsystem=Subsystem.SYS):
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
                t.Param("Value", t.ShortBytes, "The value read from memory address"),
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
                t.Param("Value", t.ShortBytes, "The value read from memory address"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # create and initialize an item in non-volatile memory. The NV item will be created
    # if it does not already exist. The data for the new NV item will be left
    # uninitialized if the InitLen parameter is zero. When InitLen is non-zero, the
    # data for the NV item will be initialized (starting at offset of zero) with the
    # values from InitData. Note that it is not necessary to initialize the entire NV
    # item (InitLen < ItemLen). It is also possible to create an NV item that is larger
    # than the maximum length InitData – use the SYS_OSAL_NV_WRITE command to finish
    # the initialization
    OSALNVItemInit = CommandDef(
        CommandType.SREQ,
        0x07,
        req_schema=t.Schema(
            (
                t.Param("Id", t.uint16_t, "The Id of the NV Item"),
                t.Param("ItemLen", t.uint16_t, "Number of bytes in the NV item"),
                t.Param("Value", t.ShortBytes, "The value of the NV item"),
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
                t.Param("Value", t.ShortBytes, "The value of the NV item"),
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
                t.Param("Value", t.ShortBytes, "The value of the NV item"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # delete an item from the non-volatile memory. The ItemLen parameter must match
    # the length of the NV item or the command will fail
    OSALNVDelete = CommandDef(
        CommandType.SREQ,
        0x12,
        req_schema=t.Schema(
            (
                t.Param("Id", t.uint16_t, "The Id of the NV item"),
                t.Param("ItemLen", t.uint16_t, "Number of bytes in the NV item"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # get the length of an item in non-volatile memory. A returned length of zero
    # indicates that the NV item does not exist
    OSALNVLength = CommandDef(
        CommandType.SREQ,
        0x13,
        req_schema=t.Schema((t.Param("Id", t.uint16_t, "The Id of the NV item"),)),
        rsp_schema=t.Schema(
            (t.Param("ItemLen", t.uint16_t, "Number of bytes in the NV item"),)
        ),
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
                t.Param("Value", t.uint8_t, "GPIO value for specified operation"),
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

    # set the target system date and time. The time can be specified in
    # “seconds since 00:00:00 on January 1, 2000”
    # or in parsed date/time components
    SetTime = CommandDef(
        CommandType.SREQ,
        0x10,
        req_schema=t.Schema(
            (
                t.Param(
                    "UTCTime",
                    t.uint32_t,
                    "Number of seconds since 00:00:00 on Jan 2000",
                ),
                t.Param("Hour", t.uint8_t, "Hour of the day (0 -- 23)"),
                t.Param("Minute", t.uint8_t, "Minute of the hour (0 -- 59)"),
                t.Param("Second", t.uint8_t, "Seconds of the minute (0 -- 59)"),
                t.Param("Month", t.uint8_t, "Month of the year (1 -- 12)"),
                t.Param("Day", t.uint8_t, "Day of the month (1 -- 31)"),
                t.Param("Year", t.uint16_t, "Year (2000 -- )"),
            )
        ),
    )

    # get the target system date and time. The time is returned in
    # “seconds since 00:00:00 on January 1, 2000” and parsed date/time components
    GetTime = CommandDef(
        CommandType.SREQ,
        0x11,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "UTCTime",
                    t.uint32_t,
                    "Number of seconds since 00:00:00 on Jan 2000",
                ),
                t.Param("Hour", t.uint8_t, "Hour of the day (0 -- 23)"),
                t.Param("Minute", t.uint8_t, "Minute of the hour (0 -- 59)"),
                t.Param("Second", t.uint8_t, "Seconds of the minute (0 -- 59)"),
                t.Param("Month", t.uint8_t, "Month of the year (1 -- 12)"),
                t.Param("Day", t.uint8_t, "Day of the month (1 -- 31)"),
                t.Param("Year", t.uint16_t, "Year (2000 -- )"),
            )
        ),
    )

    # set the target system radio transmit power. The returned TX power is the actual
    # setting applied to the radio – nearest characterized value for the specific
    # radio
    SetTxPower = CommandDef(
        CommandType.SREQ,
        0x14,
        req_schema=t.Schema(
            (t.Param("TXPower", t.uint8_t, "Requested TX power setting in dBm"),)
        ),
        rsp_schema=t.Schema(
            (t.Param("TXPower", t.uint8_t, "Actual TX power setting in dBm"),)
        ),
    )

    # initialize the statistics table in NV memory
    ZDiagsInitStats = CommandDef(CommandType.SREQ, 0x17, rsp_schema=STATUS_SCHEMA)

    # clear the statistics table. To clear data in NV (including the Boot
    # Counter) the clearNV flag shall be set to TRUE
    ZDiagsClearStats = CommandDef(
        CommandType.SREQ,
        0x018,
        req_schema=t.Schema(
            (t.Param("ClearNV", t.Bool, "True -- clear statistics in NV memory"),)
        ),
        rsp_schema=t.Schema(
            (t.Param("SycClock", t.uint32_t, "Milliseconds since last reset"),)
        ),
    )

    # read a specific system (attribute) ID statistics and/or metrics value
    ZDiagsGetStats = CommandDef(
        CommandType.SREQ,
        0x19,
        req_schema=t.Schema(
            (t.Param("AttributeId", t.uint16_t, "System diagnostics attribute ID"),)
        ),
        rsp_schema=t.Schema(
            (t.Param("Value", t.uint32_t, "Value of the requested attribute"),)
        ),
    )

    # restore the statistics table from NV into the RAM table
    ZDiagsRestoreStatsNV = CommandDef(CommandType.SREQ, 0x1A, rsp_schema=STATUS_SCHEMA)

    # save the statistics table from RAM to NV
    ZDiagsSaveStatsToNV = CommandDef(
        CommandType.SREQ,
        0x1B,
        rsp_schema=t.Schema(
            (t.Param("SycClock", t.uint32_t, "Milliseconds since last reset"),)
        ),
    )

    # attempt to create an item in non-volatile memory
    NVCreate = CommandDef(
        CommandType.SREQ,
        0x30,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
                t.Param("Length", t.uint32_t, "Number of bytes in the NV item"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # attempt to delete an item in non-volatile memory
    NVDelete = CommandDef(
        CommandType.SREQ,
        0x31,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # get the length of an item in non-volatile memory
    NVLength = CommandDef(
        CommandType.SREQ,
        0x32,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
            )
        ),
        rsp_schema=t.Schema((t.Param("Length", t.uint8_t, "Length of NV item"),)),
    )

    # read an item in non-volatile memory
    NVRead = CommandDef(
        CommandType.SREQ,
        0x33,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
                t.Param(
                    "Offset",
                    t.uint8_t,
                    "Number of bytes offset from the beginning of the NV value",
                ),
                t.Param("Length", t.uint8_t, "Length of data to read"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Value", t.ShortBytes, "Value of the NV item read"),
            )
        ),
    )

    # write an item in non-volatile memory
    NVWrite = CommandDef(
        CommandType.SREQ,
        0x34,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
                t.Param(
                    "Offset",
                    t.uint8_t,
                    "Number of bytes offset from the beginning of the NV value",
                ),
                t.Param("Value", t.ShortBytes, "Value of the NV item to write"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # update an item in non-volatile memory
    NVUpdate = CommandDef(
        CommandType.SREQ,
        0x35,
        req_schema=t.Schema(
            (
                t.Param("SysId", t.uint8_t, "System ID of the NV item"),
                t.Param("ItemId", t.uint16_t, "Item ID of the NV item"),
                t.Param("SubId", t.uint16_t, "Sub ID of the NV item"),
                t.Param("Value", t.ShortBytes, "Value of the NV item to update"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # compact the active page in non-volatile memory
    NVCompact = CommandDef(
        CommandType.SREQ,
        0x36,
        req_schema=t.Schema(
            (
                t.Param(
                    "Threshold",
                    t.uint16_t,
                    "Compaction occurs when NV bytes are less than this value",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
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
