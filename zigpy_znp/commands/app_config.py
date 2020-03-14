"""commands to configure parameters of the device, trust center and BDB subsystem."""

from zigpy_znp.commands.types import (
    STATUS_SCHEMA,
    CommandDef,
    CommandType,
    CommandsBase,
    Subsystem,
)
import zigpy_znp.types as t


class APPConfigCommands(CommandsBase, subsystem=Subsystem.APPConfig):
    # sets the network frame counter to the value specified in the Frame Counter Value.
    # For projects with multiple instances of frame counter, the message sets the
    # frame counter of the current network
    SetNwkFrameCounter = CommandDef(
        CommandType.SREQ,
        0xFF,
        req_schema=t.Schema(
            (t.Param("FrameCounterValue", t.uint32_t, "network frame counter"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Set the default value used by parent device to expire legacy child devices
    SetDefaultRemoteEndDeviceTimeout = CommandDef(
        CommandType.SREQ,
        0x01,
        req_schema=t.Schema(
            (t.Param("TimeoutIndex", t.uint8_t, "0x00 -- 10s otherwise 2^^N minutes"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Sets in ZED the timeout value to be send to parent device for child expiring
    SetEndDeviceTimeout = CommandDef(
        CommandType.SREQ,
        0x02,
        req_schema=t.Schema(
            (t.Param("TimeoutIndex", t.uint8_t, "0x00 -- 10s otherwise 2^^N minutes"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Set the AllowRejoin TC policy
    SetAllowRejoinTCPolicy = CommandDef(
        CommandType.SREQ,
        0x03,
        req_schema=t.Schema(
            (
                t.Param(
                    "AllowRejoin",
                    t.uint8_t,
                    "whether or not the Trust center allows rejoins",
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Set the commissioning methods to be executed. Initialization of BDB is executed
    # with this call, regardless of its parameters
    BDBStartCommissioning = CommandDef(
        CommandType.SREQ,
        0x05,
        req_schema=t.Schema(
            (t.Param("Mode", t.BDBCommissioningMode, "Commissioning mode"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Set BDB primary or secondary channel masks
    BDBSetChannel = CommandDef(
        CommandType.SREQ,
        0x08,
        req_schema=t.Schema(
            (
                t.Param("IsPrimary", t.Bool, "True -- is primary channel"),
                t.Param("Channel", t.Channels, "Channel set mask"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Add a preconfigured key (plain key or IC) to Trust Center device
    BDBAddInstallCode = CommandDef(
        CommandType.SREQ,
        0x04,
        req_schema=t.Schema(
            (
                t.Param(
                    "InstallCodeFormat",
                    t.uint8_t,
                    (
                        "0x01 -- Install code + CRC"
                        "0x02 -- Key derived from install code"
                    ),
                ),
                t.Param("IEEE", t.EUI64, "IEEE address of the joining device"),
                t.Param(
                    "InstallCode", t.Bytes, "16 bytes for derived key, 18 for IC + CRC"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Set the policy flag on Trust Center device to mandate or not the TCLK
    # exchange procedure
    BDBSetTcRequireKeyExchange = CommandDef(
        CommandType.SREQ,
        0x09,
        req_schema=t.Schema(
            (
                t.Param(
                    "BdbTrustCenterRequireKeyExchange", t.Bool, "Require key exchange"
                ),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Sets the policy to mandate or not the usage of an Install Code upon joining
    BDBSetJoinUsesInstallCodeKey = CommandDef(
        CommandType.SREQ,
        0x06,
        req_schema=t.Schema(
            (t.Param("BdbJoinUsesInstallCodeKey", t.Bool, "Use install code"),)
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # On joining devices, set the default key or an install code to attempt
    # to join the network
    BDBSetActiveDefaultCentralizedKey = CommandDef(
        CommandType.SREQ,
        0x07,
        req_schema=t.Schema(
            (
                t.Param(
                    "UseGlobal",
                    t.Bool,
                    (
                        "True -- device uses default global key, "
                        "False -- device uses install code"
                    ),
                ),
                t.Param("InstallCode", t.Bytes, "Install code + CRC"),
            )
        ),
        rsp_schema=STATUS_SCHEMA,
    )

    # Instruct the ZED to try to rejoin its previews network. Use only in ZED devices
    BDBZedAttemptRecoverNWK = CommandDef(
        CommandType.SREQ, 0x0A, rsp_schema=STATUS_SCHEMA
    )

    # MT_APP_CONFIG Callbacks
    # Callback to receive notifications from BDB process
    BDBCommissioningNotification = CommandDef(
        CommandType.AREQ,
        0x80,
        req_schema=t.Schema(
            (
                t.Param(
                    "Status", t.uint8_t, "Status of the commissioning mode notified"
                ),
                t.Param(
                    "Mode", t.uint8_t, "Commissioning mode to which status is related"
                ),
                t.Param(
                    "RemainingMode",
                    t.uint8_t,
                    (
                        "Bitmask of the remaining commissioning modes after "
                        "this notification"
                    ),
                ),
            )
        ),
    )
