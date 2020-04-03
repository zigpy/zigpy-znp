"""Setup module for zigpy-znp"""

from setuptools import find_packages, setup

import zigpy_znp

setup(
    name="zigpy-znp",
    version=zigpy_znp.__version__,
    description="A library which communicates with ZNP radios for zigpy",
    url="http://github.com/zha-ng/zigpy-znp",
    author="Alexei Chetroi",
    author_email="alexei.chetroi@outlook.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=[
        "attrs",
        "pyserial-asyncio",
        "zigpy-homeassistant >= 0.18.0",
        "async_timeout",
    ],
    tests_require=[
        "asynctest",
        "pytest==5.3.5",
        "pytest-asyncio",
        "asyncmock",
        "pytest-mock",
    ],
)
