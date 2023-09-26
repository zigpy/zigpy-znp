import zigpy_znp.types as t


class DiscreteCommand(t.bitmap8):
    ZDOStart = 0x40
    ResetNwk = 0x80


class ZNP(t.CommandsBase, subsystem=t.Subsystem.ZNP):
    BasicCfg = t.CommandDef(
        t.CommandType.SREQ,
        0x00,
        req_schema=(
            t.Param(
                "BasicRspRate",
                t.uint32_t,
                "Rate at which to generate the basic response",
            ),
            t.Param("ChannelList", t.Channels, "CHANLIST NV item"),
            t.Param("PanId", t.NWK, "PANID NV item"),
            t.Param("LogicalType", t.DeviceLogicalType, "LOGICAL_TYPE NV item"),
            t.Param("CmdDisc", DiscreteCommand, "Discrete command bits"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # These exist in the codebase but the functions are completely empty
    # ZclCfg = t.CommandDef(t.CommandType.SREQ, 0x10, req_schema=(), rsp_schema=())
    # SeCfg = t.CommandDef(t.CommandType.SREQ, 0x20, req_schema=(), rsp_schema=())
