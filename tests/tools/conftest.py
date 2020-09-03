import pytest

from ..test_application import znp_server  # noqa: F401


@pytest.fixture
def openable_serial_znp_server(mocker, znp_server):  # noqa: F811
    # The fake serial port is "opened" by argparse, which we have to allow
    def fixed_open(
        file,
        mode="r",
        buffering=-1,
        encoding=None,
        errors=None,
        newline=None,
        closefd=True,
        opener=None,
    ):
        if file == znp_server._port_path:

            class FakeFile:
                name = file

                def close(self):
                    pass

            return FakeFile()

        return open(file, mode, buffering, encoding, errors, newline, closefd, opener)

    mocker.patch("argparse.open", new=fixed_open)

    # To prevent future tests involving logging from failing
    mocker.patch("logging.addLevelName")
    mocker.patch("coloredlogs.install")

    return znp_server
