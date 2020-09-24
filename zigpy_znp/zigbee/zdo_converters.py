from zigpy.zdo.types import ZDOCmd

import zigpy_znp.types as t
import zigpy_znp.commands as c

"""
Zigpy expects to be able to directly send and receive ZDO commands.
Z-Stack, however, intercepts all responses and rewrites them to use its MT command set.
We use setup proxy functions that rewrite requests and responses based on their cluster.
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
    ZDOCmd.Node_Desc_req: (
        (
            lambda addr, device, NWKAddrOfInterest: c.ZDO.NodeDescReq.Req(
                DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (lambda addr: c.ZDO.NodeDescRsp.Callback(partial=True, Src=addr)),
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
            lambda addr, device, NWKAddrOfInterest: c.ZDO.ActiveEpReq.Req(
                DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest
            )
        ),
        (lambda addr: c.ZDO.ActiveEpRsp.Callback(partial=True, Src=addr)),
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
            lambda addr, device, NWKAddrOfInterest, EndPoint: (
                c.ZDO.SimpleDescReq.Req(
                    DstAddr=addr, NWKAddrOfInterest=NWKAddrOfInterest, Endpoint=EndPoint
                )
            )
        ),
        (lambda addr: c.ZDO.SimpleDescRsp.Callback(partial=True, Src=addr)),
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
            lambda addr, device, PermitDuration, TC_Significant: (
                c.ZDO.MgmtPermitJoinReq.Req(
                    AddrMode=t.AddrMode.NWK,
                    Dst=addr,
                    Duration=PermitDuration,
                    TCSignificance=TC_Significant,
                )
            )
        ),
        (lambda addr: c.ZDO.MgmtPermitJoinRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Mgmt_Permit_Joining_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Leave_req: (
        (
            lambda addr, device, DeviceAddress, Options: c.ZDO.MgmtLeaveReq.Req(
                DstAddr=addr,
                IEEE=device.ieee,
                RemoveChildren_Rejoin=c.zdo.LeaveOptions(Options),
            )
        ),
        (lambda addr: c.ZDO.MgmtLeaveRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Mgmt_Leave_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Bind_req: (
        (
            lambda addr, device, SrcAddress, SrcEndpoint, ClusterID, DstAddress: (
                c.ZDO.BindReq.Req(
                    Dst=addr,
                    Src=SrcAddress,
                    SrcEndpoint=SrcEndpoint,
                    ClusterId=ClusterID,
                    Address=DstAddress,
                )
            )
        ),
        (lambda addr: c.ZDO.BindRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Bind_rsp, {"Status": rsp.Status})),
    ),
    ZDOCmd.Mgmt_Lqi_req: (
        (
            lambda addr, device, StartIndex: (
                c.ZDO.MgmtLqiReq.Req(
                    Dst=addr,
                    StartIndex=StartIndex,
                )
            )
        ),
        (lambda addr: c.ZDO.MgmtLqiRsp.Callback(partial=True, Src=addr)),
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
                c.ZDO.MgmtLqiReq.Req(
                    Dst=addr,
                    StartIndex=StartIndex,
                )
            )
        ),
        (lambda addr: c.ZDO.MgmtRtgRsp.Callback(partial=True, Src=addr)),
        (lambda rsp: (ZDOCmd.Mgmt_Rtg_rsp, {"Status": rsp.Status})),
    ),
}
