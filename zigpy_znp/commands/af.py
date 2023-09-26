import zigpy_znp.types as t


class TransmitOptions(t.bitmap8):
    NONE = 0

    # Will force the message to use Wildcard ProfileID
    WILDCARD_PROFILEID = 0x02

    # Will force APS to callback to preprocess before calling NWK layer
    APS_PREPROCESS = 0x04
    LIMIT_CONCENTRATOR = 0x08
    ACK_REQUEST = 0x10

    # Suppress Route Discovery for intermediate routes (route discovery performed for
    # initiating device)
    SUPPRESS_ROUTE_DISC_NETWORK = 0x20
    ENABLE_SECURITY = 0x40
    SKIP_ROUTING = 0x80


class LatencyReq(t.enum8):
    NoLatencyReqs = 0x00
    FastBeacons = 0x01
    SlowBeacons = 0x02


class AF(t.CommandsBase, subsystem=t.Subsystem.AF):
    # This command enables the tester to register an application's endpoint description
    Register = t.CommandDef(
        t.CommandType.SREQ,
        0x00,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint Id of the device"),
            t.Param("ProfileId", t.uint16_t, "Application Profile ID"),
            t.Param("DeviceId", t.uint16_t, "Device Description ID"),
            t.Param("DeviceVersion", t.uint8_t, "Device version number"),
            t.Param(
                "LatencyReq",
                LatencyReq,
                (
                    "Specifies latency reqs: 0x00 - None, "
                    "0x01 -- fast beacons, "
                    "0x02 -- slow beacons"
                ),
            ),
            t.Param("InputClusters", t.ClusterIdList, "Input cluster list"),
            t.Param("OutputClusters", t.ClusterIdList, "Output cluster list"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command is used by the tester to build and send a message through AF layer
    DataRequest = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param("DstAddr", t.NWK, "Short address of the destination device"),
            t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
            t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
            t.Param("ClusterId", t.ClusterId, "Cluster ID"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            t.Param(
                "Options",
                TransmitOptions,
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
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This extended form of the AF_DATA_REQUEST must be used to send an
    # inter-pan message
    DataRequestExt = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(
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
                TransmitOptions,
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
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command is used by the tester to build and send a message through AF layer
    # using source routing
    DataRequestSrcRtg = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param("DstAddr", t.NWK, "Short address of the destination device"),
            t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
            t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
            t.Param("ClusterId", t.ClusterId, "Cluster ID"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            t.Param(
                "Options",
                TransmitOptions,
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
            t.Param("SourceRoute", t.NWKList, "Relay list"),
            t.Param("Data", t.ShortBytes, "Data request"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # XXX: UNDOCUMENTED
    Delete = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(t.Param("Endpoint", t.uint8_t, "Application Endpoint to delete"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Inter-Pan control command and data
    InterPanCtl = t.CommandDef(
        t.CommandType.SREQ,
        0x10,
        req_schema=(
            t.Param(
                "Command",
                t.InterPanCommand,
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
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Huge AF data request data buffer store command and data
    DataStore = t.CommandDef(
        t.CommandType.SREQ,
        0x11,
        req_schema=(
            t.Param(
                "Index",
                t.uint16_t,
                (
                    "Specifies the index into the outgoing data request data buffer"
                    "to start the storing of this chunk of data"
                ),
            ),
            t.Param("Data", t.ShortBytes, "Data"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Huge AF incoming message data buffer retrieve command
    DataRetrieve = t.CommandDef(
        t.CommandType.SREQ,
        0x12,
        req_schema=(
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
        ),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Data", t.ShortBytes, "Data"),
        ),
    )

    # proxy for afAPSF_ConfigSet()
    APSFConfigSet = t.CommandDef(
        t.CommandType.SREQ,
        0x13,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint for which to set fragmentation"),
            t.Param(
                "FrameDelay",
                t.uint8_t,
                "APS Fragmentation inter-frame delay in milliseconds",
            ),
            t.Param("WindowSize", t.uint8_t, "APS Fragmentation window size"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # AF Callbacks
    # This command is sent by the device to the user after it receives a data request
    DataConfirm = t.CommandDef(
        t.CommandType.AREQ,
        0x80,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Endpoint", t.uint8_t, "Endpoint of the device"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
        ),
    )

    # This callback message is in response to incoming data to any of the registered
    # endpoints on this device
    IncomingMsg = t.CommandDef(
        t.CommandType.AREQ,
        0x81,
        rsp_schema=(
            t.Param("GroupId", t.GroupId, "The group ID of the device"),
            t.Param("ClusterId", t.ClusterId, "Cluster ID"),
            t.Param(
                "SrcAddr", t.NWK, "Short address of the device sending the message"
            ),
            t.Param("SrcEndpoint", t.uint8_t, "Endpoint of the source device"),
            t.Param("DstEndpoint", t.uint8_t, "Endpoint of the destination device"),
            t.Param(
                "WasBroadcast", t.Bool, "Was the incoming message broadcast or not"
            ),
            t.Param("LQI", t.uint8_t, "Link quality measured during reception"),
            t.Param("SecurityUse", t.Bool, "Is security in use or not"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            t.Param("Data", t.ShortBytes, "Data"),
            # https://e2e.ti.com/support/wireless-connectivity/zigbee-and-thread/f/158/t/455787
            t.Param("MacSrcAddr", t.NWK, "UNDOCUMENTED: MAC Source address"),
            t.Param(
                "MsgResultRadius", t.uint8_t, "UNDOCUMENTED: Messages result radius"
            ),
        ),
    )

    # This callback message is in response to incoming data to any of the registered
    # endpoints on this device when the code is compiled with the INTER_PAN
    # flag defined
    IncomingMsgExt = t.CommandDef(
        t.CommandType.AREQ,
        0x82,
        rsp_schema=(
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
                "WasBroadcast", t.Bool, "Was the incoming message broadcast or not"
            ),
            t.Param("LQI", t.uint8_t, "Link quality measured during reception"),
            t.Param("SecurityUse", t.uint8_t, "Is security in use or not"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            t.Param("Data", t.LongBytes, "Data"),
            # https://e2e.ti.com/support/wireless-connectivity/zigbee-and-thread/f/158/t/455787
            t.Param("MacSrcAddr", t.NWK, "UNDOCUMENTED: MAC Source address"),
            t.Param(
                "MsgResultRadius", t.uint8_t, "UNDOCUMENTED: Messages result radius"
            ),
        ),
    )

    # sent by the device to the user when it determines that an error occurred during
    # a reflected message
    ReflectError = t.CommandDef(
        t.CommandType.AREQ,
        0x83,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Endpoint", t.uint8_t, "Endpoint of the device"),
            t.Param("TSN", t.uint8_t, "Transaction Sequence Number"),
            t.Param("AddrMode", t.AddrMode, "Format of the address"),
            t.Param("Dst", t.NWK, "Destination address -- depends on AddrMode"),
        ),
    )
