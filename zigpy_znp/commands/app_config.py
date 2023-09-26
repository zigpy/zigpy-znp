"""commands to configure parameters of the device, trust center and BDB subsystem."""

import zigpy_znp.types as t


class TimeoutIndex(t.enum8):
    Seconds_10 = 0x00

    Minutes_2 = 0x01
    Minutes_4 = 0x02
    Minutes_8 = 0x03
    Minutes_16 = 0x04
    Minutes_32 = 0x05
    Minutes_64 = 0x06
    Minutes_128 = 0x07
    Minutes_256 = 0x08
    Minutes_512 = 0x09
    Minutes_1024 = 0x0A
    Minutes_2048 = 0x0B
    Minutes_4096 = 0x0C
    Minutes_8192 = 0x0D
    Minutes_16384 = 0x0E


class CentralizedLinkKeyMode(t.enum8):
    UseDefault = 0x00
    UseProvidedInstallCode = 0x01
    UseProvidedInstallCodeAndFallbackToDefault = 0x02
    UseProvidedAPSLinkKey = 0x03
    UseProvidedAPSLinkKeyAndFallbackToDefault = 0x04


class BDBCommissioningStatus(t.enum8):
    Success = 0x00
    InProgress = 0x01
    NoNetwork = 0x02
    TLTargetFailure = 0x03
    TLNotAaCapable = 0x04
    TLNoScanResponse = 0x05
    TLNotPermitted = 0x06
    TCLKExFailure = 0x07
    FormationFailure = 0x08
    FBTargetInProgress = 0x09
    FBInitiatorInProgress = 0x0A
    FBNoIdentifyQueryResponse = 0x0B
    FBBindingTableFull = 0x0C
    NetworkRestored = 0x0D
    Failure = 0x0E


class BDBCommissioningMode(t.bitmap8):
    NONE = 0

    InitiatorTouchLink = 1 << 0
    NwkSteering = 1 << 1
    NwkFormation = 1 << 2
    FindingBinding = 1 << 3
    Touchlink = 1 << 4
    ParentLost = 1 << 5


class InstallCodeFormat(t.enum8):
    InstallCodeAndCRC = 0x01
    KeyDerivedFromInstallCode = 0x02


class AppConfig(t.CommandsBase, subsystem=t.Subsystem.APPConfig):
    # sets the network frame counter to the value specified in the Frame Counter Value.
    # For projects with multiple instances of frame counter, the message sets the
    # frame counter of the current network
    SetNwkFrameCounter = t.CommandDef(
        t.CommandType.SREQ,
        0xFF,
        req_schema=(t.Param("FrameCounterValue", t.uint32_t, "network frame counter"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Set the default value used by parent device to expire legacy child devices
    SetDefaultRemoteEndDeviceTimeout = t.CommandDef(
        t.CommandType.SREQ,
        0x01,
        req_schema=(
            t.Param("TimeoutIndex", TimeoutIndex, "0x00 -- 10s otherwise 2^N minutes"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Sets in ZED the timeout value to be send to parent device for child expiring
    SetEndDeviceTimeout = t.CommandDef(
        t.CommandType.SREQ,
        0x02,
        req_schema=(
            t.Param("TimeoutIndex", TimeoutIndex, "0x00 -- 10s otherwise 2^N minutes"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Set the AllowRejoin TC policy
    SetAllowRejoinTCPolicy = t.CommandDef(
        t.CommandType.SREQ,
        0x03,
        req_schema=(
            t.Param(
                "AllowRejoin",
                t.Bool,
                "whether or not the Trust center allows rejoins with well-known key",
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Set the commissioning methods to be executed. Initialization of BDB is executed
    # with this call, regardless of its parameters
    BDBStartCommissioning = t.CommandDef(
        t.CommandType.SREQ,
        0x05,
        req_schema=(t.Param("Mode", BDBCommissioningMode, "Commissioning mode"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Set BDB primary or secondary channel masks
    BDBSetChannel = t.CommandDef(
        t.CommandType.SREQ,
        0x08,
        req_schema=(
            t.Param("IsPrimary", t.Bool, "True -- is primary channel"),
            t.Param("Channel", t.Channels, "Channel set mask"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Add a preconfigured key (plain key or IC) to Trust Center device
    BDBAddInstallCode = t.CommandDef(
        t.CommandType.SREQ,
        0x04,
        req_schema=(
            t.Param(
                "InstallCodeFormat",
                InstallCodeFormat,
                ("0x01 -- Install code + CRC  0x02 -- Key derived from install code"),
            ),
            t.Param("IEEE", t.EUI64, "IEEE address of the joining device"),
            t.Param(
                "InstallCode", t.Bytes, "16 bytes for derived key, 18 for IC + CRC"
            ),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Set the policy flag on Trust Center device to mandate or not the TCLK
    # exchange procedure
    BDBSetTcRequireKeyExchange = t.CommandDef(
        t.CommandType.SREQ,
        0x09,
        req_schema=(
            t.Param("BdbTrustCenterRequireKeyExchange", t.Bool, "Require key exchange"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Sets the policy to mandate or not the usage of an Install Code upon joining
    BDBSetJoinUsesInstallCodeKey = t.CommandDef(
        t.CommandType.SREQ,
        0x06,
        req_schema=(t.Param("BdbJoinUsesInstallCodeKey", t.Bool, "Use install code"),),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # On joining devices, set the default key or an install code to attempt
    # to join the network
    BDBSetActiveDefaultCentralizedKey = t.CommandDef(
        t.CommandType.SREQ,
        0x07,
        req_schema=(
            t.Param(
                "CentralizedLinkKeyModes",
                CentralizedLinkKeyMode,
                (
                    "which key will be used when performing association "
                    "to a centralized network"
                ),
            ),
            t.Param("InstallCode", t.Bytes, "key in any of its formats"),
        ),
        rsp_schema=t.STATUS_SCHEMA,
    )

    # Instruct the ZED to try to rejoin its previews network. Use only in ZED devices
    BDBZedAttemptRecoverNWK = t.CommandDef(
        t.CommandType.SREQ, 0x0A, req_schema=(), rsp_schema=t.STATUS_SCHEMA
    )

    # MT_APP_CONFIG Callbacks
    # Callback to receive notifications from BDB process
    BDBCommissioningNotification = t.CommandDef(
        t.CommandType.AREQ,
        0x80,
        rsp_schema=(
            t.Param(
                "Status",
                BDBCommissioningStatus,
                "Status of the commissioning mode notified",
            ),
            t.Param(
                "Mode",
                BDBCommissioningMode,
                "Commissioning mode to which status is related",
            ),
            t.Param(
                "RemainingModes",
                BDBCommissioningMode,
                (
                    "Bitmask of the remaining commissioning modes after "
                    "this notification"
                ),
            ),
        ),
    )
