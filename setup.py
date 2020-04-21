"""Setup module for zigpy-znp"""

import pathlib
from setuptools import find_packages, setup

import zigpy_znp

root = pathlib.Path(__file__).parent

setup(
    name="zigpy-znp",
    version=zigpy_znp.__version__,
    description="A library which communicates with ZNP radios for zigpy",
    long_description=(root / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="http://github.com/zha-ng/zigpy-znp",
    author="Alexei Chetroi",
    author_email="alexei.chetroi@outlook.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=[
        "attrs",
        "pyserial-asyncio",
        "zigpy >= 0.20.0",
        "async_timeout",
        "voluptuous",
    ],
    tests_require=[
        "asynctest",
        "pytest==5.3.5",
        "pytest-asyncio==0.10.0",
        "asyncmock",
        "pytest-mock",
    ],
)
