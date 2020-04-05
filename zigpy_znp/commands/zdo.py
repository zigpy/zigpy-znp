"""ZDO Interface

This interface allows the tester to issue commands to the ZDO layer in the target
and receive responses. Each of these messages has a corresponding message that is
returned by the target. The response message only indicates that the command message
was received and executed. The result of the command execution will be conveyed to
the tester via a callback message interface"""

import enum

import zigpy.types
import zigpy.zdo.types

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    BindEntry,
    CommandDef,
    CommandType,
    DeviceState,
    Network,
    CommandsBase,
    Subsystem,
)
import zigpy_znp.types as t


class SecurityEntry(t.FixedList):
    _itemtype = t.uint8_t
    _length = 5


class StartupState(t.enum_uint8, enum.IntEnum):
    RestoredNetworkState = 0x00
    NewNetworkState = 0x01
    NotStarted = 0x02


class RouteDiscoveryOptions(t.enum_uint8, enum.IntEnum):
    Suppress = 0x00
    Enable = 0x01
    Force = 0x02


class MACCapabilities(t.enum_uint8, enum.IntFlag):
    PANCoordinator = 1 << 0
    Router = 1 << 1
    MainsPowered = 1 << 2
    RXWhenIdle = 1 << 3
    Reserved5 = 1 << 4
    Reserved6 = 1 << 5
    SecurityCapable = 1 << 6
    AllocateShortAddrDuringAssocNeeded = 1 << 7


class LeaveOptions(t.enum_uint8, enum.IntFlag):
    NONE = 0
    Rejoin = 1 << 0
    RemoveChildren = 1 << 1


class ZDOCommands(CommandsBase, subsystem=Subsystem.ZDO):
    # send a “Network Address Request”. This message sends a broadcast message looking
    # for a 16 bit address with a known 64 bit IEEE address. You must subscribe to
    # “ZDO Network Address Response” to receive the response to this message
    NwkAddrReq = CommandDef(
        CommandType.SREQ,
        0x00,
        req_schema=t.Schema(
            (
                t.Param(
                    "IEEE",
                    t.EUI64,
                    "Extended address of the device requesting association",
                ),
                t.Param(
                    "RequestType",
                    t.uint8_t,
                    "0x00 -- single device request, 0x01 -- Extended",
                ),
                t.Param(
                    "StartIndex", t.uint8_t, "Starting index into the list of children"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request a device’s IEEE 64-bit address
    IEEEAddrReq = CommandDef(
        CommandType.SREQ,
        0x01,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param(
                    "RequestType",
                    t.uint8_t,
                    "0x00 -- single device request, 0x01 -- Extended",
                ),
                t.Param(
                    "StartIndex", t.uint8_t, "Starting index into the list of children"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # inquire about the Node Descriptor information of the destination device
    NodeDescReq = CommandDef(
        CommandType.SREQ,
        0x02,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # inquire about the Power Descriptor information of the destination device
    PowerDescReq = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # inquire as to the Simple Descriptor of the destination device’s Endpoint
    SimpleDescReq = CommandDef(
        CommandType.SREQ,
        0x04,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
                t.Param("Endpoint", t.uint8_t, "application endpoint the data is from"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request a list of active endpoint from the destination device
    ActiveEpReq = CommandDef(
        CommandType.SREQ,
        0x05,
        req_schema=t.Schema(
            (
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
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the device match descriptor
    MatchDescReq = CommandDef(
        CommandType.SREQ,
        0x06,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
                t.Param("ProfileId", t.uint16_t, "profile id of the device"),
                t.Param(
                    "InputClusters", t.LVList(t.ClusterId), "Input cluster id list"
                ),
                t.Param(
                    "OutputClusters", t.LVList(t.ClusterId), "Output cluster id list"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request for the destination device’s complex descriptor
    ComplexDescReq = CommandDef(
        CommandType.SREQ,
        0x07,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request for the destination device’s user descriptor
    UserDescReq = CommandDef(
        CommandType.SREQ,
        0x08,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the inquiry"
                ),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # This command will cause the CC2480 device to issue an “End device announce”
    # broadcast packet to the network. This is typically used by an end-device to
    # announce itself to the network
    EndDeviceAnnce = CommandDef(
        CommandType.SREQ,
        0x0A,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param(
                    "IEEE",
                    t.EUI64,
                    "Extended address of the device generating the request",
                ),
                t.Param("Capabilities", t.uint8_t, "MAC Capabilities"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # write a User Descriptor value to the targeted device
    UserDescSet = CommandDef(
        CommandType.SREQ,
        0x0B,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst",
                    t.NWK,
                    "network address of the device generating the set request",
                ),
                t.Param(
                    "NWK", t.NWK, "NWK address of the destination device being queried"
                ),
                t.Param("UserDescriptor", t.ShortBytes, "User descriptor array"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # discover the location of a particular system server or servers as indicated by
    # the ServerMask parameter. The destination addressing on this request is
    # ‘broadcast to all RxOnWhenIdle devices’
    ServerDiscReq = CommandDef(
        CommandType.SREQ,
        0x0C,
        req_schema=t.Schema(
            (
                t.Param(
                    "ServerMask", t.uint16_t, "system server capabilities of the device"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request an End Device Bind with the destination device
    EndDeviceBindReq = CommandDef(
        CommandType.SREQ,
        0x20,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst", t.NWK, "Short address of the device generating the request"
                ),
                t.Param(
                    "LocalCoordinator",
                    t.NWK,
                    (
                        "local coordinator’s short address. In the case of source "
                        "binding, it’s the short address of the source address"
                    ),
                ),
                t.Param("IEEE", t.EUI64, "Local coordinator's IEEE address"),
                t.Param("Endpoint", t.uint8_t, "device's endpoint"),
                t.Param("ProfileId", t.uint16_t, "profile id of the device"),
                t.Param(
                    "InputClusters", t.LVList(t.ClusterId), "Input cluster id list"
                ),
                t.Param(
                    "OutputClusters", t.LVList(t.ClusterId), "Output cluster id list"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request a Bind
    BindReq = CommandDef(
        CommandType.SREQ,
        0x21,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param("Src", t.EUI64, "Binding source IEEE address"),
                t.Param("SrcEndpoint", t.uint8_t, "binding source endpoint"),
                t.Param("ClusterId", t.ClusterId, "Cluster id to match in messages"),
                t.Param(
                    "Address", zigpy.zdo.types.MultiAddress, "Binding address/endpoint"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request a UnBind
    UnBindReq = CommandDef(
        CommandType.SREQ,
        0x22,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param("Src", t.EUI64, "Binding source IEEE address"),
                t.Param("SrcEndpoint", t.uint8_t, "binding source endpoint"),
                t.Param("ClusterId", t.ClusterId, "Cluster id to match in messages"),
                t.Param(
                    "Address",
                    t.AddrModeAddress,
                    "Binding address mode destination address",
                ),
                t.Param("DstEndpoint", t.uint8_t, "Binding destination endpoint"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the destination device to perform a network discovery
    MgmtNwkDiscReq = CommandDef(
        CommandType.SREQ,
        0x30,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
                t.Param("ScanDuration", t.uint8_t, "Scanning time"),
                t.Param(
                    "StartIndex",
                    t.uint8_t,
                    "Specifies where to start in the response array",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the destination device to perform a LQI query of other devices
    # in the network
    MgmtLqiReq = CommandDef(
        CommandType.SREQ,
        0x31,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param(
                    "StartIndex",
                    t.uint8_t,
                    "Specifies where to start in the response array",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the Routing Table of the destination device
    MgmtRtgReq = CommandDef(
        CommandType.SREQ,
        0x32,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param(
                    "StartIndex",
                    t.uint8_t,
                    "Specifies where to start in the response array",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the Binding Table of the destination device
    MgmtBindReq = CommandDef(
        CommandType.SREQ,
        0x33,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param(
                    "StartIndex",
                    t.uint8_t,
                    "Specifies where to start in the response array",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request a Management Leave Request for the target device
    MgmtLeaveReq = CommandDef(
        CommandType.SREQ,
        0x34,
        req_schema=t.Schema(
            (
                t.Param(
                    "Dst",
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
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the Management Direct Join Request of a designated device
    MgmtDirectJoinReq = CommandDef(
        CommandType.SREQ,
        0x35,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the device to join"),
                t.Param("IEEE", t.EUI64, "IEEE address of the device to join"),
                t.Param("Capabilities", t.uint8_t, "MAC Capabilities"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # set the Permit Join for the destination device
    MgmtPermitJoinReq = CommandDef(
        CommandType.SREQ,
        0x36,
        req_schema=t.Schema(
            (
                t.Param(
                    "AddrMode", t.AddrMode, "Address mode of DST: short or broadcast"
                ),
                t.Param("Dst", t.NWK, "Short address of the device to join"),
                t.Param(
                    "Duration", t.uint8_t, "Specifies the duration to permit joining"
                ),
                t.Param(
                    "TCSignificance",
                    t.uint8_t,
                    "Trust Center Significance  -- unused in the code!",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # allow updating of network configuration parameters or to request information
    # from devices on network conditions in the local operating environment
    MgmtNWKUpdateReq = CommandDef(
        CommandType.SREQ,
        0x37,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination device"),
                t.Param("DstAddrMode", t.AddrMode, "Destination Address mode"),
                t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
                t.Param("ScanDuration", t.uint8_t, "Scanning time"),
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
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # register for a ZDO callback
    MsgCallbackRegister = CommandDef(
        CommandType.SREQ,
        0x3E,
        req_schema=t.Schema(
            (
                t.Param(
                    "ClusterId",
                    t.ClusterId,
                    "Cluster id for which to receive ZDO callback",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # de-register for a ZDO callback
    MsgCallbackRemove = CommandDef(
        CommandType.SREQ,
        0x3F,
        req_schema=t.Schema(
            (
                t.Param(
                    "ClusterId",
                    t.ClusterId,
                    "Cluster id for which to receive ZDO callback",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # starts the device in the network
    StartupFromApp = CommandDef(
        CommandType.SREQ,
        0x40,
        req_schema=t.Schema((t.Param("StartDelay", t.uint16_t, "Startup delay"),)),
        rsp_schema=t.Schema((t.Param("State", StartupState, "State after startup"),)),
    )

    # Extended version of ZDO to indicate to router devices to create
    # a distributed network
    StartupFromAppExt = CommandDef(
        CommandType.SREQ,
        0x54,
        req_schema=t.Schema(
            (
                t.Param("StartDelay", t.uint16_t, "Startup delay"),
                t.Param(
                    "Mode", t.Bool, "True -- ZR devices to create a distributed network"
                ),
            )
        ),
        rsp_schema=t.Schema((t.Param("State", StartupState, "State after startup"),)),
    )

    # set the application link key for a given device
    SetLinkKey = CommandDef(
        CommandType.SREQ,
        0x23,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param("IEEE", t.EUI64, "Extended address of the device"),
                t.Param("LinkKeyData", zigpy.types.KeyData, "128bit link key"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # remove the application link key for a given device
    RemoveLinkKey = CommandDef(
        CommandType.SREQ,
        0x24,
        req_schema=t.Schema(
            (t.Param("IEEE", t.EUI64, "Extended address of the device"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # get the application link key for a given device
    GetLinkKey = CommandDef(
        CommandType.SREQ,
        0x25,
        req_schema=t.Schema(
            (t.Param("IEEE", t.EUI64, "Extended address of the device"),)
        ),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "Extended address of the device"),
                t.Param("LinkKeyData", zigpy.types.KeyData, "128bit link key"),
            )
        ),
    )

    # initiate a network discovery (active scan)
    NetworkDiscoveryReq = CommandDef(
        CommandType.SREQ,
        0x26,
        req_schema=t.Schema(
            (
                t.Param("Channels", t.Channels, "Bitmask of channels to scan"),
                t.Param("ScanDuration", t.uint8_t, "Scanning time"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # request the device to join itself to a parent device on a network
    JoinReq = CommandDef(
        CommandType.SREQ,
        0x27,
        req_schema=t.Schema(
            (
                t.Param(
                    "LogicalChannel", t.uint8_t, "Channel where the PAN is located"
                ),
                t.Param("PanId", t.PanId, "The PAN Id to join."),
                t.Param("Extended PanId", t.ExtendedPanId, "64-bit extended PAN ID"),
                t.Param(
                    "ChosenParent",
                    t.NWK,
                    "Short address of the parent device chosen to join",
                ),
                t.Param("Depth", t.uint8_t, "Depth of the parent"),
                t.Param(
                    "StackProfile", t.uint8_t, "Stack profile of the network to use"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # set rejoin backoff duration and rejoin scan duration for an end device
    SetRejoinParams = CommandDef(
        CommandType.SREQ,
        # in documentation CmdId=0x26 which conflict with discover req
        0x28,
        req_schema=t.Schema(
            (
                t.Param(
                    "BackoffDuraation",
                    t.uint32_t,
                    "Rejoin backoff  duration for end device",
                ),
                t.Param(
                    "ScanDuration", t.uint32_t, "Rejoin scan duration for end device"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handles the ZDO security add link key extension message
    SecAddLinkKey = CommandDef(
        CommandType.SREQ,
        0x42,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param("IEEE", t.EUI64, "Extended address of the device"),
                t.Param("LinkKeyData", zigpy.types.KeyData, "128bit link key"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO security entry lookup extended extension message
    SecEntryLookupExt = CommandDef(
        CommandType.SREQ,
        0x43,
        req_schema=t.Schema(
            (
                t.Param("IEEE", t.EUI64, "Extended address of the device"),
                t.Param("Entry", SecurityEntry, "Valid entry"),
            )
        ),
        rsp_schema=t.Schema(
            (
                t.Param("AMI", t.uint16_t, "Address manager index"),
                t.Param("KeyNVID", t.uint16_t, "Index to link key table in NV"),
                t.Param("Option", t.uint8_t, "Authentication option for device"),
            )
        ),
    )

    # handle the ZDO security remove device extended extension message
    SecDeviceRemove = CommandDef(
        CommandType.SREQ,
        0x44,
        req_schema=t.Schema(
            (t.Param("IEEE", t.EUI64, "Extended address of the device"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO route discovery extension message
    ExtRouteDisc = CommandDef(
        CommandType.SREQ,
        0x45,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination"),
                t.Param("Options", RouteDiscoveryOptions, "Route options"),
                t.Param("Radius", t.uint8_t, "Broadcast radius"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO route check extension messags
    ExtRouteChk = CommandDef(
        CommandType.SREQ,
        0x46,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination"),
                t.Param("RtStatus", t.uint8_t, "Status value for routing entries"),
                t.Param("Options", t.uint8_t, "Route options"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO extended remove group extension message
    ExtRemoveGroup = CommandDef(
        CommandType.SREQ,
        0x47,
        req_schema=t.Schema(
            (
                t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
                t.Param("GroupId", t.GroupId, "ID to look for group"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO extended remove all group extension message
    ExtRemoveAllGroups = CommandDef(
        CommandType.SREQ,
        0x48,
        req_schema=t.Schema((t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),)),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO extension find all groups for endpoint message
    ExtFindAllGroupsEndpoint = CommandDef(
        CommandType.SREQ,
        0x49,
        req_schema=t.Schema(
            (
                t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
                # this parameter does not make sense
                t.Param("Groups", t.uint16_t, "List to hold group IDs"),
            )
        ),
        rsp_schema=t.Schema(
            (t.Param("Groups", t.LVList(t.GroupId), "List of Group IDs"),)
        ),
    )

    # handle the ZDO extension find group message
    ExtFindGroup = CommandDef(
        CommandType.SREQ,
        0x4A,
        req_schema=t.Schema(
            (
                t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
                t.Param("GroupId", t.GroupId, "ID to look for group"),
            )
        ),
        rsp_schema=t.Schema((t.Param("Group", t.Bytes, "Group information"),)),
    )

    # handle the ZDO extension add group message
    ExtAddGroup = CommandDef(
        CommandType.SREQ,
        0x4B,
        req_schema=t.Schema(
            (
                t.Param("Endpoint", t.uint8_t, "Endpoint to look for"),
                t.Param("GroupId", t.GroupId, "ID to look for group"),
                t.Param("GroupName", t.CharacterString, "Group name"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO extension count all groups message
    ExtCountAllGroups = CommandDef(
        CommandType.SREQ,
        0x4C,
        req_schema=t.Schema(),
        rsp_schema=t.Schema(
            (t.Param("GroupCount", t.uint8_t, "Total number of groups"),)
        ),
    )

    # handle the ZDO extension Get/Set RxOnIdle to ZMac message
    ExtRxIdle = CommandDef(
        CommandType.SREQ,
        0x4D,
        req_schema=t.Schema(
            (
                t.Param("SetFlag", t.uint8_t, "Set or get value"),
                t.Param("SetValue", t.uint8_t, "Value to be set to ZMac message"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO security update network key extension message
    ExtUpdateNwkKey = CommandDef(
        CommandType.SREQ,
        0x4E,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination"),
                t.Param("KeySeqNum", t.uint8_t, "Key sequence number"),
                t.Param("Key", zigpy.types.KeyData, "Network key"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO security switch network key extension message
    ExtSwitchNwkKey = CommandDef(
        CommandType.SREQ,
        0x4F,
        req_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination"),
                t.Param("KeySeqNum", t.uint8_t, "Key sequence number"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle the ZDO extension network message
    ExtNwkInfo = CommandDef(
        CommandType.SREQ,
        0x50,
        req_schema=t.Schema(),
        rsp_schema=t.Schema(
            (
                t.Param("Dst", t.NWK, "Short address of the destination"),
                t.Param("PanId", t.PanId, "The PAN Id to join."),
                t.Param("ParentNWK", t.NWK, "Short address of the parent"),
                t.Param("Extended PanId", t.ExtendedPanId, "64-bit extended PAN ID"),
                t.Param("ParentIEEE", t.EUI64, "IEEE address of the parent"),
                t.Param("Channel", t.Channels, "Current Channel"),
            )
        ),
    )

    # handle the ZDO extension Security Manager APS Remove Request message
    ExtSecApsRemoveReq = CommandDef(
        CommandType.SREQ,
        0x51,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the device"),
                t.Param("IEEE", t.EUI64, "IEEE address of the device"),
                t.Param("ParentNWK", t.NWK, "Short address of the parent"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # forces a network concentrator change by resetting zgConcentratorEnable and
    # zgConcentratorDiscoveryTime from NV and set nwk event
    ForceConcentratorChange = CommandDef(
        CommandType.SREQ, 0x52, req_schema=t.Schema(), rsp_schema=t.Schema()
    )

    # set parameters not settable through NV
    ExtSetParams = CommandDef(
        CommandType.SREQ,
        0x53,
        req_schema=t.Schema(
            (t.Param("UseMulticast", t.Bool, "Set or reset of multicast"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # handle ZDO network address of interest request
    NwkAddrOfInterestReq = CommandDef(
        CommandType.SREQ,
        0x29,
        req_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Short address of the destination"),
                t.Param(
                    "NWKAddrOfInterest",
                    t.NWK,
                    "Short address of the device being queried",
                ),
                t.Param(
                    "Cmd",
                    t.uint8_t,
                    "A valid Cluser ID command as specified by profile",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # ZDO Callbacks
    # return the results to the NwkAddrReq
    NwkAddrRsp = CommandDef(
        CommandType.AREQ,
        0x80,
        req_schema=t.Schema(),
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "Extended address of the source device"),
                t.Param("NWK", t.NWK, "Short address of the source device"),
                t.Param(
                    "Index",
                    t.uint8_t,
                    "Starting index into the list of associated devices",
                ),
                t.Param("Devices", t.LVList(t.NWK), "List of the associated devices"),
            )
        ),
    )

    # return the results to the IEEEAddrReq
    IEEEAddrRsp = CommandDef(
        CommandType.AREQ,
        0x81,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "Extended address of the source device"),
                t.Param("NWK", t.NWK, "Short address of the source device"),
                t.Param(
                    "Index",
                    t.uint8_t,
                    "Starting index into the list of associated devices",
                ),
                t.Param("Devices", t.LVList(t.NWK), "List of the associated devices"),
            )
        ),
    )

    # return the results to the NodeDescReq
    NodeDescRsp = CommandDef(
        CommandType.AREQ,
        0x82,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("IEEE", t.EUI64, "Extended address of the source device"),
                t.Param("NWK", t.NWK, "Short address of the source device"),
                t.Param(
                    "NodeDescriptor", zigpy.zdo.types.NodeDescriptor, "Node descriptor"
                ),
            )
        ),
    )

    # return the results to the PowerDescReq
    PowerDescRsp = CommandDef(
        CommandType.AREQ,
        0x83,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param(
                    "PowerDescriptor",
                    zigpy.zdo.types.PowerDescriptor,
                    "Power descriptor response",
                ),
            )
        ),
    )

    # return the results to the SimpleDescReq
    SimpleDescRsp = CommandDef(
        CommandType.AREQ,
        0x84,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param("Len", t.uint8_t, "Length of the simple descriptor"),
                t.Param(
                    "SimpleDescriptor",
                    zigpy.zdo.types.SimpleDescriptor,
                    "Simple descriptor",
                ),
            )
        ),
    )

    # return the results to the ActiveEpReq
    ActiveEpRsp = CommandDef(
        CommandType.AREQ,
        0x85,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param(
                    "ActiveEndpoints", t.LVList(t.uint8_t), "Active endpoints list"
                ),
            )
        ),
    )

    # return the results to the MatchDescReq
    MatchDescRsp = CommandDef(
        CommandType.AREQ,
        0x86,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param("MatchList", t.LVList(t.uint8_t), "Endpoints list"),
            )
        ),
    )

    # return the results to the ComplexDescReq
    ComplexDescRsp = CommandDef(
        CommandType.AREQ,
        0x87,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param("ComplexDesc", t.ShortBytes, "Complex descriptor"),
            )
        ),
    )

    # return the results to the UserDescReq
    UserDescRsp = CommandDef(
        CommandType.AREQ,
        0x88,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
                t.Param("UserDesc", t.ShortBytes, "User descriptor"),
            )
        ),
    )

    # notify the user when the device receives a user descriptor
    UserDescCnf = CommandDef(
        CommandType.AREQ,
        0x89,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NWK", t.NWK, "Short address of the device response describes"),
            )
        ),
    )

    # return the results to the ServerDiscReq
    ServerDiscRsp = CommandDef(
        CommandType.AREQ,
        0x8A,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("ServerMask", t.Status, "Server mask response"),
            )
        ),
    )

    # return the results to the EndDeviceBindReq
    EndDeviceBindRsp = CommandDef(
        CommandType.AREQ,
        0xA0,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # return the results to the BindReq
    BindRsp = CommandDef(
        CommandType.AREQ,
        0xA1,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # return the results to the UnBindReq
    UnBindRsp = CommandDef(
        CommandType.AREQ,
        0xA2,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # return the results to the MgmtNwkDiscReq
    MgmtNwkDiscRsp = CommandDef(
        CommandType.AREQ,
        0xB0,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("NetworkCount", t.uint8_t, "Total number of entries available"),
                t.Param("Index", t.uint8_t, "Where the response starts"),
                t.Param("Networks", t.LVList(Network), "Discovered networks list"),
            )
        ),
    )

    # return the results to the MgmtLqiReq
    MgmtLqiRsp = CommandDef(
        CommandType.AREQ,
        0xB1,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Neighbours", zigpy.zdo.types.Neighbors, "Neighbours"),
            )
        ),
    )

    # return the results to the MgmtRtgReq
    MgmtRtgRsp = CommandDef(
        CommandType.AREQ,
        0xB2,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Routes", zigpy.zdo.types.Routes, "Routes"),
            )
        ),
    )

    # return the results to the MgmtBingReq
    MgmtBindRsp = CommandDef(
        CommandType.AREQ,
        0xB3,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param(
                    "BindTableEntries",
                    t.uint8_t,
                    "Total number of entries available on the device",
                ),
                t.Param("Index", t.uint8_t, "Index where the response starts"),
                t.Param("BindTable", t.LVList(BindEntry), "list of BindEntries"),
            )
        ),
    )

    # return the results to the MgmtLeaveReq
    MgmtLeaveRsp = CommandDef(
        CommandType.AREQ,
        0xB4,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # return the results to the MgmtDirectJoinReq
    MgmtDirectJoinRsp = CommandDef(
        CommandType.AREQ,
        0xB5,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # return the results to the MgmtPermitJoinReq
    MgmtPermitJoinRsp = CommandDef(
        CommandType.AREQ,
        0xB6,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # indicates ZDO state change
    StateChangeInd = CommandDef(
        CommandType.AREQ,
        0xC0,
        rsp_schema=t.Schema((t.Param("State", DeviceState, "New ZDO state"),)),
    )

    # indicates the ZDO End Device Announce
    EndDeviceAnnceInd = CommandDef(
        CommandType.AREQ,
        0xC1,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "Source address of the message."),
                t.Param("NWK", t.NWK, "Specifies the device’s short address"),
                t.Param(
                    "IEEE",
                    t.EUI64,
                    "Extended address of the device generating the request",
                ),
                t.Param("Capabilities", MACCapabilities, "MAC Capabilities"),
            )
        ),
    )

    # indicates that Match Descriptor Response has been sent
    MatchDescRspSent = CommandDef(
        CommandType.AREQ,
        0xC2,
        rsp_schema=t.Schema(
            (
                t.Param("NWK", t.NWK, "Device's network address"),
                t.Param(
                    "InputClusters", t.LVList(t.ClusterId), "Input cluster id list"
                ),
                t.Param(
                    "OutputClusters", t.LVList(t.ClusterId), "Output cluster id list"
                ),
            )
        ),
    )

    # default message for error status
    StatusErrorRsp = CommandDef(
        CommandType.AREQ,
        0xC3,
        rsp_schema=t.Schema(
            (
                t.Param("Src", t.NWK, "message's source network address"),
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
            )
        ),
    )

    # indication to inform host device the receipt of a source route to a given device
    SrcRtgInd = CommandDef(
        CommandType.AREQ,
        0xC4,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Dst",
                    t.NWK,
                    "Network address of the destination of the source route",
                ),
                t.Param("Relays", t.LVList(t.NWK), "List of relay devices"),
            )
        ),
    )

    # indication to inform host device the receipt of a beacon notification
    BeaconNotifyInd = CommandDef(
        CommandType.AREQ,
        0xC5,
        rsp_schema=t.Schema((t.Param("Beacons", t.LVList(t.Beacon), "Beacons list"),)),
    )

    # inform the host device of a ZDO join request result
    JoinCnf = CommandDef(
        CommandType.AREQ,
        0xC6,
        rsp_schema=t.Schema(
            (
                t.Param(
                    "Status", t.Status, "Status is either Success (0) or Failure (1)"
                ),
                t.Param("Nwk", t.NWK, "device's network address"),
                t.Param("ParentNwk", t.NWK, "Parent's network address"),
            )
        ),
    )

    # indication to inform host device the completion of network discovery scan
    NwkDiscoveryCnf = CommandDef(CommandType.AREQ, 0xC7, rsp_schema=STATUS_SCHEMA)

    # an indication to inform the host of a device leaving the network
    LeaveInd = CommandDef(
        CommandType.AREQ,
        0xC9,
        rsp_schema=t.Schema(
            (
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
            )
        ),
    )

    # ZDO callback for a Cluster Id that the host requested to receive
    # with a MsgCallbackRegister request
    MsgCbIncoming = CommandDef(
        CommandType.AREQ,
        0xFF,
        rsp_schema=t.Schema(
            (
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
            )
        ),
    )

    # a ZDO callback for TC Device Indication
    TCDevInd = CommandDef(
        CommandType.AREQ,
        0xCA,
        rsp_schema=t.Schema(
            (
                t.Param("SrcNwk", t.NWK, "device's network address"),
                t.Param("SrcIEEE", t.EUI64, "IEEE address of the source"),
                t.Param("ParentNwk", t.NWK, "Parent's network address"),
            )
        ),
    )

    # a ZDO callback for Permit Join Indication
    PermitJoinInd = CommandDef(
        CommandType.AREQ,
        0xCB,
        rsp_schema=t.Schema((t.Param("Duration", t.uint8_t, "Permit join duration"),)),
    )
