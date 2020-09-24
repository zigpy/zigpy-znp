"""This interface allows tester to interact with the simple API interface."""

import zigpy_znp.types as t


class SAPI(t.CommandsBase, subsystem=t.Subsystem.SAPI):
    # reset the device by using a soft reset (i.e. a jump to the reset vector) vice a
    # hardware reset (i.e. watchdog reset.)
    ZBSystemReset = t.CommandDef(t.CommandType.AREQ, 0x09, req_schema=())

    # start the ZigBee stack
    ZBStartReq = t.CommandDef(t.CommandType.SREQ, 0x00, req_schema=(), rsp_schema=())

    # control the joining permissions and thus allows or disallows new devices
    # from joining the network
    ZBPermitJoiningReq = t.CommandDef(
        t.CommandType.SREQ,
        0x08,
        req_schema=(
            t.Param(
                "NWK",
                t.NWK,
                (
                    "Short address of the device for which the joining "
                    "permissions should be set"
                ),
            ),
            t.Param(
                "duration",
                t.uint8_t,
                "amount of time in seconds to allow new device to join",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # establishes or removes a 'binding' between two devices. Once bound, an
    # application can send messages to a device by referencing the commandId
    # for the binding
    ZBBindDevice = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param("Create", t.Bool, "True to create binding, False to remove"),
            t.Param("CommandId", t.uint16_t, "The identifier of the binding"),
            t.Param("IEEE", t.EUI64, "IEEE address of the device to bind to"),
        ),
        rsp_schema=(),
    )

    # puts the device into the Allow Binding Mode for a given period of time. A peer
    # device can establish a binding to a device in the Allow Binding Mode by calling
    # zb_BindDevice with a destination address of NULL
    ZBAllowBind = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(
            t.Param(
                "duration",
                t.uint8_t,
                "amount of time in seconds to allow new device to join",
            ),
        ),
        rsp_schema=(),
    )

    # initiates transmission of data to a peer device
    ZBSendDataRequest = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param("Destination", t.NWK, "Short address of the destination"),
            t.Param("CommandId", t.uint16_t, "The command id to send with the message"),
            t.Param(
                "Handle",
                t.uint8_t,
                "A handle used to Identify the send data request",
            ),
            t.Param("Ack", t.Bool, "True if requesting ACK from the destination"),
            t.Param(
                "Radius", t.uint8_t, "The max number of hops the packet can travel"
            ),
            t.Param("Data", t.ShortBytes, "Data"),
        ),
        rsp_schema=(),
    )

    # get a configuration property from nonvolatile memory
    ZBReadConfiguration = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(
            t.Param("ConfigId", t.uint8_t, "ID of the configuration property to read"),
        ),
        rsp_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("ConfigId", t.uint8_t, "ID of the configuration property to read"),
            t.Param("Value", t.ShortBytes, "Value"),
        ),
    )

    # write a configuration property from nonvolatile memory
    ZBWriteConfiguration = t.CommandDef(
        t.CommandType.SREQ,
        0x05,
        req_schema=(
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
            t.Param("ConfigId", t.uint8_t, "ID of the configuration property to read"),
            t.Param("Value", t.ShortBytes, "Value"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # retrieves a Device Information Property
    ZBGetDeviceInfo = t.CommandDef(
        t.CommandType.SREQ,
        0x06,
        req_schema=(
            t.Param("Param", t.uint8_t, "The identifier for deice information"),
        ),
        rsp_schema=(
            t.Param("Param", t.uint8_t, "The identifier for deice information"),
            t.Param("Value", t.uint16_t, "Value"),
        ),
    )

    #  determine the short address for a device in the network. The device
    # initiating a call to zb_FindDeviceRequest and the device being discovered must
    # both be a member of the same network. When the search is complete,
    # the zv_FindDeviceConfirm callback function is called
    ZBFindDeviceReq = t.CommandDef(
        t.CommandType.SREQ,
        0x07,
        req_schema=(t.Param("SearchKey", t.EUI64, "IEEE address of the device"),),
        rsp_schema=(),
    )

    # SAPI CallBacks
    # this callback is called by the ZigBee stack after a start request
    # operation completes
    ZBStartConfirm = t.CommandDef(t.CommandType.AREQ, 0x80, req_schema=t.STATUS_SCHEMA)

    # This callback is called by the ZigBee stack after a bind operation completes
    ZBBindConfirm = t.CommandDef(
        t.CommandType.AREQ,
        0x81,
        rsp_schema=(
            t.Param("CommandId", t.uint16_t, "The command id to send with the message"),
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
        ),
    )

    # This callback indicates another device attempted to bind to this device
    ZBAllowBindConfirm = t.CommandDef(
        t.CommandType.AREQ,
        0x82,
        rsp_schema=(
            t.Param("Source", t.NWK, "Source Nwk of the device attempted to bind"),
        ),
    )

    # This callback indicates the data has been sent
    ZBSendConfirm = t.CommandDef(
        t.CommandType.AREQ,
        0x83,
        rsp_schema=(
            t.Param(
                "Handle",
                t.uint8_t,
                "A handle used to Identify the send data request",
            ),
            t.Param("Status", t.Status, "Status is either Success (0) or Failure (1)"),
        ),
    )

    # This callback is called asynchronously by the ZigBee stack to notify the
    # application when data is received from a peer device
    ZBRecieveDataInd = t.CommandDef(
        t.CommandType.AREQ,
        0x87,
        rsp_schema=(
            t.Param("Source", t.NWK, "NWK address of the source device"),
            t.Param("CommandId", t.uint16_t, "The command id associated with the data"),
            t.Param("Data", t.LongBytes, "Data"),
        ),
    )

    # This callback is called by the ZigBee stack when a find device operation
    # completes
    ZBFindDeviceConfirm = t.CommandDef(
        t.CommandType.AREQ,
        0x85,
        rsp_schema=(
            t.Param("SearchType", t.uint8_t, "The type of search that was performed"),
            t.Param("SearchKey", t.uint16_t, "Value that the search was executed on"),
            t.Param("Result", t.EUI64, "The result of the search"),
        ),
    )
