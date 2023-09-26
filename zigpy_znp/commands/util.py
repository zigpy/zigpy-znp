"""This interface provides tester supporting functionalities such as setting PanId,
getting device info, getting NV info, subscribing callbacks, etc."""

import zigpy_znp.types as t


class NodeRelation(t.enum8):
    PARENT = 0
    CHILD_RFD = 1
    CHILD_RFD_RX_IDLE = 2
    CHILD_FFD = 3
    CHILD_FFD_RX_IDLE = 4
    NEIGHBOR = 5
    OTHER = 6
    UNKNOWN_8 = 8
    NOTUSED = 0xFF


class BindEntry(t.Struct):
    srcEP: t.uint8_t
    dstGroupMode: t.uint8_t  # 0 - Normal address index, 1 - Group address
    dstIdx: t.uint16_t
    dstEP: t.uint8_t
    clusterIdList: t.ClusterIdList


class AgingEndDevice(t.CStruct):
    endDevCfg: t.uint8_t
    deviceTimeout: t.uint32_t


class LinkInfo(t.CStruct):
    txCounter: t.uint8_t  # Counter of transmission success/failures
    txCost: t.uint8_t  # Average of sending rssi values if link status is enabled
    #   i.e. NWK_LINK_STATUS_PERIOD is defined as non zero
    rxLqi: t.uint8_t  # average of received rssi values
    # needs to be converted to link cost (1-7) before used
    inKeySeqNum: t.uint8_t  # security key sequence number
    inFrmCntr: t.uint32_t  # security frame counter..
    txFailure: t.uint16_t  # higher values indicate more failures


class Device(t.CStruct):
    shortAddr: t.NWK
    addrIdx: t.uint16_t
    nodeRelation: NodeRelation
    devStatus: t.uint8_t
    assocCnt: t.uint8_t
    age: t.uint8_t
    linkInfo: LinkInfo
    endDev: AgingEndDevice
    timeoutCounter: t.uint32_t
    keepaliveRcv: t.uint8_t  # not a bool, can be 0xFF
    ctrl: t.uint8_t  # XXX: This field is only present in Z-Stack 3.30+ !!!


class Key(t.FixedList, item_type=t.uint8_t, length=42):
    pass


class RandomNumbers(t.FixedList, item_type=t.uint8_t, length=100):
    pass


class LEDMode(t.enum8):
    OFF = 0
    ON = 1
    BLINK = 2
    FLASH = 3
    TOGGLE = 4


class UTIL(t.CommandsBase, subsystem=t.Subsystem.UTIL):
    # MAC Reset command to reset MAC state machine
    GetDeviceInfo = t.CommandDef(
        t.CommandType.SREQ,
        0x00,
        req_schema=(),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("DeviceType", t.DeviceTypeCapabilities, "Device type"),
            t.Param("DeviceState", t.DeviceState, "Indicated the state of the device"),
            t.Param(
                "AssociatedDevices",
                t.NWKList,
                (
                    "Network addresses of Reduce Function Devices associated "
                    "to the local device."
                ),
            ),
        ),
    )

    # read a block of parameters from Non-Volatile storage of the target device
    GetNVInfo = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("IEEE", t.EUI64, "IEEE address of the device"),
            t.Param(
                "ScanChannels",
                t.uint32_t,
                "Channels to be scanned when starting the device. Big endian!",
            ),
            t.Param(
                "PanId",
                t.PanId,
                "The PAN Id to use. This parameter is ignored if Pan",
            ),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            t.Param("PreConfigKey", t.KeyData, "Preconfigured network key"),
        ),
    )

    # Set PAN ID
    SetPanId = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(t.Param("PanId", t.PanId, "The PAN Id to set"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # store a channel select bit-mask into Non-Volatile memory to be used the next
    # time the target device resets
    SetChannels = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param(
                "Channels", t.Channels, "Channels to scan when starting the device"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # store a security level value into Non-Volatile memory to be used the next time
    # the target device reset
    SetSecurityLevel = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(
            # ToDo: Make this an enum
            t.Param(
                "SecurityLevel",
                t.uint8_t,
                "Specifies the messaging network security level",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # store a pre-configured key array into Non-Volatile memory to be used the next
    # time the target device resets
    SetPreConfigKey = t.CommandDef(
        t.CommandType.SREQ,
        0x05,
        req_schema=(t.Param("PreConfigKey", t.KeyData, "Preconfigured network key"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # subscribes/unsubscribes to layer callbacks. For particular subsystem callbacks
    # to work, the software must be compiled with a special flag that is unique to that
    # subsystem to enable the callback mechanism. For example to enable ZDO callbacks,
    # MT_ZDO_CB_FUNC flag must be compiled when the software is built
    CallbackSubCmd = t.CommandDef(
        t.CommandType.SREQ,
        0x06,
        req_schema=(
            t.Param(
                "SubsystemId",
                t.CallbackSubsystem,
                "Subsystem id to subscribe/unsubscribe",
            ),
            t.Param("Action", t.Bool, "True -- enable, False -- Disable"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Send a key event to the device registered application
    KeyEvent = t.CommandDef(
        t.CommandType.SREQ,
        0x07,
        req_schema=(
            t.Param("Keys", t.uint8_t, "Key code bitmask"),
            t.Param("Shift", t.Bool, "True -- shift, False -- no shift"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # get the board's time alive
    TimeAlive = t.CommandDef(
        t.CommandType.SREQ,
        0x09,
        req_schema=(),
        rsp_schema=(
            t.Param("Seconds", t.uint32_t, "The time of the board's uptime in seconds"),
        ),
    )

    # control the LEDs on the board
    LEDControl = t.CommandDef(
        t.CommandType.SREQ,
        0x0A,
        req_schema=(
            t.Param("LED", t.uint8_t, "The LED number. 0xFF for all."),
            t.Param("Mode", LEDMode, "LED mode. ON/OFF are static."),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # test data buffer loopback
    Loopback = t.CommandDef(
        t.CommandType.SREQ,
        0x10,
        req_schema=(t.Param("Data", t.Bytes, "The data bytes to loop back"),),
        rsp_schema=(t.Param("Data", t.Bytes, "The looped back data"),),
    )

    # effect a MAC MLME Poll Request
    DataReq = t.CommandDef(
        t.CommandType.SREQ,
        0x11,
        req_schema=(
            t.Param(
                "SecurityUse",
                t.Bool,
                "True -- to request MAC security, bun not used for now",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # enable AUTOPEND and source address matching
    SrcMatchEnable = t.CommandDef(
        t.CommandType.SREQ, 0x20, req_schema=(), rsp_schema=t.STATUS_SCHEMA
    )

    # add a short or extended address to source address table
    SrcMatchAddEntry = t.CommandDef(
        t.CommandType.SREQ,
        0x21,
        req_schema=(
            t.Param("AddrModeAddress", t.AddrModeAddress, "Address mode and address"),
            t.Param(
                "PanId",
                t.PanId,
                "PAN Id of the device. Only use with a short address",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # delete a short or extended address to source address table
    SrcMatchDelEntry = t.CommandDef(
        t.CommandType.SREQ,
        0x22,
        req_schema=(
            t.Param("AddrModeAddress", t.AddrModeAddress, "Address mode and address"),
            t.Param(
                "PanId",
                t.PanId,
                "PAN Id of the device. Only use with a short address",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # check if a short or extended address is in the source address table
    SrcMatchCheckSrcAddr = t.CommandDef(
        t.CommandType.SREQ,
        0x23,
        req_schema=(
            t.Param("AddrModeAddress", t.AddrModeAddress, "Address mode and address"),
            t.Param(
                "PanId",
                t.PanId,
                "PAN Id of the device. Only use with a short address",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # enable/disable acknowledging all packets with pending bit set
    SrcMatchAckAllPending = t.CommandDef(
        t.CommandType.SREQ,
        0x24,
        req_schema=(
            t.Param(
                "Enabled",
                t.Bool,
                (
                    "True - acknowledging all packets with pending field set, "
                    "False - Otherwise"
                ),
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # check if acknowledging all packets with pending bit set is enabled
    SrcMatchCheckAllPending = t.CommandDef(
        t.CommandType.SREQ,
        0x25,
        req_schema=(),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param(
                "Enabled",
                t.Bool,
                (
                    "True - acknowledging all packets with pending field set, "
                    "False - Otherwise"
                ),
            ),
        ),
    )

    # proxy call to the AddrMgrEntryLookupExt() function
    AddrMgrExtAddrLookup = t.CommandDef(
        t.CommandType.SREQ,
        0x40,
        req_schema=(
            t.Param(
                "IEEE", t.EUI64, "Extended address of the device to lookup the NWK"
            ),
        ),
        rsp_schema=(t.Param("NWK", t.NWK, "NWK address of the device"),),
    )

    # a proxy call to the AddrMgrEntryLookupNwk() function
    AddrMgwNwkAddrLookUp = t.CommandDef(
        t.CommandType.SREQ,
        0x41,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device to lookup IEEE"),
        ),
        rsp_schema=(t.Param("IEEE", t.EUI64, "Extended address of the device"),),
    )

    # retrieve APS link key data, Tx and Rx frame counters
    APSMELinkKeyDataGet = t.CommandDef(
        t.CommandType.SREQ,
        0x44,
        req_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the device to get link data"),
        ),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("SecKey", t.KeyData, "Security Key"),
            t.Param("TxFrmCntr", t.uint32_t, "On success, the TX frame counter"),
            t.Param("RxFrmCntr", t.uint32_t, "On success, the RX frame counter"),
        ),
    )

    # a proxy call to the APSME_LinkKeyNvIdGet() function
    APSMELinkKeyNvIdGet = t.CommandDef(
        t.CommandType.SREQ,
        0x45,
        req_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the device to get link data"),
        ),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param(
                "LinkKeyNvId",
                t.uint16_t,
                "On success, link key NV ID, otherwise 0xFFFF",
            ),
        ),
    )

    # a proxy call to the AssocCount() function
    AssocCount = t.CommandDef(
        t.CommandType.SREQ,
        0x48,
        req_schema=(
            t.Param(
                "StartRelation", NodeRelation, "A valid node relation from AssocList.h"
            ),
            t.Param(
                "EndRelation",
                NodeRelation,
                "Same as StartRelation, but the node relation to stop counting",
            ),
        ),
        rsp_schema=(
            t.Param("Count", t.uint16_t, "The count returned by the proxy call"),
        ),
    )

    # a proxy call to the AssocFindDevice() function
    AssocFindDevice = t.CommandDef(
        t.CommandType.SREQ,
        0x49,
        req_schema=(
            t.Param("Index", t.uint8_t, "Nth active entry in the device list"),
        ),
        # XXX: The struct is not packed when sent: `write(&struct, sizeof(struct))`
        rsp_schema=(t.Param("Device", t.Bytes, "associated_devices_t structure"),),
    )

    # a proxy call to the AssocGetWithAddress() function
    AssocGetWithAddress = t.CommandDef(
        t.CommandType.SREQ,
        0x4A,
        req_schema=(
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
        ),
        rsp_schema=(t.Param("Device", Device, "associated_devices_t structure"),),
    )

    # send a request key to the Trust Center from an originator device who wants to
    # exchange messages with a partner device
    APSMERequestKeyCmd = t.CommandDef(
        t.CommandType.SREQ,
        0x4B,
        req_schema=(
            t.Param(
                "IEEE",
                t.EUI64,
                (
                    "Specifies the extended address of the partner device the "
                    "originator wants to exchange messages with"
                ),
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # a proxy call to the bindAddEntry() function
    BindAddEntry = t.CommandDef(
        t.CommandType.SREQ,
        0x4D,
        req_schema=(
            t.Param(
                "DstAddrModeAddr",
                t.AddrModeAddress,
                "Address mode address of the partner",
            ),
            t.Param("DstEndpoint", t.uint8_t, "Binding entry destination endpoint"),
            t.Param("ClusterIdList", t.ClusterIdList, "List of the cluster IDs"),
        ),
        rsp_schema=(
            t.Param(
                "BindEntry",
                BindEntry,
                (
                    "Bind Entry. The dstIdx in the BindEntry is set to "
                    "INVALID_NODE_ADDR to indicate failure"
                ),
            ),
        ),
    )

    # Z2M firmware: proxy call to AssocRemove
    AssocRemove = t.CommandDef(
        t.CommandType.SREQ,
        0x63,
        req_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the device to remove"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Z2M firmware: proxy call to AssocAddNew
    AssocAdd = t.CommandDef(
        t.CommandType.SREQ,
        0x64,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("IEEE", t.EUI64, "Extended address of the device to add"),
            t.Param(
                "NodeRelation",
                NodeRelation,
                "Relation of the device to the coordinator",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # a proxy call to zclGeneral_KeyEstablish_InitiateKeyEstablishment()
    ZCLKeyEstInitEst = t.CommandDef(
        t.CommandType.SREQ,
        0x80,
        req_schema=(
            t.Param("TaskId", t.uint8_t, "The OSAL Task Id making the request"),
            t.Param("SeqNum", t.uint8_t, "The sequence number of the request"),
            t.Param("EndPoint", t.uint8_t, "The endpoint of the partner"),
            t.Param(
                "AddrModeAddr",
                t.AddrModeAddress,
                "Address mode address of the partner",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # a proxy call to zclGeneral_KeyEstablishment_ECDSASign()
    ZCLKeyEstSign = t.CommandDef(
        t.CommandType.SREQ,
        0x81,
        req_schema=(t.Param("Input", t.ShortBytes, "The input data"),),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Key", Key, "The output key on success"),
        ),
    )

    #  generate Secure Random Number. It generates 1,000,000 bits in sets of 100 bytes.
    #  As in 100 bytes of secure random numbers are generated until 1,000,000 bits are
    #  generated. 100 bytes are generated 1250 times. So 1250 SRSPs are generated.
    #  MT_SRNG has to be defined to include this API
    SRngGen = t.CommandDef(
        t.CommandType.SREQ,
        0x4C,
        req_schema=(),
        rsp_schema=(
            t.Param("RandomNumbers", RandomNumbers, "Secure random numbers list"),
        ),
    )

    # UTIL Callbacks
    # asynchronous request/response handshake
    # XXX: This command's request is completely identical to its response.
    # SyncReq = t.CommandDef(t.CommandType.AREQ, 0xE0)

    # RPC proxy indication for a ZCL_KEY_ESTABLISH_IND
    ZCLKeyEstInd = t.CommandDef(
        t.CommandType.AREQ,
        0xE1,
        rsp_schema=(
            t.Param(
                "TaskId",
                t.uint8_t,
                "The OSAL Task id registered to receive the indication",
            ),
            t.Param("Event", t.uint8_t, "The OSAL message event"),
            t.Param("Status", t.Status, "The OSAL message status"),
            t.Param("WaitTime", t.uint8_t, "The wait time"),
            t.Param("Suite", t.uint16_t, "The key establishment suite"),
        ),
    )
