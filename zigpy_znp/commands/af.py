import enum

from zigpy_znp.commands.types import CommandDef, CommandType, InterPanCommand
import zigpy_znp.types as t


class AFCommands(enum.Enum):
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
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

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
                t.Param("Data", t.LVBytes, "Data request"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

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
                t.Param("Data", t.LVBytes, "Data request"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

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
                t.Param("Data", t.LVBytes, "Data request"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

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
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

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
                t.Param("Data", t.LVBytes, "Data"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    DataRequestSrcRtg = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(()),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )
