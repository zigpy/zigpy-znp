import asyncio

import pytest
import zigpy.zdo.types as zdo_t

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.tools.energy_scan import main as energy_scan

from ..conftest import (
    EMPTY_DEVICES,
    FORMED_DEVICES,
    serialize_zdo_command,
    deserialize_zdo_command,
)


@pytest.mark.parametrize("device", EMPTY_DEVICES)
async def test_energy_scan_unformed(device, make_znp_server, caplog):
    znp_server = make_znp_server(server_cls=device)

    await energy_scan(["-n", "1", znp_server._port_path, "-v", "-v"])
    assert "Form a network" in caplog.text


@pytest.mark.parametrize("device", FORMED_DEVICES)
async def test_energy_scan_formed(device, make_znp_server, capsys):
    znp_server = make_znp_server(server_cls=device)

    def fake_scanner(request):
        async def response(request):
            znp_server.send(c.AF.DataRequestExt.Rsp(Status=t.Status.SUCCESS))

            params = deserialize_zdo_command(request.ClusterId, request.Data[1:])
            channels = params["NwkUpdate"].ScanChannels
            num_channels = len(list(channels))

            await asyncio.sleep(0.1)

            znp_server.send(
                c.ZDO.MsgCbIncoming.Callback(
                    Src=0x0000,
                    IsBroadcast=t.Bool.false,
                    ClusterId=zdo_t.ZDOCmd.Mgmt_NWK_Update_rsp,
                    SecurityUse=0,
                    TSN=request.TSN,
                    MacDst=0x0000,
                    Data=serialize_zdo_command(
                        command_id=zdo_t.ZDOCmd.Mgmt_NWK_Update_rsp,
                        Status=t.ZDOStatus.SUCCESS,
                        ScannedChannels=channels,
                        TotalTransmissions=998,
                        TransmissionFailures=2,
                        EnergyValues=list(range(11, 26 + 1))[:num_channels],
                    ),
                )
            )

            znp_server.send(
                c.ZDO.MgmtNWKUpdateNotify.Callback(
                    Src=0x0000,
                    Status=t.ZDOStatus.SUCCESS,
                    ScannedChannels=channels,
                    TotalTransmissions=998,
                    TransmissionFailures=2,
                    EnergyValues=list(range(11, 26 + 1))[:num_channels],
                )
            )

        asyncio.create_task(response(request))

    znp_server.callback_for_response(
        c.AF.DataRequestExt.Req(
            DstAddrModeAddress=t.AddrModeAddress(mode=t.AddrMode.NWK, address=0x0000),
            DstEndpoint=0,
            SrcEndpoint=0,
            ClusterId=zdo_t.ZDOCmd.Mgmt_NWK_Update_req,
            partial=True,
        ),
        fake_scanner,
    )

    await energy_scan(["-n", "1", znp_server._port_path, "-v", "-v"])

    captured = capsys.readouterr()

    for i in range(11, 26 + 1):
        assert str(i) in captured.out
