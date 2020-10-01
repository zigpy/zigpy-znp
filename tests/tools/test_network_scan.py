import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.exceptions import InvalidCommandResponse
from zigpy_znp.types.nvids import NwkNvIds
from zigpy_znp.tools.network_scan import main as network_scan

from ..conftest import FormedLaunchpadCC26X2R1

pytestmark = [pytest.mark.timeout(1), pytest.mark.asyncio]


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_network_scan(device, make_znp_server, capsys):
    znp_server = make_znp_server(server_cls=device)

    original_channels = t.Channels.from_channel_list([15, 20, 25]).serialize()
    assert znp_server.nvram["nwk"][NwkNvIds.CHANLIST] == original_channels

    # Scan 1 results
    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    t.Beacon(
                        Src=0x0000,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=39,
                        Depth=0,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                    t.Beacon(
                        Src=0xEC9B,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=66,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    t.Beacon(
                        Src=0x74E2,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=69,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    # Scan 2 results
    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    # First (and only) other network
                    t.Beacon(
                        Src=0x0000,
                        PanId=0x86E6,
                        Channel=11,
                        PermitJoining=1,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=0,
                        Depth=0,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("d9:6d:d1:3b:39:46:6c:36"),
                    ),
                    t.Beacon(
                        Src=0x0000,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=45,
                        Depth=0,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    t.Beacon(
                        Src=0x9DC1,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=57,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    # Scan 3 results
    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    t.Beacon(
                        Src=0x74E2,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=63,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                    t.Beacon(
                        Src=0xEC9B,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=66,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.BeaconNotifyInd.Callback(
                Beacons=[
                    t.Beacon(
                        Src=0xF8B4,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=90,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                    t.Beacon(
                        Src=0x43FD,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=111,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                    t.Beacon(
                        Src=0x4444,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=126,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                    t.Beacon(
                        Src=0x5014,
                        PanId=0x7ABE,
                        Channel=25,
                        PermitJoining=0,
                        RouterCapacity=1,
                        DeviceCapacity=1,
                        ProtocolVersion=2,
                        StackProfile=2,
                        LQI=78,
                        Depth=1,
                        UpdateId=0,
                        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
                    ),
                ]
            ),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    # Scan 4 results
    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    await network_scan(["-n", "4", znp_server._port_path, "-v", "-v"])

    # The channels in NVRAM were restored
    assert znp_server.nvram["nwk"][NwkNvIds.CHANLIST] == original_channels

    captured = capsys.readouterr()

    # Nine unique beacons were detected
    assert captured.out.count(", from: ") == 9
    assert captured.out.count("0x7ABE, from: ") == 8
    assert captured.out.count("0x86E6, from: ") == 1


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_network_scan_failure(device, make_znp_server):
    znp_server = make_znp_server(server_cls=device)

    original_channels = t.Channels.from_channel_list([15, 20, 25]).serialize()
    assert znp_server.nvram["nwk"][NwkNvIds.CHANLIST] == original_channels

    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.FAILURE)],
    )

    with pytest.raises(InvalidCommandResponse):
        await network_scan([znp_server._port_path, "-v", "-v"])

    # The channels in NVRAM were restored even when we had a failure
    assert znp_server.nvram["nwk"][NwkNvIds.CHANLIST] == original_channels


@pytest.mark.parametrize("device", [FormedLaunchpadCC26X2R1])
async def test_network_scan_duplicates(device, make_znp_server, capsys):
    znp_server = make_znp_server(server_cls=device)

    beacon = t.Beacon(
        Src=0x0000,
        PanId=0x7ABE,
        Channel=25,
        PermitJoining=0,
        RouterCapacity=1,
        DeviceCapacity=1,
        ProtocolVersion=2,
        StackProfile=2,
        LQI=39,
        Depth=0,
        UpdateId=0,
        ExtendedPanId=t.EUI64.convert("92:6b:f8:1e:df:1b:e8:1c"),
    )

    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.BeaconNotifyInd.Callback(Beacons=[beacon, beacon]),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    znp_server.reply_once_to(
        c.ZDO.NetworkDiscoveryReq.Req(Channels=t.Channels.ALL_CHANNELS, ScanDuration=2),
        responses=[
            c.ZDO.NetworkDiscoveryReq.Rsp(Status=t.Status.SUCCESS),
            c.ZDO.BeaconNotifyInd.Callback(Beacons=[beacon, beacon]),
            c.ZDO.NwkDiscoveryCnf.Callback(Status=t.ZDOStatus.SUCCESS),
        ],
    )

    await network_scan([znp_server._port_path, "-v", "-v", "-n", "2", "-a"])

    captured = capsys.readouterr()

    # No duplicates were filtered
    assert captured.out.count(", from: ") == 4
