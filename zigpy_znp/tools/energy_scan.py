import sys
import asyncio
import logging
import itertools
from collections import deque, defaultdict

import zigpy.zdo.types as zdo_t
from zigpy.exceptions import NetworkNotFormed

import zigpy_znp.types as t
from zigpy_znp.tools.common import setup_parser
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


async def perform_energy_scan(radio_path, num_scans=None):
    LOGGER.info("Starting up zigpy-znp")

    config = ControllerApplication.SCHEMA({"device": {"path": radio_path}})
    app = ControllerApplication(config)
    await app.connect()

    try:
        await app.start_network(read_only=True)
    except NetworkNotFormed as e:
        LOGGER.error("Could not start application: %s", e)
        LOGGER.error("Form a network with `python -m zigpy_znp.tools.form_network`")
        return

    LOGGER.info("Running scan...")

    # We compute an average over the last 5 scans
    channel_energies = defaultdict(lambda: deque([], maxlen=5))

    for i in itertools.count(start=1):
        if num_scans is not None and i > num_scans:
            break

        rsp = await app.get_device(nwk=0x0000).zdo.Mgmt_NWK_Update_req(
            zdo_t.NwkUpdate(
                ScanChannels=t.Channels.ALL_CHANNELS,
                ScanDuration=0x02,
                ScanCount=1,
            )
        )

        _, scanned_channels, _, _, energy_values = rsp

        for channel, energy in zip(scanned_channels, energy_values):
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
