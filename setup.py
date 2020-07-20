"""Setup module for zigpy-znp"""

import pathlib
from setuptools import find_packages, setup

import zigpy_znp

root = pathlib.Path(__file__).parent

setup(
    name="zigpy-znp",
    version=zigpy_znp.__version__,
    description="A library for zigpy which communicates with TI ZNP radios",
    long_description=(root / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="https://github.com/zha-ng/zigpy-znp",
    author="Alexei Chetroi",
    author_email="alexei.chetroi@outlook.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=[
        "attrs",
        "pyserial-asyncio",
        "zigpy>=0.22.1",
        "async_timeout",
        "voluptuous",
        "coloredlogs",
    ],
    tests_require=[
        "asynctest",
        "pytest>=5.4.5",
        "pytest-asyncio>=0.12.0",
        "pytest-mock",
    ],
)
