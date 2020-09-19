import pytest


@pytest.fixture(autouse=True)
def patch_logging(mocker):
    # To prevent global state from being modified in tool tests
    mocker.patch("logging.addLevelName")
    mocker.patch("coloredlogs.install")
