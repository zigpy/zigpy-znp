"""This interface provides tester supporting functionalities such as setting PanId,
getting device info, getting NV info, subscribing callbacks…etc."""
import enum

import zigpy.zdo.types

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    CallbackSubsystem,
    CommandDef,
    CommandType,
    DeviceState,
)
import zigpy_znp.types as t


class Device(t.FixedList):
    """associated_devices_t structure returned by the proxy call to
        AssocFindDevice()"""

    _itemtype = t.uint8_t
    _length = 18


class Key(t.FixedList):
    _itemtype = t.uint8_t
    _length = 42


class UtilCommands(enum.Enum):
    # MAC Reset command to reset MAC state machine
    GetDeviceInfo = CommandDef(
        CommandType.SREQ,
        0x00,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "Extended address of the device"),
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param("DeviceType", zigpy.zdo.types.LogicalType, "Device type"),
                t.Param(
                    "DeviceState", DeviceState, "Indicated the state of the device"
                ),
                t.Param("Childs", t.LVList(t.NWK), "List of child devices"),
            )
        ),
    )

    # read a block of parameters from Non-Volatile storage of the target device
    SetPanId = CommandDef(
        CommandType.SREQ,
        0x01,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "IEEE address of the device"),
                t.Param(
                    "ScanChannels",
                    t.Channels,
                    "Channels to be scanned when starting the device",
                ),
                t.Param(
                    "PanId",
                    t.PanId,
                    "The PAN Id to use. This parameter is ignored if Pan",
                ),
                # ToDo: Make this an enum
                t.Param(
                    "SecurityLevel", t.uint8_t, "Security level of this data frame"
                ),
                t.Param(
                    "PreConfigKey", zigpy.types.KeyData, "Preconfigured network key"
                ),
            )
        ),
    )

    # Set PAN ID
    GetNvInfo = CommandDef(
        CommandType.SREQ,
        0x02,
        req_schema=t.Schema((t.Param("PanId", t.PanId, "The PAN Id to set"),)),
        rsp_schema=STATUS_SCHEMA,
    )

    # store a channel select bit-mask into Non-Volatile memory to be used the next
    # time the target device resets
    SetChannels = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(
            (
                t.Param(
                    "Channels", t.Channels, "Channels to scan when starting the device"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # store a security level value into Non-Volatile memory to be used the next time
    # the target device reset
    SetSecurityLevel = CommandDef(
        CommandType.SREQ,
        0x04,
        req_schema=t.Schema(
            (
                # ToDo: Make this an enum
                t.Param(
                    "SecurityLevel",
                    t.uint8_t,
                    "Specifies the messaging network security level",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # store a pre-configured key array into Non-Volatile memory to be used the next
    # time the target device resets
    SetPreConfigKey = CommandDef(
        CommandType.SREQ,
        0x05,
        req_schema=t.Schema(
            (t.Param("PreConfigKey", zigpy.types.KeyData, "Preconfigured network key"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # subscribes/unsubscribes to layer callbacks. For particular subsystem callbacks
    # to work, the software must be compiled with a special flag that is unique to that
    # subsystem to enable the callback mechanism. For example to enable ZDO callbacks,
    # MT_ZDO_CB_FUNC flag must be compiled when the software is built
    CallbackSubCmd = CommandDef(
        CommandType.SREQ,
        0x06,
        req_schema=t.Schema(
            (
                t.Param(
                    "SubsystemId",
                    CallbackSubsystem,
                    "Subsystem id to subscribe/unsubscribe",
                ),
                t.Param("Action", t.Bool, "True -- enable, False -- Disable"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Send a key event to the device registered application
    KeyEvent = CommandDef(
        CommandType.SREQ,
        0x07,
        req_schema=t.Schema(
            (
                t.Param("Shift", t.Bool, "True -- shift, False -- no shift"),
                t.Param("Key", t.uint8_t, "Value of the key"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # get the board’s time alive
    TimeAlive = CommandDef(
        CommandType.SREQ,
        0x09,
        rsp_schema=t.Schema(
            (
                t.Param("Shift", t.Bool, "True -- shift, False -- no shift"),
                t.Param("Key", t.uint8_t, "Value of the key"),
            )
        ),
    )

    # control the LEDs on the board
    LEDControl = CommandDef(
        CommandType.SREQ,
        0x0A,
        req_schema=t.Schema(
            (
                t.Param("Laded", t.uint8_t, "The LED number"),
                t.Param("On", t.Bool, "True -- On, False -- Off"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # test data buffer loopback
    Loopback = CommandDef(
        CommandType.SREQ,
        0x10,
        req_schema=t.Schema((t.Param("Data", t.Bytes, "The data bytes to loop back"),)),
        rsp_schema=t.Schema((t.Param("Data", t.Bytes, "The looped back data"),)),
    )

    # effect a MAC MLME Poll Request
    DataReq = CommandDef(
        CommandType.SREQ,
        0x11,
        req_schema=t.Schema(
            (
                t.Param(
                    "SecurityUse",
                    t.Bool,
                    "True -- to request MAC security, bun not used for now",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # a proxy call to the AddrMgrEntryLookupNwk() function
    AddrMgwNwkAddrLookUp = CommandDef(
        CommandType.SREQ,
        0x41,
        req_schema=t.Schema(
            (t.Param("NWK", t.NWK, "Short address of the device to lookup IEEE"),)
        ),
        rsp_schema=t.Schema(
            (t.Param("IEEE", t.EUI64, "Extended address of the device"),)
        ),
    )

    # a proxy call to the AssocCount() function
    AssocCount = CommandDef(
        CommandType.SREQ,
        0x48,
        req_schema=t.Schema(
            (
                t.Param(
                    "StartRelation", t.uint8_t, "A valid node relation from AssocList.h"
                ),
                t.Param(
                    "EndRelation",
                    t.uint8_t,
                    "Same as StartRelation, but the node relation to stop counting",
                ),
            )
        ),
        rsp_schema=t.Schema(
            (t.Param("Count", t.uint16_t, "The count returned by the proxy call"),)
        ),
    )

    # a proxy call to the AssocFindDevice() function
    AssocFindDevice = CommandDef(
        CommandType.SREQ,
        0x49,
        req_schema=t.Schema(
            (t.Param("Index", t.uint8_t, "Nth active entry in the device list"),)
        ),
        rsp_schema=t.Schema(
            (t.Param("Device", Device, "associated_devices_t structure"),)
        ),
    )

    # a proxy call to the AssocGetWithAddress() function
    AssocGetWithAddress = CommandDef(
        CommandType.SREQ,
        0x4A,
        req_schema=t.Schema(
            (
                t.Param(
                    "IEEE",
                    t.EUI64,
                    (
                        "Extended address for the lookup or all zeroes to use the NWK "
                        "addr for the lookup"
                    ),
                ),
                t.Param(
                    "NWK", t.NWK, "NWK address to use for lookup if IEEE is all zeroes"
                ),
            )
        ),
        rsp_schema=t.Schema(
            (t.Param("Device", Device, "associated_devices_t structure"),)
        ),
    )

    # a proxy call to zclGeneral_KeyEstablish_InitiateKeyEstablishment()
    ZCLKeyEstInitEst = CommandDef(
        CommandType.SREQ,
        0x80,
        req_schema=t.Schema(
            (
                t.Param("TaskId", t.uint8_t, "The OSAL Task Id making the request"),
                t.Param("SeqNum", t.uint8_t, "The sequence number of the request"),
                t.Param("EndPoint", t.uint8_t, "The endpoint of the partner"),
                t.Param(
                    "AddrModeAddr",
                    t.AddrModeAddress,
                    "Address mode address of the partner",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # a proxy call to zclGeneral_KeyEstablishment_ECDSASign()
    ZCLKeyEstSign = CommandDef(
        CommandType.SREQ,
        0x81,
        req_schema=t.Schema((t.Param("Input", t.LongBytes, "The input data"),)),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Key", Key, "The output key on success"),
            )
        ),
    )

    # UTIL Callbacks
    # asynchronous request/response handshake
    SyncReq = CommandDef(CommandType.AREQ, 0xE0)

    # RPC proxy indication for a ZCL_KEY_ESTABLISH_IND
    ZCLKeyEstInd = CommandDef(
        CommandType.AREQ,
        0xE1,
        req_schema=t.Schema(
            (
                t.Param(
                    "TaskId",
                    t.uint8_t,
                    "The OSAL Task id registered to receive the indication",
                ),
                t.Param("Event", t.uint8_t, "The OSAL message event"),
                t.Param("Status", t.Status, "The OSAL message status"),
                t.Param("WaitTime", t.uint8_t, "The wait time"),
                t.Param("Suite", t.uint16_t, "The key establishment suite"),
            )
        ),
    )
