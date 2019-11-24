import enum

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    CommandDef,
    CommandType,
    InterPanCommand,
)
import zigpy_znp.types as t


class AFCommands(enum.Enum):
    # This command enables the tester to register an application’s endpoint description
    Register = CommandDef(
        CommandType.SREQ,
        0x00,
        req_schema=t.Schema(
            (
                t.Param("Endpoint", t.uint8_t, "Endpoint Id of the device"),
                t.Param("ProfileId", t.uint16_t, "Application Profile ID"),
                t.Param("DeviceId", t.uint16_t, "Device Description ID"),
                t.Param(
                    "LatencyReq",
                    t.uint8_t,
                    (
                        "Specifies latency: 0x00 - No latency, "
                        "0x01 -- fast beacons, "
                        "0x02 -- slow beacons"
                    ),
                ),
                t.Param("InputClusters", t.LVList(t.ClusterId), "Input cluster list"),
                t.Param("OutputClusters", t.LVList(t.ClusterId), "Output cluster list"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # This command is used by the tester to build and send a message through AF layer
    DataRequest = CommandDef(
        CommandType.SREQ,
        0x01,
        req_schema=t.Schema(
            (
                t.Param("DstAddr", t.NWK, "Short address of the destination device"),
                t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
                t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
                t.Param("ClusterId", t.ClusterId, "Cluster ID"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
                t.Param(
                    "Options",
                    t.uint8_t,
                    (
                        "Transmit options bitmask: bit 4 -- APS Ack, "
                        "bit 5 -- Route Discovery, "
                        "bit 6 -- APS security, "
                        "bit 7 -- Skip routing"
                    ),
                ),
                t.Param(
                    "Radius",
                    t.uint8_t,
                    "Specifies the number of hops allowed delivering the message",
                ),
                t.Param("Data", t.ShortBytes, "Data request"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # This extended form of the AF_DATA_REQUEST must be used to send an
    # inter-pan message
    DataRequestExt = CommandDef(
        CommandType.SREQ,
        0x02,
        req_schema=t.Schema(
            (
                t.Param(
                    "DstAddrModeAddress",
                    t.AddrModeAddress,
                    "Destination address mode and address",
                ),
                t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
                t.Param(
                    "DstPanId",
                    t.PanId,
                    (
                        "PanId of the destination device: 0x0000==Intra-Pan, "
                        "otherwise Inter-Pan"
                    ),
                ),
                t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
                t.Param("ClusterId", t.ClusterId, "Cluster ID"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
                t.Param(
                    "Options",
                    t.uint8_t,
                    (
                        "Transmit options bitmask: bit 4 -- APS Ack, "
                        "bit 5 -- Route Discovery, "
                        "bit 6 -- APS security, "
                        "bit 7 -- Skip routing"
                    ),
                ),
                t.Param(
                    "Radius",
                    t.uint8_t,
                    "Specifies the number of hops allowed delivering the message",
                ),
                t.Param("Data", t.LongBytes, "Data request"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # This command is used by the tester to build and send a message through AF layer
    # using source routing
    DataRequestSrcRtg = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(
            (
                t.Param("DstAddr", t.NWK, "Short address of the destination device"),
                t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
                t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
                t.Param("ClusterId", t.ClusterId, "Cluster ID"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
                t.Param(
                    "Options",
                    t.uint8_t,
                    (
                        "Transmit options bitmask: bit 4 -- APS Ack, "
                        "bit 5 -- Route Discovery, "
                        "bit 6 -- APS security, "
                        "bit 7 -- Skip routing"
                    ),
                ),
                t.Param(
                    "Radius",
                    t.uint8_t,
                    "Specifies the number of hops allowed delivering the message",
                ),
                t.Param("SourceRoute", t.LVList(t.NWK), "Relay list"),
                t.Param("Data", t.ShortBytes, "Data request"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Inter-Pan control command and data
    InterPanCtl = CommandDef(
        CommandType.SREQ,
        0x10,
        req_schema=t.Schema(
            (
                t.Param(
                    "Command",
                    InterPanCommand,
                    (
                        "0x00 InterPanClr Proxy call to StubAPS_SetIntraPanChannel() to"
                        " switch channel back to the NIB-specified channel. "
                        "0x01 InterPanSet Proxy call to StubAPS_SetInterPanChannel() "
                        "with the 1-byte channel specified. "
                        "0x02 InterPanReg If the 1-byte Endpoint specified by the data "
                        "argument is found by invoking afFindEndPointDesc(), then proxy"
                        " a call to StubAPS_RegisterApp() with the pointer to the "
                        "endPointDesc_t found (i.e. the Endpoint must already be "
                        "registered with AF)"
                    ),
                ),
                t.Param("Data", t.Bytes, "Data"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Huge AF data request data buffer store command and data
    DataStore = CommandDef(
        CommandType.SREQ,
        0x11,
        req_schema=t.Schema(
            (
                t.Param(
                    "Index",
                    t.uint16_t,
                    (
                        "Specifies the index into the outgoing data request data buffer"
                        "to start the storing of this chunk of data"
                    ),
                ),
                t.Param("Data", t.ShortBytes, "Data"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Huge AF incoming message data buffer retrieve command
    DataRetrieve = CommandDef(
        CommandType.SREQ,
        0x12,
        req_schema=t.Schema(
            (
                t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
                t.Param(
                    "Index",
                    t.uint16_t,
                    (
                        "Specifies the index into the outgoing data request data buffer"
                        "to start the storing of this chunk of data"
                    ),
                ),
                t.Param(
                    "Length",
                    t.uint8_t,
                    (
                        "A length of zero is special and triggers the freeing of the "
                        "corresponding incoming message"
                    ),
                ),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Data", t.ShortBytes, "Data"),
            )
        ),
    )

    # This command is sent by the device to the user after it receives a data request
    DataConfirm = CommandDef(
        CommandType.AREQ,
        0x80,
        req_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Endpoint", t.uint8_t, "Endpoint of the device"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            )
        ),
    )

    # This callback message is in response to incoming data to any of the registered
    # endpoints on this device
    IncomingMsg = CommandDef(
        CommandType.AREQ,
        0x81,
        req_schema=t.Schema(
            (
                t.Param("GroupId", t.GroupId, "The group ID of the device"),
                t.Param("ClusterId", t.ClusterId, "Cluster ID"),
                t.Param(
                    "SrcAddr", t.NWK, "Short address of the device sending the message"
                ),
                t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
                t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
                t.Param(
                    "WasBroadcast",
                    t.uint8_t,
                    "Was the incoming message broadcast or not",
                ),
                t.Param("LQI", t.uint8_t, "Link quality measured during reception"),
                t.Param("SecurityUse", t.uint8_t, "Is security in use or not"),
                t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
                t.Param("Data", t.ShortBytes, "Data"),
            )
        ),
    )

    # This callback message is in response to incoming data to any of the registered
    # endpoints on this device when the code is compiled with the INTER_PAN
    # flag defined
    IncomingMsgExt = CommandDef(
        CommandType.AREQ,
        0x82,
        req_schema=t.Schema(
            (
                t.Param("GroupId", t.GroupId, "The group ID of the device"),
                t.Param("ClusterId", t.ClusterId, "Cluster ID"),
                t.Param(
                    "SrcAddrModeAddress",
                    t.AddrModeAddress,
                    "Address of the device sending the message",
                ),
                t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
                t.Param("SrcPanId", t.PanId, "Source PanId of the message"),
                t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
                t.Param(
                    "WasBroadcast",
                    t.uint8_t,
                    "Was the incoming message broadcast or not",
                ),
                t.Param("LQI", t.uint8_t, "Link quality measured during reception"),
                t.Param("SecurityUse", t.uint8_t, "Is security in use or not"),
                t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
                t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
                t.Param("Data", t.LongBytes, "Data"),
            )
        ),
    )
