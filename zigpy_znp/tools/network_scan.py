import sys
import time
import asyncio
import logging
import itertools

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import OsalNvIds
from zigpy_znp.tools.common import setup_parser

LOGGER = logging.getLogger(__name__)


async def scan_once(znp: ZNP, channels: t.Channels, duration_exp: int):
    async with znp.capture_responses(
        [
            c.ZDO.BeaconNotifyInd.Callback(partial=True),
            c.ZDO.NwkDiscoveryCnf.Callback(partial=True),
        ]
    ) as updates:
        await znp.request(
            c.ZDO.NetworkDiscoveryReq.Req(
                Channels=channels,
                ScanDuration=duration_exp,
            ),
            RspStatus=t.Status.SUCCESS,
        )

        while True:
            update = await updates.get()

            if isinstance(update, c.ZDO.NwkDiscoveryCnf.Callback):
                break

            for beacon in update.Beacons:
                yield beacon


async def network_scan(
    znp: ZNP, channels: t.Channels, num_scans: int, duration_exp: int, duplicates: bool
) -> None:
    # Network scanning only works if our device is not joined to a network.
    # If we don't start Z-Stack 3 it will always work but Z-Stack 1 keeps the device
    # state in the NIB, which we have to temporarily delete in order for the scan to be
    # possible.
    if znp.version == 1.2:
        previous_nib = await znp.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)
        await znp.nvram.osal_delete(OsalNvIds.NIB)
    else:
        previous_nib = None

    previous_channels = await znp.nvram.osal_read(
        OsalNvIds.CHANLIST, item_type=t.Channels
    )
    await znp.nvram.osal_write(OsalNvIds.CHANLIST, t.Channels.ALL_CHANNELS)

    try:
        await znp.request_callback_rsp(
            request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
            callback=c.SYS.ResetInd.Callback(partial=True),
        )

        seen_beacons = set()

        for i in itertools.count(start=1):
            if num_scans is not None and i > num_scans:
                break

            async for beacon in scan_once(znp, channels, duration_exp):
                if not duplicates:
                    key = beacon.replace(Depth=0, LQI=0).serialize()

                    if key in seen_beacons:
                        continue

                    seen_beacons.add(key)

                print(
                    f"{time.time():0.2f}"
                    f" [EPID: {beacon.ExtendedPanId}, PID: {beacon.PanId},"
                    f" from: {beacon.Src}]: Channel={beacon.Channel:2>}"
                    f" PermitJoins={beacon.PermitJoining}"
                    f" RtrCapacity={beacon.RouterCapacity}"
                    f" DevCapacity={beacon.DeviceCapacity}"
                    f" ProtoVer={beacon.ProtocolVersion}"
                    f" StackProf={beacon.StackProfile}"
                    f" Depth={beacon.Depth:>3}"
                    f" UpdateId={beacon.UpdateId:>2}"
                    f" LQI={beacon.LQI:>3}"
                )
    finally:
        if previous_nib is not None:
            await znp.nvram.osal_write(OsalNvIds.NIB, previous_nib, create=True)

        await znp.nvram.osal_write(OsalNvIds.CHANLIST, previous_channels)
        await znp.disconnect()


async def main(argv):
    parser = setup_parser("Actively scan for Zigbee networks")

    parser.add_argument(
        "-c",
        "--channels",
        dest="channels",
        type=lambda s: t.Channels.from_channel_list(map(int, s.split(","))),
        default=t.Channels.ALL_CHANNELS,
        help="Channels on which to scan for networks",
    )

    parser.add_argument(
        "-n",
        "--num_scans",
        dest="num_scans",
        type=int,
        default=None,
        help="Number of scans to perform. Default is to scan forever.",
    )

    parser.add_argument(
        "-d",
        "--duration-exp",
        dest="duration_exp",
        type=int,
        default=2,
        help="Scan duration exponent",
    )

    parser.add_argument(
        "-a",
        "--allow-duplicates",
        dest="allow_duplicates",
        action="store_true",
        default=False,
        help="Allow duplicate beacons that differ only by LQI and depth",
    )

    args = parser.parse_args(argv)

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))

    await znp.connect()
    await network_scan(
        znp=znp,
        channels=args.channels,
        num_scans=args.num_scans,
        duration_exp=args.duration_exp,
        duplicates=args.allow_duplicates,
    )

    await znp.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
