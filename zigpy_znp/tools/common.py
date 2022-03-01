from __future__ import annotations

import sys
import typing
import logging
import argparse

import jsonschema
import coloredlogs

import zigpy_znp.types as t
import zigpy_znp.logger as log

LOG_LEVELS = [logging.INFO, logging.DEBUG, log._TRACE]
OPEN_COORDINATOR_BACKUP_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://github.com/zigpy/open-coordinator-backup/schema.json",
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "pattern": "^zigpy/open-coordinator-backup$",
                },
                "version": {"type": "integer", "minimum": 1, "maximum": 1},
                "source": {"type": "string", "pattern": "^(.*?)+@(.*?)$"},
                "internal": {"type": "object"},
            },
            "required": ["version", "source"],
        },
        "stack_specific": {
            "type": "object",
            "properties": {
                "zstack": {
                    "type": "object",
                    "properties": {
                        "tclk_seed": {"type": "string", "pattern": "[a-fA-F0-9]{32}"},
                    },
                }
            },
        },
        "coordinator_ieee": {"type": "string", "pattern": "[a-fA-F0-9]{16}"},
        "pan_id": {"type": "string", "pattern": "[a-fA-F0-9]{4}"},
        "extended_pan_id": {"type": "string", "pattern": "[a-fA-F0-9]{16}"},
        "nwk_update_id": {"type": "integer", "minimum": 0, "maximum": 255},
        "security_level": {"type": "integer", "minimum": 0, "maximum": 7},
        "channel": {"type": "integer", "minimum": 11, "maximum": 26},
        "channel_mask": {
            "type": "array",
            "items": {"type": "integer", "minimum": 11, "maximum": 26},
        },
        "network_key": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "pattern": "[a-fA-F0-9]{32}"},
                "sequence_number": {"type": "integer", "minimum": 0, "maximum": 255},
                "frame_counter": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4294967295,
                },
            },
            "required": ["key", "sequence_number", "frame_counter"],
        },
        "devices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nwk_address": {
                        "type": ["string", "null"],
                        "pattern": "[a-fA-F0-9]{4}",
                    },
                    "ieee_address": {"type": "string", "pattern": "[a-fA-F0-9]{16}"},
                    "is_child": {"type": "boolean"},
                    "link_key": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "pattern": "[a-fA-F0-9]{16}"},
                            "tx_counter": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 4294967295,
                            },
                            "rx_counter": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 4294967295,
                            },
                        },
                        "required": ["key", "tx_counter", "rx_counter"],
                    },
                },
                "required": ["nwk_address", "ieee_address"],
            },
        },
    },
    "required": [
        "metadata",
        "coordinator_ieee",
        "pan_id",
        "extended_pan_id",
        "nwk_update_id",
        "security_level",
        "channel",
        "channel_mask",
        "network_key",
        "devices",
    ],
}


def validate_backup_json(backup: t.JSONType) -> None:
    jsonschema.validate(backup, schema=OPEN_COORDINATOR_BACKUP_SCHEMA)


class CustomArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args: typing.Sequence[str] | None = None, namespace=None):
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
            fmt=(
                "%(asctime)s.%(msecs)03d"
                " %(hostname)s"
                " %(name)s"
                " %(levelname)s %(message)s"
            ),
            level=log_level,
            level_styles=level_styles,
        )

        return args


class UnclosableFile:
    """
    Wraps a file object so that every operation but "close" is proxied.
    """

    def __init__(self, f):
        self.f = f

    def close(self):
        return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return

    def __getattr__(self, name):
        return getattr(self.f, name)


class ClosableFileType(argparse.FileType):
    """
    Allows `FileType` to always be closed properly, even with stdout and stdin.
    """

    def __call__(self, string):
        f = super().__call__(string)

        if f not in (sys.stdin, sys.stdout):
            return f

        return UnclosableFile(f)


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
