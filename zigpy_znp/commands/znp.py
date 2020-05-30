import zigpy_znp.types as t


class ZNP(t.CommandsBase, subsystem=t.Subsystem.ZNP):
    BasicReq = t.CommandDef(
        t.CommandType.SREQ, 0x00, req_schema=t.Schema(), rsp_schema=t.Schema(),
    )
