import io
import logging

import pytest

from zigpy_znp.logger import _TRACE
from zigpy_znp.tools.common import UnclosableFile, ClosableFileType, setup_parser


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


def test_command_close_stdout(tmpdir):
    parser = setup_parser("Test parser")
    parser.add_argument(
        "--input",
        "-i",
        type=ClosableFileType("rb"),
        help="Input .bin file",
        default="-",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=ClosableFileType("w"),
        help="Output .txt file",
        default="-",
    )

    parser.add_argument(
        "--other",
        "-t",
        type=ClosableFileType("w"),
        help="Other .txt file",
        required=True,
    )

    args = parser.parse_args(["/dev/null", "-t", str(tmpdir / "test.txt")])

    assert isinstance(args.input, UnclosableFile)
    assert isinstance(args.output, UnclosableFile)
    assert isinstance(args.other, io.TextIOWrapper)

    with args.input as _:
        pass

    with args.output as _:
        pass

    with args.other as _:
        pass

    # pytest patches sys.input on some platforms it seems
    if hasattr(args.input, "closed"):
        assert not args.input.closed

    assert not args.output.closed
    assert args.other.closed
