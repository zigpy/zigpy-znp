import sys
import time
import asyncio
import logging
import itertools

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA
from zigpy_znp.types.nvids import NwkNvIds
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
                Channels=channels, ScanDuration=duration_exp,
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
    znp: ZNP, channels: t.Channels, num_scans: int, duration_exp: int
) -> None:
    previous_channels = await znp.nvram_read(NwkNvIds.CHANLIST)

    await znp.nvram_write(NwkNvIds.CHANLIST, t.Channels.ALL_CHANNELS)

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
                key = beacon.replace(Depth=0, LQI=0).serialize()

                if key in seen_beacons:
                    continue

                seen_beacons.add(key)

                print(
                    f"{time.time():0.2f} [{beacon.ExtendedPanId}, {beacon.PanId},"
                    f" from: {beacon.Src}]: Channel={beacon.Channel:2>}"
                    f" PermitJoining={beacon.PermitJoining}"
                    f" RouterCapacity={beacon.RouterCapacity}"
                    f" DeviceCapacity={beacon.DeviceCapacity}"
                    f" ProtocolVersion={beacon.ProtocolVersion}"
                    f" StackProfile={beacon.StackProfile}"
                    f" Depth={beacon.Depth:>3}"
                    f" UpdateId={beacon.UpdateId:>2}"
                )
    finally:
        await znp.nvram_write(NwkNvIds.CHANLIST, previous_channels)


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

    args = parser.parse_args(argv)

    znp = ZNP(CONFIG_SCHEMA({"device": {"path": args.serial}}))

    await znp.connect()
    await network_scan(znp, args.channels, args.num_scans, args.duration_exp)

    znp.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
