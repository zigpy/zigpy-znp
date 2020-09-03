import asyncio

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.tools.energy_scan import channels_from_channel_mask, main as energy_scan

from ..test_api import pytest_mark_asyncio_timeout  # noqa: F401
from ..test_application import make_application, znp_server  # noqa: F401


def test_channels_from_channel_mask():
    def channel_list(channels):
        return list(channels_from_channel_mask(channels))

    assert channel_list(t.Channels.ALL_CHANNELS) == list(range(11, 26 + 1))
    assert channel_list(t.Channels.NO_CHANNELS) == []
    assert channel_list(t.Channels.CHANNEL_11 | t.Channels.CHANNEL_20) == [11, 20]
    assert channel_list(t.Channels.CHANNEL_15) == [15]


@pytest_mark_asyncio_timeout(seconds=5)
async def test_energy_scan(openable_serial_znp_server, capsys, mocker):  # noqa: F811
    app, openable_serial_znp_server = make_application(openable_serial_znp_server)

    def fake_scanner(request):
        async def response(request):
            openable_serial_znp_server.send(
                c.ZDO.MgmtNWKUpdateReq.Rsp(Status=t.Status.SUCCESS)
            )

            delay = 2 ** request.ScanDuration
            num_channels = len(list(channels_from_channel_mask(request.Channels)))

            for i in range(request.ScanCount):
                await asyncio.sleep(delay / 100)

                openable_serial_znp_server.send(
                    c.ZDO.MgmtNWKUpdateNotify.Callback(
                        Src=0x0000,
                        Status=t.ZDOStatus.SUCCESS,
                        ScannedChannels=request.Channels,
                        TotalTransmissions=998,
                        TransmissionFailures=2,
                        EnergyValues=list(range(num_channels)),
                    )
                )

        asyncio.create_task(response(request))

    openable_serial_znp_server.callback_for_response(
        c.ZDO.MgmtNWKUpdateReq.Req(
            Dst=0x0000, DstAddrMode=t.AddrMode.NWK, NwkManagerAddr=0x0000, partial=True,
        ),
        fake_scanner,
    )

    await energy_scan(["-n", "1", openable_serial_znp_server._port_path, "-v", "-v"])

    captured = capsys.readouterr()

    for i in range(11, 26 + 1):
        assert str(i) in captured.out
