import zigpy_znp.types as t


class APP(t.CommandsBase, subsystem=t.Subsystem.APP):
    # This command is sent to the target in order to test the functions defined
    # for individual applications.
    # This command sends a raw data to an application
    Msg = t.CommandDef(
        t.CommandType.SREQ,
        0x00,
        req_schema=(
            t.Param(
                "Endpoint",
                t.uint8_t,
                "Application endpoint of the outgoing message",
            ),
            t.Param("DstAddr", t.NWK, "Destination address of the outgoing message"),
            t.Param(
                "DstEndpoint",
                t.uint8_t,
                "Destination endpoint of the outgoing message",
            ),
            t.Param("ClusterId", t.ClusterId, "Cluster ID"),
            t.Param("Data", t.ShortBytes, "Data request"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # This command is used by tester to issue user's defined commands to the
    # application
    UserTest = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param(
                "SrcEndpoint",
                t.uint8_t,
                "Source Endpoint of the user-defined command",
            ),
            t.Param("CommandId", t.uint16_t, "Command Id of the user-defined command"),
            t.Param("Parameter1", t.uint16_t, "Parameter #1 of the command"),
            t.Param("Parameter2", t.uint16_t, "Parameter #2 of the command"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )
