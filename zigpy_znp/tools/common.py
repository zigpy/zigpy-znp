import logging
import argparse

import coloredlogs

import zigpy_znp.logger as log

LOG_LEVELS = [logging.INFO, logging.DEBUG, log._TRACE]


class CustomArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        args = super().parse_args(args, namespace)

        # Since we're running as a CLI tool, install our own log level and color logger
        log.TRACE = log._TRACE
        logging.addLevelName(log.TRACE, "TRACE")

        # But still allow the user to configure verbosity
        verbosity = args.verbosity
        log_level = LOG_LEVELS[min(max(0, verbosity), len(LOG_LEVELS) - 1)]

        # coloredlogs uses "spam" for level 5, not "trace"
        level_styles = coloredlogs.DEFAULT_LEVEL_STYLES.copy()
        level_styles["trace"] = level_styles["spam"]

        logging.getLogger().setLevel(log_level)

        coloredlogs.install(
            level=log_level,
            level_styles=level_styles,
        )

        return args


def setup_parser(description: str) -> argparse.ArgumentParser:
    """
    Creates an ArgumentParser that sets up a logger with a configurable verbosity
    and a positional serial port argument.
    """

    parser = CustomArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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
