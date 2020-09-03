import copy
import json
import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.types.nvids import NwkNvIds, OsalExNvIds

from zigpy_znp.tools.nvram_read import main as nvram_read
from zigpy_znp.tools.nvram_write import main as nvram_write
from zigpy_znp.tools.nvram_reset import main as nvram_reset

from ..test_api import pytest_mark_asyncio_timeout  # noqa: F401


# We use an existing backup as an NVRAM model
REAL_BACKUP = {
    "osal": {
        "ADDRMGR": "998877665544332211223344",
        "BINDING_TABLE": "ffffffffffffffffffffffffffff",
        "DEVICE_LIST": "a964000001080000ff300020003c0000",
        "TCLK_TABLE": "00000000000000000000000000000000ff000000",
        "APS_KEY_DATA_TABLE": "000000000000000000000000000000000000000000000000",
        "NWK_SEC_MATERIAL_TABLE": "000000000000000000000000",
    },
    "nwk": {
        "HAS_CONFIGURED_ZSTACK3": "55",
        "EXTADDR": "5cacaa1c004b1200",
        "STARTUP_OPTION": "00",
        "START_DELAY": "0a",
        "NIB": (
            "0c0502331433001e0000000105018f00070002051e0000001900000000000000000000"
            "0095860800008010020f0f040001000000010000000099887766554433220100000000"
            "00000000000000000000000000000000000000000000000000000000000000000f0300"
            "01780a0100000089460000"
        ),
        "POLL_RATE_OLD16": "b80b",
        "POLL_RATE": (
            "b80b0000b8010000640000006400000000000000e80300000000000000000000"
            "e859002001000000"
        ),
        "DATA_RETRIES": "02",
        "POLL_FAILURE_RETRIES": "01",
        "STACK_PROFILE": "02",
        "INDIRECT_MSG_TIMEOUT": "07",
        "ROUTE_EXPIRY_TIME": "1e",
        "EXTENDED_PAN_ID": "9988776655443322",
        "BCAST_RETRIES": "02",
        "PASSIVE_ACK_TIMEOUT": "05",
        "BCAST_DELIVERY_TIME": "1e",
        "CONCENTRATOR_ENABLE": "01",
        "CONCENTRATOR_DISCOVERY": "78",
        "CONCENTRATOR_RADIUS_OLD16": "0a",
        "CONCENTRATOR_RC": "01",
        "NWK_MGR_MODE": "01",
        "SRC_RTG_EXPIRY_TIME": "ff",
        "ROUTE_DISCOVERY_TIME": "05",
        "NWK_ACTIVE_KEY_INFO": "0011223344556677889911223344556677",
        "NWK_ALTERN_KEY_INFO": "0011223344556677889911223344556677",
        "ROUTER_OFF_ASSOC_CLEANUP": "00",
        "NWK_LEAVE_REQ_ALLOWED": "01",
        "NWK_CHILD_AGE_ENABLE": "00",
        "GROUP_TABLE": "0000ffffffffffffffffffffffffffffffffffffffff",
        "APS_FRAME_RETRIES": "03",
        "APS_ACK_WAIT_DURATION": "b80b",
        "APS_ACK_WAIT_MULTIPLIER": "02",
        "BINDING_TIME": "803e",
        "APS_USE_EXT_PANID": "0000000000000000",
        "APS_USE_INSECURE_JOIN": "01",
        "COMMISSIONED_NWK_ADDR": "feff",
        "APS_NONMEMBER_RADIUS": "02",
        "APS_LINK_KEY_TABLE": "0000000000000000000000000000000000000000",
        "APS_DUPREJ_TIMEOUT_INC": "e803",
        "APS_DUPREJ_TIMEOUT_COUNT": "0a",
        "APS_DUPREJ_TABLE_SIZE": "0500",
        "NWK_PARENT_INFO": "01",
        "NWK_ENDDEV_TIMEOUT_DEF": "08",
        "END_DEV_TIMEOUT_VALUE": "08",
        "END_DEV_CONFIGURATION": "00",
        "BDBNODEISONANETWORK": "01",
        "PRECFGKEY": "a1a2a3a4a5a6a7a8a1a2a3a4a5a6a7a8",
        "PRECFGKEYS_ENABLE": "01",
        "SECURE_PERMIT_JOIN": "01",
        "APS_LINK_KEY_TYPE": "01",
        "APS_ALLOW_R19_SECURITY": "00",
        "USE_DEFAULT_TCLK": "01",
        "TRUSTCENTER_ADDR": "ffffffffffffffff",
        "USERDESC": "0000000000000000000000000000000000",
        "NWKKEY": "0011223344556677889911223344556677df010006930400",
        "PANID": "9586",
        "CHANLIST": "00801002",
        "LEAVE_CTRL": "00",
        "SCAN_DURATION": "04",
        "LOGICAL_TYPE": "00",
        "NWKMGR_MIN_TX": "14",
        "ZDO_DIRECT_CB": "01",
        "SAPI_ENDPOINT": "e0",
        "TCLK_SEED": "a8a1a2a3a4a5a6a7a8a1a2a3a4a5a6a7",
    },
}


def osal_nv_read(req):
    nvid = NwkNvIds(req.Id).name

    if nvid not in REAL_BACKUP["nwk"]:
        return c.SYS.OSALNVRead.Rsp(Status=t.Status.INVALID_PARAMETER, Value=b"")

    value = bytes.fromhex(REAL_BACKUP["nwk"][nvid])

    return c.SYS.OSALNVRead.Rsp(Status=t.Status.SUCCESS, Value=value[req.Offset :])


def nv_length(req):
    nvid = OsalExNvIds(req.ItemId).name

    if nvid not in REAL_BACKUP["osal"]:
        return c.SYS.NVLength.Rsp(Length=0)

    value = bytes.fromhex(REAL_BACKUP["osal"][nvid])

    return c.SYS.NVLength.Rsp(Length=len(value))


def nv_read(req):
    nvid = OsalExNvIds(req.ItemId).name
    value = bytes.fromhex(REAL_BACKUP["osal"][nvid])

    return c.SYS.NVRead.Rsp(
        Status=t.Status.SUCCESS, Value=value[req.Offset :][: req.Length]
    )


def not_recognized(req):
    return c.RPCError.CommandNotRecognized.Rsp(
        ErrorCode=c.rpc_error.ErrorCode.InvalidCommandId, RequestHeader=req.header
    )


@pytest_mark_asyncio_timeout(seconds=5)
async def test_nvram_read(openable_serial_znp_server, tmp_path, mocker):
    openable_serial_znp_server.reply_to(
        request=c.SYS.OSALNVRead.Req(partial=True), responses=[osal_nv_read],
    )

    openable_serial_znp_server.reply_to(
        request=c.SYS.NVLength.Req(SysId=1, SubId=0, partial=True),
        responses=[nv_length],
    )

    openable_serial_znp_server.reply_to(
        request=c.SYS.NVRead.Req(SysId=1, SubId=0, partial=True), responses=[nv_read],
    )

    backup_file = tmp_path / "backup.json"
    await nvram_read([openable_serial_znp_server._port_path, "-o", str(backup_file)])

    # The backup JSON written to disk should be an exact copy of our fake NVRAM
    assert json.loads(backup_file.read_text()) == REAL_BACKUP


@pytest_mark_asyncio_timeout(seconds=5)
async def test_nvram_read_old_zstack(openable_serial_znp_server, tmp_path, mocker):
    openable_serial_znp_server.reply_to(
        request=c.SYS.OSALNVRead.Req(partial=True), responses=[osal_nv_read],
    )

    # SYS.NVLength doesn't exist
    openable_serial_znp_server.reply_to(
        request=c.SYS.NVLength.Req(partial=True), responses=[not_recognized],
    )

    # Nor does SYS.NVRead
    openable_serial_znp_server.reply_to(
        request=c.SYS.NVRead.Req(SysId=1, SubId=0, partial=True),
        responses=[not_recognized],
    )

    backup_file = tmp_path / "backup.json"
    await nvram_read([openable_serial_znp_server._port_path, "-o", str(backup_file)])

    backup_without_osal = REAL_BACKUP.copy()
    backup_without_osal["osal"] = {}

    # The backup JSON written to disk should be an exact copy of our fake NVRAM,
    # without the OSAL NVIDs
    assert json.loads(backup_file.read_text()) == backup_without_osal


@pytest_mark_asyncio_timeout(seconds=5)
async def test_nvram_write(openable_serial_znp_server, tmp_path, mocker):
    simulated_nvram = {"osal": {}, "nwk": {}}

    def osal_nv_item_init(req):
        nvid = NwkNvIds(req.Id)

        # We have one special value fail
        if nvid == NwkNvIds.SAS_TC_ADDR:
            return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.NV_OPER_FAILED)

        assert len(req.Value) == req.ItemLen

        simulated_nvram["nwk"][nvid.name] = bytearray(req.Value)

        return c.SYS.OSALNVItemInit.Rsp(Status=t.Status.SUCCESS)

    def osal_nv_write(req):
        nvid = NwkNvIds(req.Id)

        # We have one special value fail
        if nvid == NwkNvIds.SAS_TC_ADDR:
            return c.SYS.OSALNVWrite.Rsp(Status=t.Status.NV_OPER_FAILED)

        assert nvid.name in simulated_nvram["nwk"]
        assert len(req.Value) + req.Offset <= len(simulated_nvram["nwk"][nvid.name])

        simulated_nvram["nwk"][nvid.name][
            req.Offset : req.Offset + len(req.Value)
        ] = req.Value

        return c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)

    def nv_write(req):
        nvid = OsalExNvIds(req.ItemId)

        # We have one special value fail
        if nvid == OsalExNvIds.TCLK_IC_TABLE:
            return c.SYS.NVWrite.Rsp(Status=t.Status.NV_OPER_FAILED)

        assert req.Offset == 0

        simulated_nvram["osal"][nvid.name] = req.Value

        return c.SYS.NVWrite.Rsp(Status=t.Status.SUCCESS)

    openable_serial_znp_server.reply_to(
        request=c.SYS.OSALNVItemInit.Req(partial=True), responses=[osal_nv_item_init],
    )

    openable_serial_znp_server.reply_to(
        request=c.SYS.OSALNVWrite.Req(partial=True), responses=[osal_nv_write],
    )

    openable_serial_znp_server.reply_to(
        request=c.SYS.NVWrite.Req(SysId=1, SubId=0, partial=True), responses=[nv_write],
    )

    openable_serial_znp_server.reply_to(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        responses=[
            c.SYS.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=2,
                ProductId=1,
                MajorRel=2,
                MinorRel=7,
                MaintRel=1,
            )
        ],
    )

    # These NVIDs don't exist
    backup_obj = copy.deepcopy(REAL_BACKUP)
    backup_obj["osal"]["TCLK_IC_TABLE"] = "00"
    backup_obj["nwk"]["SAS_TC_ADDR"] = "00"

    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup_obj))

    await nvram_write([openable_serial_znp_server._port_path, "-i", str(backup_file)])

    # Convert every value to its hex representation to match the backup format
    simulated_nvram_hex = {
        cls: {k: v.hex() for k, v in obj.items()}
        for cls, obj in simulated_nvram.items()
    }

    # The backup JSON written to disk should be an exact copy of our original fake NVRAM
    assert simulated_nvram_hex == REAL_BACKUP


@pytest_mark_asyncio_timeout(seconds=5)
@pytest.mark.parametrize(
    "delete_rsp",
    [
        c.SYS.OSALNVDelete.Rsp(Status=t.Status.SUCCESS),
        c.SYS.OSALNVDelete.Rsp(Status=t.Status.NV_ITEM_UNINIT),
    ],
)
async def test_nvram_reset(openable_serial_znp_server, delete_rsp):
    did_write_reset = openable_serial_znp_server.reply_once_to(
        request=c.SYS.OSALNVWrite.Req(
            Id=NwkNvIds.STARTUP_OPTION,
            Offset=0,
            Value=(
                t.StartupOptions.ClearConfig | t.StartupOptions.ClearState
            ).serialize(),
        ),
        responses=[c.SYS.OSALNVWrite.Rsp(Status=t.Status.SUCCESS)],
    )

    did_delete_zstack1_configured = openable_serial_znp_server.reply_once_to(
        request=c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK1, ItemLen=1),
        responses=[delete_rsp],
    )

    did_delete_zstack3_configured = openable_serial_znp_server.reply_once_to(
        request=c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1),
        responses=[delete_rsp],
    )

    did_reset = openable_serial_znp_server.reply_once_to(
        request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
        responses=[
            c.SYS.ResetInd.Callback(
                Reason=t.ResetReason.PowerUp,
                TransportRev=2,
                ProductId=2,
                MajorRel=2,
                MinorRel=7,
                MaintRel=2,
            )
        ],
    )

    await nvram_reset([openable_serial_znp_server._port_path])

    await did_write_reset
    await did_delete_zstack1_configured
    await did_delete_zstack3_configured
    await did_reset
