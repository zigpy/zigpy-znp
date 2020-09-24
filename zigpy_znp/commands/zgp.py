"""Green Power devices and Green Power infrastructure interface."""

import zigpy_znp.types as t


class ZGP(t.CommandsBase, subsystem=t.Subsystem.ZGP):
    DataReq = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param("Action", t.Bool, "True/False -- add/remove GPDF into the queue"),
            t.Param("TXOptions", t.uint8_t, "ZGP TX Options"),
            t.Param(
                "ApplicationId",
                t.uint8_t,
                (
                    "ApplicationID of the GPD to which the ASDU will be sent; "
                    "ApplicationID 0x00 indicates the usage of the SrcID; "
                    "ApplicationID 0x02 indicates the usage of the GPD IEEE"
                ),
            ),
            t.Param(
                "SrcId",
                t.uint32_t,
                "The identifier of the GPD entity to which the ASDU will be sent",
            ),
            t.Param("IEEE", t.EUI64, "IEEE address"),
            t.Param(
                "Endpoint",
                t.uint8_t,
                "GPD ep used in combination with GPD IEEE for APPid of 0b010",
            ),
            t.Param("CommandId", t.uint8_t, "GPD command id"),
            t.Param("ASDU", t.ShortBytes, "GPD ASDU"),
            t.Param("Handle", t.uint8_t, "GPEP handle to match req to confirmation"),
            t.Param("LifeTime", t.uint24_t, "The lifetime of the packet"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send security data into # the dGP stub
    SecRsp = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(
            t.Param(
                "Status",
                t.uint8_t,
                "The status code as returned by the GP endpoint",
            ),
            t.Param("Handle", t.uint8_t, "GPEP handle to match req to confirmation"),
            t.Param(
                "ApplicationId",
                t.uint8_t,
                (
                    "ApplicationID of the GPD to which the ASDU will be sent; "
                    "ApplicationID 0x00 indicates the usage of the SrcID; "
                    "ApplicationID 0x02 indicates the usage of the GPD IEEE"
                ),
            ),
            t.Param(
                "SrcId",
                t.uint32_t,
                "The identifier of the GPD entity to which the ASDU will be sent",
            ),
            t.Param("IEEE", t.EUI64, "IEEE address"),
            t.Param(
                "Endpoint",
                t.uint8_t,
                "GPD ep used in combination with GPD IEEE for APPid of 0b010",
            ),
            t.Param("SecurityLevel", t.uint8_t, "Security level for GPDF processing"),
            t.Param("KeyType", t.uint8_t, "The security key type"),
            t.Param("KeyData", t.KeyData, "Security key"),
            t.Param("FrameCounter", t.uint32_t, "The security frame counter value"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # ZGP Callbacks
    # Green power confirm is a message that provides a mechanism for the Green Power
    # EndPoint in the host processor to understand the status of a previous request
    # to send a GPDF
    DataCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x05,
        req_schema=(
            t.Param(
                "Status",
                t.uint8_t,
                "The status code as returned by the GP endpoint",
            ),
            t.Param("Handle", t.uint8_t, "handle to match req to confirmation"),
        ),
    )

    # This message provides a mechanism for dGP stub to request security data from the
    # Green Power EndPoint in the host processor
    SecReq = t.CommandDef(
        t.CommandType.AREQ,
        0x03,
        req_schema=(
            t.Param(
                "ApplicationId",
                t.uint8_t,
                (
                    "ApplicationID of the GPD to which the ASDU will be sent; "
                    "ApplicationID 0x00 indicates the usage of the SrcID; "
                    "ApplicationID 0x02 indicates the usage of the GPD IEEE"
                ),
            ),
            t.Param(
                "SrcId",
                t.uint32_t,
                "The identifier of the GPD entity to which the ASDU will be sent",
            ),
            t.Param("IEEE", t.EUI64, "IEEE address"),
            t.Param(
                "Endpoint",
                t.uint8_t,
                "GPD ep used in combination with GPD IEEE for APPid of 0b010",
            ),
            t.Param("SecurityLevel", t.uint8_t, "Security level for GPDF processing"),
            t.Param("KeyType", t.uint8_t, "The security key type"),
            t.Param("FrameCounter", t.uint32_t, "The security frame counter value"),
            t.Param(
                "Handle", t.uint8_t, "dGP stub handle to match req to confirmation"
            ),
        ),
    )

    # This message provides a mechanism for identifying and conveying a received
    # GPDF to the Green Power EndPoint in the host processor
    DataInd = t.CommandDef(
        t.CommandType.AREQ,
        0x04,
        req_schema=(
            t.Param("Status", t.uint8_t, "The status code as returned by the dGP stub"),
            t.Param(
                "RSSI",
                t.int8s,
                "The RSSI delivered by the MAC on receipt of this frame",
            ),
            t.Param("LQI", t.uint8_t, "Link quality measured during reception"),
            t.Param("SeqNum", t.uint8_t, "The sequence number from MAC header of MPDU"),
            t.Param("SrcAddrMode", t.AddrMode, "The source addressing mode of MPDU"),
            t.Param("SrcPanId", t.PanId, "The source PAN Id"),
            # ToDo: ugh, this could be ieee depending on addressing mode
            t.Param("SrcNWK", t.NWK, "The source address of the GPD entity"),
            t.Param(
                "DstAddrMode", t.AddrMode, "The destination addressing mode of MPDU"
            ),
            t.Param("DstPanId", t.PanId, "The destination PAN Id"),
            # ToDo: ugh, this could be ieee depending on addressing mode
            t.Param("DstNWK", t.NWK, "The destination address of the GPD entity"),
            t.Param("MPDU", t.ShortBytes, "GP MPDU"),
        ),
    )
