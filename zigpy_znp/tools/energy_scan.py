import sys
import asyncio
import logging
import itertools
from collections import deque, defaultdict

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.tools.common import setup_parser
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


def channels_from_channel_mask(channels: t.Channels):
    for channel in range(11, 26 + 1):
        if channels & t.Channels.from_channel_list([channel]):
            yield channel


async def perform_energy_scan(radio_path, num_scans=None):
    LOGGER.info("Starting up zigpy-znp")

    app = await ControllerApplication.new(
        ControllerApplication.SCHEMA({"device": {"path": radio_path}}), auto_form=True
    )

    LOGGER.info("Running scan...")

    # We compute an average over the last 5 scans
    channel_energies = defaultdict(lambda: deque([], maxlen=5))

    for i in itertools.count(start=1):
        if num_scans is not None and i > num_scans:
            break

        rsp = await app._znp.request_callback_rsp(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=t.Channels.ALL_CHANNELS,
                ScanDuration=0x02,  # exponent
                ScanCount=1,
                NwkManagerAddr=0x0000,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtNWKUpdateNotify.Callback(partial=True, Src=0x0000),
        )

        for channel, energy in zip(
            channels_from_channel_mask(rsp.ScannedChannels), rsp.EnergyValues
        ):
            energies = channel_energies[channel]
            energies.append(energy)

        total = 0xFF * len(energies)

        print(f"Channel energy (mean of {len(energies)} / {energies.maxlen}):")
        print("------------------------------------------------")
        print(" + Lower energy is better")
        print(" + Active Zigbee networks on a channel may still cause congestion")
        print(" + TX on 26 in North America may be with lower power due to regulations")
        print(" + Zigbee channels 15, 20, 25 fall between WiFi channels 1, 6, 11")
        print(" + Some Zigbee devices only join networks on channels 15, 20, and 25")
        print("------------------------------------------------")

        for channel, energies in channel_energies.items():
            count = sum(energies)
            asterisk = "*" if channel == 26 else " "

            print(
                f" - {channel:>02}{asterisk}  {count / total:>7.2%}  "
                + "#" * int(100 * count / total)
            )

        print()

    await app.shutdown()


async def main(argv):
    parser = setup_parser("Perform an energy scan")
    parser.add_argument(
        "-n",
        "--num-scans",
        dest="num_scans",
        type=int,
        default=None,
        help="Number of scans to perform before exiting",
    )

    args = parser.parse_args(argv)

    await perform_energy_scan(args.serial, num_scans=args.num_scans)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
