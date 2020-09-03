import pytest
import logging

from zigpy_znp.tools.common import setup_parser
from zigpy_znp.logger import _TRACE


@pytest.mark.parametrize(
    "v_count,level", [(0, logging.INFO), (1, logging.DEBUG), (2, _TRACE)]
)
def test_logging_levels(v_count, level, mocker, caplog):
    mocker.patch("logging.addLevelName")

    parser = setup_parser("Test parser")
    parser.parse_args(["/dev/null"] + ["-v"] * v_count)

    assert logging.getLogger().level == level
