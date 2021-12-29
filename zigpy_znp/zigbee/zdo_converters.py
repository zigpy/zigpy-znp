from zigpy.zdo.types import ZDOCmd

import zigpy_znp.commands as c

"""
Zigpy expects to be able to directly send and receive ZDO commands.
Z-Stack, however, intercepts all responses and rewrites them to use its MT command set.
We must use proxy functions that rewrite requests and responses based on their cluster.
"""


# The structure of this dict is:
#     {
#         cluster: (
#             zigpy_req_to_mt_req_converter,
#             mt_rsp_callback_matcher,
#             mt_rsp_callback_to_zigpy_rsp_converter,
#         )
#

ZDO_CONVERTERS = {
    ZDOCmd.NWK_addr_req: (
        (
            lambda addr, IEEEAddr, RequestType, StartIndex: c.ZDO.NwkAddrReq.Req(
                IEEE=IEEEAddr,
                RequestType=c.zdo.AddrRequestType(RequestType),
                StartIndex=StartIndex,
            )
        ),
        (
            lambda addr, IEEEAddr, **kwargs: c.ZDO.NwkAddrRsp.Callback(
                partial=True, IEEE=IEEEAddr
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.NWK_addr_rsp,
                {
                    "Status": rsp.Status,
                    "IEEE": rsp.IEEE,
                    "NWKAddr": rsp.NWK,
                    "NumAssocDev": len(rsp.Devices),
                    "StartIndex": rsp.Index,
                    "NWKAddrAssocDevList": rsp.Devices,
                },
            )
        ),
    ),
    ZDOCmd.IEEE_addr_req: (
        (
            lambda addr, NWKAddrOfInterest, RequestType, StartIndex: (
                c.ZDO.IEEEAddrReq.Req(
                    NWK=NWKAddrOfInterest,
                    RequestType=c.zdo.AddrRequestType(RequestType),
                    StartIndex=StartIndex,
                )
            )
        ),
        (
            lambda addr, NWKAddrOfInterest, **kwargs: c.ZDO.IEEEAddrRsp.Callback(
                partial=True, NWK=NWKAddrOfInterest
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.IEEE_addr_rsp,
                {
                    "Status": rsp.Status,
                    "IEEEAddr": rsp.IEEE,
                    "NWKAddr": rsp.NWK,
                    "NumAssocDev": len(rsp.Devices),
                    "StartIndex": rsp.Index,
                    "NWKAddrAssocDevList": rsp.Devices,
                },
            )
        ),
    ),
    ZDOCmd.Node_Desc_req: (
        (
            lambda addr, NWKAddrOfInterest: c.ZDO.NodeDescReq.Req(
                DstAddr=addr.address, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.NodeDescRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Node_Desc_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "NodeDescriptor": rsp.NodeDescriptor,
                },
            )
        ),
    ),
    ZDOCmd.Active_EP_req: (
        (
            lambda addr, NWKAddrOfInterest: c.ZDO.ActiveEpReq.Req(
                DstAddr=addr.address, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.ActiveEpRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Active_EP_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "ActiveEPList": rsp.ActiveEndpoints,
                },
            )
        ),
    ),
    ZDOCmd.Simple_Desc_req: (
        (
            lambda addr, NWKAddrOfInterest, EndPoint: (
                c.ZDO.SimpleDescReq.Req(
                    DstAddr=addr.address,
                    NWKAddrOfInterest=NWKAddrOfInterest,
                    Endpoint=EndPoint,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.SimpleDescRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Simple_Desc_rsp,
                {
                    "Status": rsp.Status,
                    "NWKAddrOfInterest": rsp.NWK,
                    "SimpleDescriptor": rsp.SimpleDescriptor,
                },
            )
        ),
    ),
    ZDOCmd.Mgmt_Permit_Joining_req: (
        (
            lambda addr, PermitDuration, TC_Significant: (
                c.ZDO.MgmtPermitJoinReq.Req(
                    AddrMode=addr.mode,
                    Dst=addr.address,
                    Duration=PermitDuration,
                    TCSignificance=TC_Significant,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtPermitJoinRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (lambda rsp: (ZDOCmd.Mgmt_Permit_Joining_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Leave_req: (
        (
            lambda addr, DeviceAddress, Options: c.ZDO.MgmtLeaveReq.Req(
                DstAddr=addr.address,
                IEEE=DeviceAddress,
                RemoveChildren_Rejoin=c.zdo.LeaveOptions(Options),
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtLeaveRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (lambda rsp: (ZDOCmd.Mgmt_Leave_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_NWK_Update_req: (
        (
            lambda addr, NwkUpdate: c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=addr.address,
                DstAddrMode=addr.mode,
                Channels=NwkUpdate.ScanChannels,
                ScanDuration=NwkUpdate.ScanDuration,
                ScanCount=NwkUpdate.ScanCount,
                # XXX: nwkUpdateId is hard-coded to `_NIB.nwkUpdateId + 1`
                NwkManagerAddr=NwkUpdate.nwkManagerAddr or 0x0000,
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtNWKUpdateNotify.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Mgmt_NWK_Update_rsp,
                {
                    "Status": rsp.Status,
                    "ScannedChannels": rsp.ScannedChannels,
                    "TotalTransmissions": rsp.TotalTransmissions,
                    "TransmissionFailures": rsp.TransmissionFailures,
                    "EnergyValues": rsp.EnergyValues,
                },
            )
        ),
    ),
    ZDOCmd.Bind_req: (
        (
            lambda addr, SrcAddress, SrcEndpoint, ClusterID, DstAddress: (
                c.ZDO.BindReq.Req(
                    Dst=addr.address,
                    Src=SrcAddress,
                    SrcEndpoint=SrcEndpoint,
                    ClusterId=ClusterID,
                    Address=DstAddress,
                )
            )
        ),
        (lambda addr, **kwargs: c.ZDO.BindRsp.Callback(partial=True, Src=addr.address)),
        (lambda rsp: (ZDOCmd.Bind_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Unbind_req: (
        (
            lambda addr, SrcAddress, SrcEndpoint, ClusterID, DstAddress: (
                c.ZDO.UnBindReq.Req(
                    Dst=addr.address,
                    Src=SrcAddress,
                    SrcEndpoint=SrcEndpoint,
                    ClusterId=ClusterID,
                    Address=DstAddress,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.UnBindRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (lambda rsp: (ZDOCmd.Unbind_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Lqi_req: (
        (
            lambda addr, StartIndex: (
                c.ZDO.MgmtLqiReq.Req(
                    Dst=addr.address,
                    StartIndex=StartIndex,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtLqiRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Mgmt_Lqi_rsp,
                {"Status": rsp.Status, "Neighbors": rsp.Neighbors},
            )
        ),
    ),
    ZDOCmd.Mgmt_Rtg_req: (
        (
            lambda addr, StartIndex: (
                c.ZDO.MgmtRtgReq.Req(
                    Dst=addr.address,
                    StartIndex=StartIndex,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtRtgRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (lambda rsp: (ZDOCmd.Mgmt_Rtg_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Bind_req: (
        (
            lambda addr, StartIndex: (
                c.ZDO.MgmtBindReq.Req(
                    Dst=addr.address,
                    StartIndex=StartIndex,
                )
            )
        ),
        (
            lambda addr, **kwargs: c.ZDO.MgmtBindRsp.Callback(
                partial=True, Src=addr.address
            )
        ),
        (
            lambda rsp: (
                ZDOCmd.Mgmt_Bind_rsp,
                {
                    "Status": rsp.Status,
                    "BindingTableEntries": rsp.BindTableEntries,
                    "StartIndex": rsp.StartIndex,
                    "BindingTableList": rsp.BindTableList,
                },
            )
        ),
    ),
}
