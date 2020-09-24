import zigpy_znp.types as t


class AttributeValue(t.FixedList, item_type=t.uint8_t, length=16):
    pass


class MAC(t.CommandsBase, subsystem=t.Subsystem.MAC):
    # MAC Reset command to reset MAC state machine
    ResetReq = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param(
                "SetDefault",
                t.Bool,
                "TRUE - Set the MAC pib values to default values",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # initialize the MAC
    Init = t.CommandDef(
        t.CommandType.SREQ, 0x02, req_schema=(), rsp_schema=t.STATUS_SCHEMA
    )

    # start the MAC as a coordinator or end device
    StartReq = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param(
                "StartTime",
                t.uint32_t,
                (
                    "The time to begin transmitting beacons relative to "
                    "the received beacon"
                ),
            ),
            t.Param(
                "PanId",
                t.PanId,
                (
                    "The PAN Id to use. This parameter is ignored if Pan "
                    "Coordinator is FALSE"
                ),
            ),
            t.Param("LogicalChannel", t.uint8_t, "The logical channel to use"),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param(
                "BeaconOrder",
                t.uint8_t,
                "The exponent used to calculate the beacon interval",
            ),
            t.Param(
                "SuperFrameOrder",
                t.uint8_t,
                "The exponent used to calculate the superframe duration",
            ),
            t.Param(
                "PanCoordinator",
                t.Bool,
                "Set to TRUE to start a network as PAN coordinator",
            ),
            t.Param(
                "BatteryLifeExt",
                t.uint8_t,
                "full backoff periods following the interframe spacing",
            ),
            t.Param("CoordRealignment", t.uint8_t, "Coordinator realignment"),
            t.Param("RealignKeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Enum for for RealignSecurityLevel
            t.Param(
                "RealignSecurityLevel",
                t.uint8_t,
                "Security level of this data frame",
            ),
            # ToDo: Make this an enum
            t.Param("RealignKeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("RealignKeyIndex", t.uint8_t, "Key index of this frame"),
            t.Param("BeaconKeySource", t.KeySource, "Key source of this data frame"),
            # ToDo: Make this an enum
            t.Param(
                "BeaconSecurityLevel",
                t.uint8_t,
                "Security Level of this data frame",
            ),
            t.Param("BeaconKeyIdMode", t.uint8_t, "Key Id Mode of this data frame"),
            t.Param("BeaconKeyIndex", t.uint8_t, "Key index of this data frame"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request synchronization to the current network beacon
    SyncReq = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(
            t.Param("LogicalChannel", t.uint8_t, "The logical channel to use"),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param(
                "TrackBeacon",
                t.Bool,
                (
                    "Set to TRUE to continue tracking beacons after synchronizing "
                    "with the first beacon. Set to FALSE to only synchronize with "
                    "the first beacon"
                ),
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send (on behalf of the next higher layer) MAC Data Frame packet
    DataReq = t.CommandDef(
        t.CommandType.SREQ,
        0x05,
        req_schema=(
            t.Param(
                "DstAddrModeAddress",
                t.AddrModeAddress,
                "Destination address mode and address",
            ),
            t.Param("DstPanId", t.PanId, "The PAN Id of destination"),
            t.Param("SrcAddrMode", t.AddrMode, "Format of the source address"),
            t.Param("Handle", t.uint8_t, "Handle of the packet"),
            # ToDo: Make this a proper Flags Enum
            t.Param("TxOption", t.uint8_t, "Transmitting options"),
            t.Param(
                "LogicalChannel",
                t.uint8_t,
                "Channel that data frame will be transmitted",
            ),
            t.Param("Power", t.uint8_t, "Power level to use for transmission"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
            t.Param("MSDU", t.ShortBytes, "Actual data that will be sent"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request (on behalf of the next higher layer) an association with a coordinator
    AssociateReq = t.CommandDef(
        t.CommandType.SREQ,
        0x06,
        req_schema=(
            t.Param("LogicalChannel", t.uint8_t, "The logical channel to use"),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param(
                "CoordAddrModeAddress",
                t.AddrModeAddress,
                "Coordinator address mode and address",
            ),
            t.Param("CoordPanId", t.PanId, "The PAN Id of the coordinator"),
            # ToDo: make this a bitflag enum
            t.Param("CapabilityInformation", t.uint8_t, "BitFlag Coordinator"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command is sent by the host to response to the MAC_ASSOCIATE_IND
    AssociateRsp = t.CommandDef(
        t.CommandType.SREQ,
        0x50,
        req_schema=(
            t.Param(
                "IEEE",
                t.EUI64,
                "Extended address of the device requesting association",
            ),
            t.Param("NWK", t.NWK, "Short address of the associated device"),
            # ToDo: make this an enum
            t.Param("AssocStatus", t.uint8_t, "Status of the associaiton"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    #  request (on behalf of the next higher layer) a disassociation of the device
    #  from the coordinator
    DisAssociateReq = t.CommandDef(
        t.CommandType.SREQ,
        0x07,
        req_schema=(
            t.Param(
                "DeviceAddrModeAddress",
                t.AddrModeAddress,
                "Device address mode and address",
            ),
            t.Param("DevicePanId", t.PanId, "Device's PAN Id"),
            # ToDo: Make this an enum
            t.Param("DisassociateReason", t.uint8_t, "Reason for disassociation"),
            t.Param("TxIndirect", t.Bool, "Indirect Transmission"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # read (on behalf of the next higher layer) a MAC PIB attribute
    GetReq = t.CommandDef(
        t.CommandType.SREQ,
        0x08,
        req_schema=(
            # ToDo: Make this an enum
            t.Param("Attribute", t.uint8_t, "MAC PIB Attribute to get"),
        ),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Value", AttributeValue, "Value of the attribute"),
        ),
    )

    # request the device to write a MAC PIB value
    SetReq = t.CommandDef(
        t.CommandType.SREQ,
        0x09,
        req_schema=(
            # ToDo: Make this an enum
            t.Param("Attribute", t.uint8_t, "MAC PIB Attribute to set"),
            t.Param("Value", AttributeValue, "Value of the attribute"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send a request to the device to perform a network scan
    ScanReq = t.CommandDef(
        t.CommandType.SREQ,
        0x0C,
        req_schema=(
            t.Param(
                "ScanChannels",
                t.Channels,
                "Bitmask of channels to scan when starting the device",
            ),
            # ToDo: Make this an enum
            t.Param("ScanType", t.uint8_t, "Specifies the scan type"),
            t.Param(
                "ScanDuration", t.uint8_t, "The exponent used in the scan duration"
            ),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param("MaxResults", t.uint8_t, "Max results (UNDOCUMENTED)"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command is sent by the host to response to the ORPHAN_IND
    OrphanRsp = t.CommandDef(
        t.CommandType.SREQ,
        0x51,
        req_schema=(
            t.Param(
                "IEEE",
                t.EUI64,
                "Extended address of the device requesting association",
            ),
            t.Param("NWK", t.NWK, "Short address of the associated device"),
            t.Param(
                "AssociatedMember",
                t.Bool,
                "True is the orphan is a associated member",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send a MAC data request poll
    PollReq = t.CommandDef(
        t.CommandType.SREQ,
        0x0D,
        req_schema=(
            t.Param(
                "CoordAddrModeAddress",
                t.AddrModeAddress,
                "Coordinator address mode and address",
            ),
            t.Param("CoordPanId", t.PanId, "The PAN Id of the coordinator"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send a request to the device to purge a data frame
    PurgeReq = t.CommandDef(
        t.CommandType.SREQ,
        0x0E,
        req_schema=(t.Param("MsduHandle", t.uint8_t, "MSDU handle"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # send a request to the device to set Rx gain
    SetRxGainReq = t.CommandDef(
        t.CommandType.SREQ,
        0x0F,
        req_schema=(t.Param("Mode", t.Bool, "PA/PNA mode - True/False"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # MAC Callbacks

    # send (on behalf of the next higher layer) an indication of the synchronization
    # loss
    SyncLossInd = t.CommandDef(
        t.CommandType.AREQ,
        0x80,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param(
                "PanId",
                t.PanId,
                "The PAN Id to use. This parameter is ignored if Pan",
            ),
            t.Param("LogicalChannel", t.uint8_t, "The logical channel to use"),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) an association indication message
    AssociateInd = t.CommandDef(
        t.CommandType.AREQ,
        0x81,
        rsp_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("Capabilities", t.uint8_t, "Operating capabilities of the device"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) an association confirmation message
    AssociateCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x82,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC beacon notify indication
    BeaconNotifyInd = t.CommandDef(
        t.CommandType.AREQ,
        0x83,
        rsp_schema=(
            t.Param("BSN", t.uint8_t, "BSN"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param(
                "CoordinatorExtendedAddress",
                t.AddrModeAddress,
                "Extended address of coordinator",
            ),
            t.Param(
                "PanId",
                t.PanId,
                "The PAN Id to use. This parameter is ignored if Pan",
            ),
            t.Param("Superframe", t.uint16_t, "Superframe specification"),
            t.Param("LogicalChannel", t.uint8_t, "The logical channel to use"),
            t.Param("GTSPermit", t.Bool, "True/False - Permit/Not permit GTS"),
            t.Param("LQI", t.uint8_t, "Link quality of the message"),
            t.Param("SecurityFailure", t.uint8_t, "Security failure???"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
            t.Param("PendingAddrSpec", t.uint8_t, "Pending address spec"),
            t.Param(
                "AddressList",
                t.uint8_t,
                "List of address associate with the device",
            ),
            t.Param("NSDU", t.ShortBytes, "Beacon payload"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC data confirmation
    DataCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x84,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Handle", t.uint8_t, "Handle of the message"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param("TimeStamp2", t.uint16_t, "16 bit timestamp of the message"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC data indication
    DataInd = t.CommandDef(
        t.CommandType.AREQ,
        0x85,
        rsp_schema=(
            t.Param("SrcAddrModeAddr", t.AddrModeAddress, "Source address"),
            t.Param("DstAddrModeAddr", t.AddrModeAddress, "Destination address"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param("TimeStamp2", t.uint16_t, "16 bit timestamp of the message"),
            t.Param("SrcPanId", t.PanId, "PAN Id ofo the source address"),
            t.Param("DstPanId", t.PanId, "PAN Id ofo the destination address"),
            t.Param("LQI", t.uint8_t, "Link quality of the message"),
            t.Param("Correlation", t.uint8_t, "Correlation"),
            t.Param("RSSI", t.int8s, "RSSI"),
            t.Param("DSN", t.uint8_t, "DSN"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
            t.Param("Data", t.ShortBytes, "Actual data that will be sent"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC disassociation indication
    DisassociateReq = t.CommandDef(
        t.CommandType.AREQ,
        0x86,
        rsp_schema=(
            t.Param("IEEE", t.EUI64, "EUI64 address of the device leaving the network"),
            # ToDo: Make this an enum
            t.Param("DisassociateReason", t.uint8_t, "Reason for disassociation"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC disassociate confirm
    DisassociateCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x87,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param(
                "DeviceAddrModeAddr",
                t.AddrModeAddress,
                "Address mode address of the device",
            ),
            t.Param("PanId", t.PanId, "The PAN Id of the device"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC orphan indication
    OrphanInd = t.CommandDef(
        t.CommandType.AREQ,
        0x8A,
        rsp_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the orphan device"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC poll confirmation
    PollCnf = t.CommandDef(t.CommandType.AREQ, 0x8B, rsp_schema=t.STATUS_SCHEMA)

    # TODO: investigate the actual structure of this command. The source code indicates
    #       that the response type differs heavily based on the ScanType.
    #       Also, ResultListMaxLength does not appear to be present.
    """
    # send (on behalf of the next higher layer) a MAC scan confirmation
    ScanCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x8C,
        rsp_schema=(
            t.Param(
                "Status", t.Status, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("ED", t.uint8_t, "ED max energy"),
            t.Param("ScanType", t.ScanType, "Specifies the scan type"),
            t.Param("ChannelPage", t.uint8_t, "The channel page to use"),
            t.Param(
                "UnScannedChannelList",
                t.Channels,
                "List of the un-scanned channels",
            ),
            t.Param(
                "ResultListCount", t.uint8_t, "Number of items in the result list"
            ),
            t.Param(
                "ResultListMaxLength",
                t.uint8_t,
                "Max length of the result list in bytes"
            ),
            t.Param("ResultList", t.LVList(t.uint8_t), "Result list"),
        ),
    )
    """

    # send (on behalf of the next higher layer) a MAC communication indicator
    CommStatusInd = t.CommandDef(
        t.CommandType.AREQ,
        0x8D,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("DstAddrMode", t.AddrMode, "Destination address mode"),
            t.Param("SrcIEEE", t.EUI64, "Source address"),
            t.Param("DstIEEE", t.EUI64, "Destination address"),
            t.Param("TimeStamp", t.uint32_t, "The timestamp of the message"),
            t.Param("DevicePanId", t.PanId, "PAN Id of the device"),
            t.Param("Reason", t.uint8_t, "Reason of communication indication"),
            t.Param("KeySource", t.KeySource, "Key Source of this data frame"),
            # ToDo: Make this an enum
            t.Param("SecurityLevel", t.uint8_t, "Security level of this data frame"),
            # ToDo: Make this an enum
            t.Param("KeyIdMode", t.uint8_t, "Key Id Mode of this frame"),
            t.Param("KeyIndex", t.uint8_t, "Key index of this frame"),
        ),
    )

    # send (on behalf of the next higher layer) a MAC start confirmation
    StartCnf = t.CommandDef(t.CommandType.AREQ, 0x8E, rsp_schema=t.STATUS_SCHEMA)

    # send (on behalf of the next higher layer) a MAC Rx enable confirmation
    RxEnableCnf = t.CommandDef(t.CommandType.AREQ, 0x8F, rsp_schema=t.STATUS_SCHEMA)

    # send (on behalf of the next higher layer) a MAC purge confirmation
    PurgeCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x9A,
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("Handle", t.uint8_t, "Handle of the message"),
        ),
    )
