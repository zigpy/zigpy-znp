import logging

import pytest

from zigpy_znp.logger import _TRACE
from zigpy_znp.tools.common import setup_parser


@pytest.mark.parametrize(
    "verbosity,level", [(0, logging.INFO), (1, logging.DEBUG), (2, _TRACE)]
)
def test_logging_level_parser(verbosity, level, mocker):
    mock_levels = {}

    logging_getLevelName = logging.getLevelName

    def getLevelName(level):
        if level in mock_levels:
            return mock_levels[level]

        return logging_getLevelName(level)

    mocker.patch("logging.getLevelName", getLevelName)
    mocker.patch("logging.addLevelName", mock_levels.__setitem__)

    parser = setup_parser("Test parser")
    parser.parse_args(["/dev/null"] + ["-v"] * verbosity)

    assert logging.getLogger().level == level
