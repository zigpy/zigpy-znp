import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.tools.flash_backup import main as flash_backup

from test_api import pytest_mark_asyncio_timeout  # noqa: F401
from test_application import znp_server  # noqa: F401
from test_tools_nvram import openable_serial_znp_server  # noqa: F401


# Just random bytes
FAKE_FLASH = bytes.fromhex(
    """
    a66ea64b2299ef91102c692c8739433776ac1f7967b2d7be3b532db5255dee88f49cad134ef4155375d2
    67acecbe64637bd1df47ce1cb8b776caad7a7cd2b39892b69fbf2420176e598f689df05a3554400efb99
    60dcedfb3416fe72b1570b6eb4aa877213afb92c7a6fc8b755e7457072a8c4d4ac9ec727b7748b267fda
    241334ab9195b4eb52cb50b396859c355dfad136e1c56b18f6599e08a7464524587a44ea0caaeb2b0a79
    44ff74576db0c16b133f862de8ee8b6b37181a897416b40c589a645c62bbc6b2b4e993a6ee39ca1141bb
    7baeb7bb85476c7b905fa8f3f2148fe1162a218fb575eb3ed9849bc63212f7332a27f83c75e6590a25ad
    8ad3d13b212da0142bc257851afcc7c87c80c23d9f741f7159ccc89fed58ff2369523af224369df39224
    a4154dc2932958d3289d387356af931aa6e02d8216bffc3972674cf060de50c10e0705b2f80d7b54c763
    0999d2f28f8e3b1917d89e960a1893ebdaa1695c5b2f1fc36efb144b326d4cb8119803ea327f2848b45a
    a6e3e1ca93459eb848a8333826b12d87949be6cf652b1265a7c74e2b750303ee25f6296ed687393cb1a1
    64648ae92eb2c426ea3f35770f6d64fefcd87fc9835ab39134be9a5d325cc2839a47515f15ce5b2072fe
    808a5e897a273f883751d029bec9fe89797fd2940603537770c745c17e817e495e4d8741e744b652254b
    2b776c1d313ca30a
"""
)


@pytest_mark_asyncio_timeout(seconds=5)
async def test_flash_backup(openable_serial_znp_server, tmp_path):  # noqa: F811
    openable_serial_znp_server.reply_to(
        request=c.UBL.HandshakeReq.Req(partial=True),
        responses=[
            c.UBL.HandshakeRsp.Callback(
                Status=c.ubl.BootloaderStatus.SUCCESS,
                BootloaderRevision=0,
                DeviceType=c.ubl.BootloaderDeviceType.CC2530,
                BufferSize=64,
                PageSize=2048,
                BootloaderCodeRevision=0,
            )
        ],
    )

    def read_flash(req):
        offset = req.FlashWordAddr * 4
        data = FAKE_FLASH[offset : offset + 64]

        # We should not read partial blocks
        assert len(data) in (0, 64)

        if not data:
            return c.UBL.ReadRsp.Callback(Status=c.ubl.BootloaderStatus.FAILURE)

        return c.UBL.ReadRsp.Callback(
            Status=c.ubl.BootloaderStatus.SUCCESS,
            FlashWordAddr=req.FlashWordAddr,
            Data=t.TrailingBytes(data),
        )

    openable_serial_znp_server.reply_to(
        request=c.UBL.ReadReq.Req(partial=True), responses=[read_flash]
    )

    backup_file = tmp_path / "backup.bin"
    await flash_backup([openable_serial_znp_server._port_path, "-o", str(backup_file)])

    assert backup_file.read_bytes() == FAKE_FLASH
