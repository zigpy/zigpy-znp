"""Setup module for zigpy-znp"""

import pathlib

from setuptools import setup, find_packages

import zigpy_znp

setup(
    name="zigpy-znp",
    version=zigpy_znp.__version__,
    description="A library for zigpy which communicates with TI ZNP radios",
    long_description=(pathlib.Path(__file__).parent / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="https://github.com/zha-ng/zigpy-znp",
    author="Alexei Chetroi",
    author_email="alexei.chetroi@outlook.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=[
        "pyserial-asyncio",
        "zigpy>=0.24.1",
        "async_timeout",
        "voluptuous",
        "coloredlogs",
    ],
    extras_require={
        "testing": [
            'asynctest; python_version < "3.8.0"',
            "pytest>=5.4.5",
            "pytest-asyncio>=0.12.0",
            "pytest-mock",
        ]
    },
)
