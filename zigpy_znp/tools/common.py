import logging
import argparse
import coloredlogs

from zigpy_znp.logger import _TRACE


LOG_LEVELS = [logging.INFO, logging.DEBUG, _TRACE]


class CustomArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        args = super().parse_args(args, namespace)

        # Since we're running as a CLI tool, install our own log level and color logger
        verbosity = args.verbosity
        log_level = LOG_LEVELS[min(max(0, verbosity), len(LOG_LEVELS) - 1)]

        logging.addLevelName(_TRACE, "TRACE")
        coloredlogs.install(level=log_level)

        return args


def setup_parser(description: str) -> argparse.ArgumentParser:
    """
    Creates an ArgumentParser that sets up a logger with a configurable verbosity
    and a positional serial port argument.
    """

    parser = CustomArgumentParser(description=description)
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbosity",
        action="count",
        default=0,
        help="increases verbosity",
    )
    parser.add_argument("serial", type=str, help="Serial port path")

    return parser
