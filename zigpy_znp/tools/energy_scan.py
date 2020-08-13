import sys
import asyncio
import logging
import argparse

from collections import defaultdict, deque

import zigpy_znp.types as t
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.config import CONFIG_SCHEMA

logging.getLogger("zigpy_znp").setLevel(logging.INFO)

LOGGER = logging.getLogger(__name__)


def channels_from_channel_mask(channels: t.Channels):
    for channel in range(11, 26 + 1):
        if channels & t.Channels.from_channel_list([channel]):
            yield channel


async def perform_energy_scan(radio_path):
    znp = ZNP(CONFIG_SCHEMA({"device": {"path": radio_path}}))

    await znp.connect()

    channels = defaultdict(lambda: deque([], maxlen=5))

    while True:
        rsp = await znp.request_callback_rsp(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=t.Channels.ALL_CHANNELS,
                ScanDuration=0x02,
                ScanCount=1,
                NwkManagerAddr=0x0000,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtNWKUpdateNotify.Callback(partial=True, Src=0x0000,),
        )

        for channel, energy in zip(
            channels_from_channel_mask(rsp.ScannedChannels), rsp.EnergyValues
        ):
            channels[channel].append(energy)

        total = sum(sum(counts) for counts in channels.values())

        print("Relative channel energy:")

        for channel, counts in channels.items():
            count = sum(counts)

            print(
                f" - {channel:>02}: {count / total:>7.2%}  "
                + "#" * int(100 * count / total)
            )

        print()


async def main(argv):
    parser = argparse.ArgumentParser(description="Perform an energy scan")
    parser.add_argument("serial", type=argparse.FileType("rb"), help="Serial port path")

    args = parser.parse_args(argv)

    # We just want to make sure it exists
    args.serial.close()

    await perform_energy_scan(args.serial.name)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
