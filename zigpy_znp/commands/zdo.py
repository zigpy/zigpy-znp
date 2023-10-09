"""ZDO Interface

This interface allows the tester to issue commands to the ZDO layer in the target
and receive responses. Each of these messages has a corresponding message that is
returned by the target. The response message only indicates that the command message
was received and executed. The result of the command execution will be conveyed to
the tester via a callback message interface"""

from __future__ import annotations

import zigpy.zdo.types

import zigpy_znp.types as t


class SecurityEntry(t.FixedList, item_type=t.uint8_t, length=5):
    pass


class StartupState(t.enum8):
    RestoredNetworkState = 0x00
    NewNetworkState = 0x01
    NotStarted = 0x02


class RouteDiscoveryOptions(t.bitmap8):
    UNICAST = 0x00
    MTO_WITH_ROUTE_CACHE = 0x01
    MTO_WITHOUT_ROUTE_CACHE = 0x03


class RouteStatus(t.enum8):
    INIT = 0
    ACTIVE = 1
    DISC = 2
    LINK_FAIL = 3
    REPAIR = 4


class RouteOptions(t.bitmap8):
    # Used in option of NLME_RouteDiscoveryRequest() and rtgTable[]
    MTO_ROUTE = 0x01

    # Used in option of NLME_RouteDiscoveryRequest() and rtgTable[]
    NO_ROUTE_CACHE = 0x02

    # Used in option of rtgTable[]
    RTG_RECORD = 0x04

    # Sender has route cache. Used in option of rtgTable[]
    MTO_ROUTE_RC = 0x08

    # Sender doesn't have route cache. Used in option of rtgTable[]
    MTO_ROUTE_NRC = 0x10

    # Used in option of route request command frame
    DEST_IEEE_ADDR = 0x20

    # Used in all three places
    MULTICAST_ROUTE = 0x40


class RoutingStatus(t.enum8):
    SUCCESS = 0
    FAIL = 1
    TBL_FULL = 2
    HIGHER_COST = 3
    NO_ENTRY = 4
    INVALID_PATH = 5
    INVALID_PARAM = 6
    SRC_TBL_FULL = 7


class MACCapabilities(t.bitmap8):
    PANCoordinator = 1 << 0
    Router = 1 << 1
    MainsPowered = 1 << 2
    RXWhenIdle = 1 << 3
    Reserved5 = 1 << 4
    Reserved6 = 1 << 5
    SecurityCapable = 1 << 6
    AllocateShortAddrDuringAssocNeeded = 1 << 7


class LeaveOptions(t.bitmap8):
    NONE = 0
    Rejoin = 1 << 0
    RemoveChildren = 1 << 1


class NetworkList(t.LVList, item_type=t.Network, length_type=t.uint8_t):
    pass


class EndpointList(t.LVList, item_type=t.uint8_t, length_type=t.uint8_t):
    pass


class GroupIdList(t.LVList, item_type=t.GroupId, length_type=t.uint8_t):
    pass


class BindEntryList(t.LVList, item_type=zigpy.zdo.types.Binding, length_type=t.uint8_t):
    pass


class BeaconList(t.LVList, item_type=t.Beacon, length_type=t.uint8_t):
    pass


class EnergyValues(t.LVList, item_type=t.uint8_t, length_type=t.uint8_t):
    pass


class ChildInfoList(t.LVList, item_type=t.EUI64, length_type=t.uint8_t):
    pass


class NWKArray(t.CompleteList, item_type=t.NWK):
    pass


class NullableNodeDescriptor(zigpy.zdo.types.NodeDescriptor):
    @classmethod
    def deserialize(cls, data: bytes) -> tuple[NullableNodeDescriptor, bytes]:
        if data == b"\x00":
            return cls(), b""

        return super().deserialize(data)

    def serialize(self) -> bytes:
        # Special case when the node descriptor is completely empty
        if not self.assigned_fields():
            return b"\x00"

        return super().serialize()


class AddrRequestType(t.enum8):
    SINGLE = 0x00
    EXTENDED = 0x01


class ZDO(t.CommandsBase, subsystem=t.Subsystem.ZDO):
    # send a "Network Address Request". This message sends a broadcast message looking
    # for a 16 bit address with a known 64 bit IEEE address. You must subscribe to
    # "ZDO Network Address Response" to receive the response to this message
    NwkAddrReq = t.CommandDef(
        t.CommandType.SREQ,
        0x00,
        req_schema=(
            t.Param(
                "IEEE",
                t.EUI64,
                "Extended address of the device requesting association",
            ),
            t.Param(
                "RequestType",
                AddrRequestType,
                "0x00 -- single device request, 0x01 -- Extended",
            ),
            t.Param(
                "StartIndex", t.uint8_t, "Starting index into the list of children"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request a device's IEEE 64-bit address
    IEEEAddrReq = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param(
                "RequestType",
                AddrRequestType,
                "0x00 -- single device request, 0x01 -- Extended",
            ),
            t.Param(
                "StartIndex", t.uint8_t, "Starting index into the list of children"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # inquire about the Node Descriptor information of the destination device
    NodeDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # inquire about the Power Descriptor information of the destination device
    PowerDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # inquire as to the Simple Descriptor of the destination device's Endpoint
    SimpleDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
            t.Param("Endpoint", t.uint8_t, "application endpoint the data is from"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request a list of active endpoint from the destination device
    ActiveEpReq = t.CommandDef(
        t.CommandType.SREQ,
        0x05,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the device match descriptor
    MatchDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x06,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
            t.Param("ProfileId", t.uint16_t, "profile id of the device"),
            t.Param("InputClusters", t.ClusterIdList, "Input cluster id list"),
            t.Param("OutputClusters", t.ClusterIdList, "Output cluster id list"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request for the destination device's complex descriptor
    ComplexDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x07,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request for the destination device's user descriptor
    UserDescReq = t.CommandDef(
        t.CommandType.SREQ,
        0x08,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the inquiry",
            ),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command will cause the CC2480 device to issue an "End device announce"
    # broadcast packet to the network. This is typically used by an end-device to
    # announce itself to the network
    EndDeviceAnnce = t.CommandDef(
        t.CommandType.SREQ,
        0x0A,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param(
                "IEEE",
                t.EUI64,
                "Extended address of the device generating the request",
            ),
            t.Param("Capabilities", t.uint8_t, "MAC Capabilities"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # write a User Descriptor value to the targeted device
    UserDescSet = t.CommandDef(
        t.CommandType.SREQ,
        0x0B,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "network address of the device generating the set request",
            ),
            t.Param(
                "NWK", t.NWK, "NWK address of the destination device being queried"
            ),
            t.Param("UserDescriptor", t.ShortBytes, "User descriptor array"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # discover the location of a particular system server or servers as indicated by
    # the ServerMask parameter. The destination addressing on this request is
    # 'broadcast to all RxOnWhenIdle devices'
    ServerDiscReq = t.CommandDef(
        t.CommandType.SREQ,
        0x0C,
        req_schema=(
            t.Param(
                "ServerMask", t.uint16_t, "system server capabilities of the device"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request an End Device Bind with the destination device
    EndDeviceBindReq = t.CommandDef(
        t.CommandType.SREQ,
        0x20,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device generating the request",
            ),
            t.Param(
                "LocalCoordinator",
                t.NWK,
                (
                    "local coordinator's short address. In the case of source "
                    "binding, it's the short address of the source address"
                ),
            ),
            t.Param("IEEE", t.EUI64, "Local coordinator's IEEE address"),
            t.Param("Endpoint", t.uint8_t, "device's endpoint"),
            t.Param("ProfileId", t.uint16_t, "profile id of the device"),
            t.Param("InputClusters", t.ClusterIdList, "Input cluster id list"),
            t.Param("OutputClusters", t.ClusterIdList, "Output cluster id list"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request a Bind
    BindReq = t.CommandDef(
        t.CommandType.SREQ,
        0x21,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param("Src", t.EUI64, "Binding source IEEE address"),
            t.Param("SrcEndpoint", t.uint8_t, "binding source endpoint"),
            t.Param("ClusterId", t.ClusterId, "Cluster id to match in messages"),
            t.Param(
                "Address", zigpy.zdo.types.MultiAddress, "Binding address/endpoint"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request a UnBind
    UnBindReq = t.CommandDef(
        t.CommandType.SREQ,
        0x22,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param("Src", t.EUI64, "Binding source IEEE address"),
            t.Param("SrcEndpoint", t.uint8_t, "binding source endpoint"),
            t.Param("ClusterId", t.ClusterId, "Cluster id to match in messages"),
            t.Param(
                "Address", zigpy.zdo.types.MultiAddress, "Unbinding address/endpoint"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the destination device to perform a network discovery
    MgmtNwkDiscReq = t.CommandDef(
        t.CommandType.SREQ,
        0x30,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
            t.Param("ScanDuration", t.uint8_t, "Scanning time"),
            t.Param(
                "StartIndex",
                t.uint8_t,
                "Specifies where to start in the response array",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the destination device to perform a LQI query of other devices
    # in the network
    MgmtLqiReq = t.CommandDef(
        t.CommandType.SREQ,
        0x31,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param(
                "StartIndex",
                t.uint8_t,
                "Specifies where to start in the response array",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the Routing Table of the destination device
    MgmtRtgReq = t.CommandDef(
        t.CommandType.SREQ,
        0x32,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param(
                "StartIndex",
                t.uint8_t,
                "Specifies where to start in the response array",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the Binding Table of the destination device
    MgmtBindReq = t.CommandDef(
        t.CommandType.SREQ,
        0x33,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param(
                "StartIndex",
                t.uint8_t,
                "Specifies where to start in the response array",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request a Management Leave Request for the target device
    MgmtLeaveReq = t.CommandDef(
        t.CommandType.SREQ,
        0x34,
        req_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Short address of the device that will process the "
                "mgmt leave (remote or self)",
            ),
            t.Param(
                "IEEE",
                t.EUI64,
                (
                    "The 64-bit IEEE address of the entity to be removed from the "
                    "network or 0x0000000000000000 if the device removes itself "
                    "from the network."
                ),
            ),
            t.Param(
                "RemoveChildren_Rejoin",
                LeaveOptions,
                "Specifies actions to be performed by "
                "device when leaving the network.",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the Management Direct Join Request of a designated device
    MgmtDirectJoinReq = t.CommandDef(
        t.CommandType.SREQ,
        0x35,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the device to join"),
            t.Param("IEEE", t.EUI64, "IEEE address of the device to join"),
            t.Param("Capabilities", t.uint8_t, "MAC Capabilities"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # set the Permit Join for the destination device
    MgmtPermitJoinReq = t.CommandDef(
        t.CommandType.SREQ,
        0x36,
        req_schema=(
            t.Param("AddrMode", t.AddrMode, "Address mode of DST: short or broadcast"),
            t.Param("Dst", t.NWK, "Short address of the device to join"),
            t.Param("Duration", t.uint8_t, "Specifies the duration to permit joining"),
            t.Param(
                "TCSignificance",
                t.uint8_t,
                "Trust Center Significance  -- unused in the code!",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # allow updating of network configuration parameters or to request information
    # from devices on network conditions in the local operating environment
    MgmtNWKUpdateReq = t.CommandDef(
        t.CommandType.SREQ,
        0x37,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination device"),
            t.Param("DstAddrMode", t.AddrMode, "Destination Address mode"),
            t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
            t.Param(
                "ScanDuration",
                t.uint8_t,
                " - 0x00-0x05: Scanning time\n"
                " - 0xFE: Command to switch channels\n"
                " - 0xFF: Set a new channel mask and NWK manager addr",
            ),
            t.Param(
                "ScanCount",
                t.uint8_t,
                "The number of energy scans to be conducted and reported",
            ),
            t.Param(
                "NwkManagerAddr",
                t.NWK,
                "NWK address for the device with the Network Manager bit set",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # register for a ZDO callback
    MsgCallbackRegister = t.CommandDef(
        t.CommandType.SREQ,
        0x3E,
        req_schema=(
            t.Param(
                "ClusterId",
                t.ClusterId,
                "Cluster id for which to receive ZDO callback",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # de-register for a ZDO callback
    MsgCallbackRemove = t.CommandDef(
        t.CommandType.SREQ,
        0x3F,
        req_schema=(
            t.Param(
                "ClusterId",
                t.ClusterId,
                "Cluster id for which to receive ZDO callback",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # starts the device in the network
    # XXX: In Z-Stack 3, this actually just calls `bdb_StartCommissioning()` and returns
    #  ZSuccess. It just happens that ZSuccess == StartupState.RestoredNetworkState == 0
    StartupFromApp = t.CommandDef(
        t.CommandType.SREQ,
        0x40,
        req_schema=(t.Param("StartDelay", t.uint16_t, "Startup delay"),),
        rsp_schema=(t.Param("State", StartupState, "State after startup"),),
    )

    # Extended version of ZDO to indicate to router devices to create
    # a distributed network
    StartupFromAppExt = t.CommandDef(
        t.CommandType.SREQ,
        0x54,
        req_schema=(
            t.Param("StartDelay", t.uint16_t, "Startup delay"),
            t.Param(
                "Mode", t.Bool, "True -- ZR devices to create a distributed network"
            ),
        ),
        rsp_schema=(t.Param("State", StartupState, "State after startup"),),
    )

    # set the application link key for a given device
    SetLinkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x23,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("LinkKeyData", t.KeyData, "128bit link key"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # remove the application link key for a given device
    RemoveLinkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x24,
        req_schema=(t.Param("IEEE", t.EUI64, "Extended address of the device"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # get the application link key for a given device
    GetLinkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x25,
        req_schema=(t.Param("IEEE", t.EUI64, "Extended address of the device"),),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("LinkKeyData", t.KeyData, "128bit link key"),
        ),
    )

    # initiate a network discovery (active scan)
    NetworkDiscoveryReq = t.CommandDef(
        t.CommandType.SREQ,
        0x26,
        req_schema=(
            t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
            t.Param("ScanDuration", t.uint8_t, "Scanning time"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # request the device to join itself to a parent device on a network
    JoinReq = t.CommandDef(
        t.CommandType.SREQ,
        0x27,
        req_schema=(
            t.Param("LogicalChannel", t.uint8_t, "Channel where the PAN is located"),
            t.Param("PanId", t.PanId, "The PAN Id to join."),
            t.Param("ExtendedPanId", t.ExtendedPanId, "64-bit extended PAN ID"),
            t.Param(
                "ChosenParent",
                t.NWK,
                "Short address of the parent device chosen to join",
            ),
            t.Param("Depth", t.uint8_t, "Depth of the parent"),
            t.Param("StackProfile", t.uint8_t, "Stack profile of the network to use"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # XXX: Undocumented
    SendData = t.CommandDef(
        t.CommandType.SREQ,
        0x28,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("TSN", t.uint8_t, "Transaction sequence number"),
            t.Param("CommandId", t.uint16_t, "ZDO Command ID"),
            t.Param(
                "Data",
                t.Bytes,
                "Data to send",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handles the ZDO security add link key extension message
    SecAddLinkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x42,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("LinkKeyData", t.KeyData, "128bit link key"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO security entry lookup extended extension message
    SecEntryLookupExt = t.CommandDef(
        t.CommandType.SREQ,
        0x43,
        req_schema=(
            t.Param("IEEE", t.EUI64, "Extended address of the device"),
            t.Param("Entry", SecurityEntry, "Valid entry"),
        ),
        rsp_schema=(
            t.Param("AMI", t.uint16_t, "Address manager index"),
            t.Param("KeyNVID", t.uint16_t, "Index to link key table in NV"),
            t.Param("Option", t.uint8_t, "Authentication option for device"),
        ),
    )

    # handle the ZDO security remove device extended extension message
    SecDeviceRemove = t.CommandDef(
        t.CommandType.SREQ,
        0x44,
        req_schema=(t.Param("IEEE", t.EUI64, "Extended address of the device"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO route discovery extension message
    ExtRouteDisc = t.CommandDef(
        t.CommandType.SREQ,
        0x45,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("Options", RouteDiscoveryOptions, "Route options"),
            t.Param("Radius", t.uint8_t, "Broadcast radius"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO route check extension messages
    ExtRouteChk = t.CommandDef(
        t.CommandType.SREQ,
        0x46,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("RtStatus", RouteStatus, "Status value for routing entries"),
            t.Param("Options", RouteOptions, "Route options"),
        ),
        rsp_schema=(t.Param("Status", RoutingStatus, "Route status"),),
    )

    # handle the ZDO extended remove group extension message
    ExtRemoveGroup = t.CommandDef(
        t.CommandType.SREQ,
        0x47,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
            t.Param("GroupId", t.GroupId, "ID to look for group"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO extended remove all group extension message
    ExtRemoveAllGroups = t.CommandDef(
        t.CommandType.SREQ,
        0x48,
        req_schema=(t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO extension find all groups for endpoint message
    ExtFindAllGroupsEndpoint = t.CommandDef(
        t.CommandType.SREQ,
        0x49,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
            # this parameter does not make sense
            t.Param("Groups", t.uint16_t, "List to hold group IDs"),
        ),
        rsp_schema=(t.Param("Groups", GroupIdList, "List of Group IDs"),),
    )

    # handle the ZDO extension find group message
    ExtFindGroup = t.CommandDef(
        t.CommandType.SREQ,
        0x4A,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
            t.Param("GroupId", t.GroupId, "ID to look for group"),
        ),
        rsp_schema=(t.Param("Group", t.Bytes, "Group information"),),
    )

    # handle the ZDO extension add group message
    ExtAddGroup = t.CommandDef(
        t.CommandType.SREQ,
        0x4B,
        req_schema=(
            t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
            t.Param("GroupId", t.GroupId, "ID to look for group"),
            t.Param("GroupName", t.CharacterString, "Group name"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO extension count all groups message
    ExtCountAllGroups = t.CommandDef(
        t.CommandType.SREQ,
        0x4C,
        req_schema=(),
        rsp_schema=(t.Param("GroupCount", t.uint8_t, "Total number of groups"),),
    )

    # handle the ZDO extension Get/Set RxOnIdle to ZMac message
    ExtRxIdle = t.CommandDef(
        t.CommandType.SREQ,
        0x4D,
        req_schema=(
            t.Param("SetFlag", t.uint8_t, "Set or get value"),
            t.Param("SetValue", t.uint8_t, "Value to be set to ZMac message"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO security update network key extension message
    ExtUpdateNwkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x4E,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("KeySeqNum", t.uint8_t, "Key sequence number"),
            t.Param("Key", t.KeyData, "Network key"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO security switch network key extension message
    ExtSwitchNwkKey = t.CommandDef(
        t.CommandType.SREQ,
        0x4F,
        req_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("KeySeqNum", t.uint8_t, "Key sequence number"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle the ZDO extension network message
    ExtNwkInfo = t.CommandDef(
        t.CommandType.SREQ,
        0x50,
        req_schema=(),
        rsp_schema=(
            t.Param("Dst", t.NWK, "Short address of the destination"),
            t.Param("PanId", t.PanId, "The PAN Id to join."),
            t.Param("ParentNWK", t.NWK, "Short address of the parent"),
            t.Param("ExtendedPanId", t.ExtendedPanId, "64-bit extended PAN ID"),
            t.Param("ParentIEEE", t.EUI64, "IEEE address of the parent"),
            t.Param("Channel", t.Channels, "Current Channel"),
        ),
    )

    # handle the ZDO extension Security Manager APS Remove Request message
    ExtSecApsRemoveReq = t.CommandDef(
        t.CommandType.SREQ,
        0x51,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the device"),
            t.Param("IEEE", t.EUI64, "IEEE address of the device"),
            t.Param("ParentNWK", t.NWK, "Short address of the parent"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # forces a network concentrator change by resetting zgConcentratorEnable and
    # zgConcentratorDiscoveryTime from NV and set nwk event
    ForceConcentratorChange = t.CommandDef(
        t.CommandType.SREQ, 0x52, req_schema=(), rsp_schema=()
    )

    # set parameters not settable through NV
    ExtSetParams = t.CommandDef(
        t.CommandType.SREQ,
        0x53,
        req_schema=(t.Param("UseMulticast", t.Bool, "Set or reset of multicast"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # handle ZDO network address of interest request
    NwkAddrOfInterestReq = t.CommandDef(
        t.CommandType.SREQ,
        0x29,
        req_schema=(
            t.Param("NWK", t.NWK, "Short address of the destination"),
            t.Param(
                "NWKAddrOfInterest",
                t.NWK,
                "Short address of the device being queried",
            ),
            t.Param(
                "Cmd",
                t.uint8_t,
                "A valid Cluster ID command as specified by profile",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # ZDO Callbacks
    # return the results to the NwkAddrReq
    NwkAddrRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x80,
        rsp_schema=(
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("IEEE", t.EUI64, "Extended address of the source device"),
            t.Param("NWK", t.NWK, "Short address of the source device"),
            t.Param("NumAssoc", t.uint8_t, "Number of associated devices"),
            t.Param(
                "Index",
                t.uint8_t,
                "Starting index into the list of associated devices",
            ),
            t.Param("Devices", NWKArray, "List of the associated devices"),
        ),
    )

    # return the results to the IEEEAddrReq
    IEEEAddrRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x81,
        rsp_schema=(
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("IEEE", t.EUI64, "Extended address of the source device"),
            t.Param("NWK", t.NWK, "Short address of the source device"),
            t.Param("NumAssoc", t.uint8_t, "Number of associated devices"),
            t.Param(
                "Index",
                t.uint8_t,
                "Starting index into the list of associated devices",
            ),
            t.Param("Devices", NWKArray, "List of the associated devices"),
        ),
    )

    # return the results to the NodeDescReq
    NodeDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x82,
        rsp_schema=(
            t.Param("Src", t.NWK, "The message's source network address."),
            t.Param(
                "Status",
                t.ZDOStatus,
                "This field indicates either SUCCESS or FAILURE.",
            ),
            t.Param("NWK", t.NWK, "Device's short address of this Node descriptor"),
            t.Param(
                "NodeDescriptor",
                NullableNodeDescriptor,
                "Node descriptor",
                optional=True,
            ),
        ),
    )

    # return the results to the PowerDescReq
    PowerDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x83,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param(
                "PowerDescriptor",
                zigpy.zdo.types.PowerDescriptor,
                "Power descriptor response",
            ),
        ),
    )

    # return the results to the SimpleDescReq
    SimpleDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x84,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param(
                "SimpleDescriptor",
                zigpy.zdo.types.SizePrefixedSimpleDescriptor,
                "Simple descriptor",
            ),
        ),
    )

    # return the results to the ActiveEpReq
    ActiveEpRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x85,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param("ActiveEndpoints", EndpointList, "Active endpoints list"),
        ),
    )

    # return the results to the MatchDescReq
    MatchDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x86,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param("MatchList", EndpointList, "Endpoints list"),
        ),
    )

    # return the results to the ComplexDescReq
    ComplexDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x87,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param("ComplexDesc", t.ShortBytes, "Complex descriptor"),
        ),
    )

    # return the results to the UserDescReq
    UserDescRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x88,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
            t.Param("UserDesc", t.ShortBytes, "User descriptor"),
        ),
    )

    # notify the user when the device receives a user descriptor
    UserDescCnf = t.CommandDef(
        t.CommandType.AREQ,
        0x89,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NWK", t.NWK, "Short address of the device response describes"),
        ),
    )

    # return the results to the ServerDiscReq
    ServerDiscRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x8A,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("ServerMask", t.ZDOStatus, "Server mask response"),
        ),
    )

    ParentAnnceRsp = t.CommandDef(
        t.CommandType.AREQ,
        0x9F,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("ChildInfo", ChildInfoList),
        ),
    )

    # return the results to the EndDeviceBindReq
    EndDeviceBindRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xA0,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the BindReq
    BindRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xA1,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the UnBindReq
    UnBindRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xA2,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the MgmtNwkDiscReq
    MgmtNwkDiscRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB0,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("NetworkCount", t.uint8_t, "Total number of entries available"),
            t.Param("Index", t.uint8_t, "Where the response starts"),
            t.Param("Networks", NetworkList, "Discovered networks list"),
        ),
    )

    # return the results to the MgmtLqiReq
    MgmtLqiRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB1,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("Neighbors", zigpy.zdo.types.Neighbors, "Neighbors", optional=True),
        ),
    )

    # return the results to the MgmtRtgReq
    MgmtRtgRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB2,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("Routes", zigpy.zdo.types.Routes, "Routes"),
        ),
    )

    # return the results to the MgmtBingReq
    MgmtBindRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB3,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param(
                "BindTableEntries",
                t.uint8_t,
                "Total number of entries available on the device",
            ),
            t.Param("StartIndex", t.uint8_t, "Index where the response starts"),
            t.Param("BindTableList", BindEntryList, "list of BindEntries"),
        ),
    )

    # return the results to the MgmtLeaveReq
    MgmtLeaveRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB4,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the MgmtDirectJoinReq
    MgmtDirectJoinRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB5,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the MgmtPermitJoinReq
    MgmtPermitJoinRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xB6,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # return the results to the MgmtPermitJoinReq
    MgmtNWKUpdateNotify = t.CommandDef(
        t.CommandType.AREQ,
        0xB8,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param("Status", t.ZDOStatus, "Status"),
            t.Param("ScannedChannels", t.Channels, "Scanned channels"),
            t.Param("TotalTransmissions", t.uint16_t, "Total transmissions"),
            t.Param("TransmissionFailures", t.uint16_t, "Transmission failures"),
            t.Param(
                "EnergyValues",
                EnergyValues,
                "The result of an energy measurement made on this channel",
            ),
        ),
    )

    # indicates ZDO state change
    StateChangeInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC0,
        rsp_schema=(t.Param("State", t.DeviceState, "New ZDO state"),),
    )

    # indicates the ZDO End Device Announce
    EndDeviceAnnceInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC1,
        rsp_schema=(
            t.Param("Src", t.NWK, "Source address of the message."),
            t.Param("NWK", t.NWK, "Specifies the device's short address"),
            t.Param(
                "IEEE",
                t.EUI64,
                "Extended address of the device generating the request",
            ),
            t.Param("Capabilities", MACCapabilities, "MAC Capabilities"),
        ),
    )

    # indicates that Match Descriptor Response has been sent
    MatchDescRspSent = t.CommandDef(
        t.CommandType.AREQ,
        0xC2,
        rsp_schema=(
            t.Param("NWK", t.NWK, "Device's network address"),
            t.Param("InputClusters", t.ClusterIdList, "Input cluster id list"),
            t.Param("OutputClusters", t.ClusterIdList, "Output cluster id list"),
        ),
    )

    # default message for error status
    StatusErrorRsp = t.CommandDef(
        t.CommandType.AREQ,
        0xC3,
        rsp_schema=(
            t.Param("Src", t.NWK, "message's source network address"),
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # indication to inform host device the receipt of a source route to a given device
    SrcRtgInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC4,
        rsp_schema=(
            t.Param(
                "DstAddr",
                t.NWK,
                "Network address of the destination of the source route",
            ),
            t.Param("Relays", t.NWKList, "List of relay devices"),
        ),
    )

    # indication to inform host device the receipt of a beacon notification
    BeaconNotifyInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC5,
        rsp_schema=(t.Param("Beacons", BeaconList, "Beacons list"),),
    )

    # inform the host device of a ZDO join request result
    JoinCnf = t.CommandDef(
        t.CommandType.AREQ,
        0xC6,
        rsp_schema=(
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
            t.Param("Nwk", t.NWK, "device's network address"),
            t.Param("ParentNwk", t.NWK, "Parent's network address"),
        ),
    )

    # indication to inform host device the completion of network discovery scan
    NwkDiscoveryCnf = t.CommandDef(
        t.CommandType.AREQ,
        0xC7,
        rsp_schema=(
            t.Param(
                "Status", t.ZDOStatus, "Status is either Success (0) or Failure (1)"
            ),
        ),
    )

    # ???
    ConcentratorInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC8,
        rsp_schema=(
            t.Param("NWK", t.NWK, "Short address"),
            t.Param("IEEE", t.EUI64, "IEEE address"),
            t.Param("PktCost", t.uint8_t, "Packet cost"),
        ),
    )

    # an indication to inform the host of a device leaving the network
    LeaveInd = t.CommandDef(
        t.CommandType.AREQ,
        0xC9,
        rsp_schema=(
            t.Param(
                "NWK", t.NWK, "Short address of the source of the leave indication"
            ),
            t.Param(
                "IEEE",
                t.EUI64,
                "IEEE address of the source of the leave indication",
            ),
            t.Param("Request", t.Bool, "True -- request, False -- indication"),
            t.Param("Remove", t.Bool, "True -- Remove children"),
            t.Param("Rejoin", t.Bool, "True -- Rejoin"),
        ),
    )

    # ZDO callback for a Cluster Id that the host requested to receive
    # with a MsgCallbackRegister request
    MsgCbIncoming = t.CommandDef(
        t.CommandType.AREQ,
        0xFF,
        rsp_schema=(
            t.Param("Src", t.NWK, "Source address of the ZDO message"),
            t.Param(
                "IsBroadcast",
                t.Bool,
                "Indicates whether the message was a broadcast",
            ),
            t.Param("ClusterId", t.ClusterId, "Cluster Id of this ZDO message"),
            t.Param("SecurityUse", t.uint8_t, "Not used"),
            t.Param("TSN", t.uint8_t, "Transaction sequence number"),
            t.Param(
                "MacDst", t.NWK, "Mac destination short address of the ZDO message"
            ),
            t.Param(
                "Data",
                t.Bytes,
                "Data that corresponds to the cluster ID of the message",
            ),
        ),
    )

    # a ZDO callback for TC Device Indication
    TCDevInd = t.CommandDef(
        t.CommandType.AREQ,
        0xCA,
        rsp_schema=(
            t.Param("SrcNwk", t.NWK, "device's network address"),
            t.Param("SrcIEEE", t.EUI64, "IEEE address of the source"),
            t.Param("ParentNwk", t.NWK, "Parent's network address"),
        ),
    )

    # a ZDO callback for Permit Join Indication
    PermitJoinInd = t.CommandDef(
        t.CommandType.AREQ,
        0xCB,
        rsp_schema=(t.Param("Duration", t.uint8_t, "Permit join duration"),),
    )

    # set rejoin backoff duration and rejoin scan duration for an end device
    SetRejoinParams = t.CommandDef(
        t.CommandType.SREQ,
        # in documentation CmdId=0x26 which conflict with discover req
        0xCC,
        req_schema=(
            t.Param(
                "BackoffDuraation",
                t.uint32_t,
                "Rejoin backoff  duration for end device",
            ),
            t.Param("ScanDuration", t.uint32_t, "Rejoin scan duration for end device"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )
