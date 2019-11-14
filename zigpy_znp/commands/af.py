import enum

from zigpy_znp.commands.types import CommandDef, CommandType
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
                t.Param("InputClusters", t.LVList(t.uint16_t), "Input cluster list"),
                t.Param("OutputClusters", t.LVList(t.uint16_t), "Output cluster list"),
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
                t.Param("DstAddrMode", t.uint8_t, "Destination address mode enum"),
                t.Param("DstAddr", t.uint64_t, "Address of the destination device"),
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
