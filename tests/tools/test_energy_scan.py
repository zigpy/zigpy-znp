import asyncio

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.tools.energy_scan import main as energy_scan

from ..conftest import FORMED_DEVICES


@pytest.mark.asyncio
@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_energy_scan(device, make_znp_server, capsys):
    znp_server = make_znp_server(server_cls=device)

    def fake_scanner(request):
        async def response(request):
            znp_server.send(c.ZDO.MgmtNWKUpdateReq.Rsp(Status=t.Status.SUCCESS))

            delay = 2 ** request.ScanDuration
            num_channels = len(list(request.Channels))

            for i in range(request.ScanCount):
                await asyncio.sleep(delay / 100)

                znp_server.send(
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

    znp_server.callback_for_response(
        c.ZDO.MgmtNWKUpdateReq.Req(
            Dst=0x0000,
            DstAddrMode=t.AddrMode.NWK,
            NwkManagerAddr=0x0000,
            partial=True,
        ),
        fake_scanner,
    )

    await energy_scan(["-n", "1", znp_server._port_path, "-v", "-v"])

    captured = capsys.readouterr()

    for i in range(11, 26 + 1):
        assert str(i) in captured.out
