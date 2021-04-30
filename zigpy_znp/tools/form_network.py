import sys
import asyncio
import logging

from zigpy_znp.tools.common import setup_parser
from zigpy_znp.zigbee.application import ControllerApplication

LOGGER = logging.getLogger(__name__)


async def form_network(radio_path):
    LOGGER.info("Starting up zigpy-znp")

    config = ControllerApplication.SCHEMA({"device": {"path": radio_path}})
    app = ControllerApplication(config)

    await app.startup(force_form=True)
    await app.shutdown()


async def main(argv):
    parser = setup_parser("Form a network with randomly generated settings")
    args = parser.parse_args(argv)

    await form_network(args.serial)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))  # pragma: no cover
