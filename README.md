# zigpy-znp

[![Build Status](https://travis-ci.org/zha-ng/zigpy-znp.svg?branch=master)](https://travis-ci.org/zha-ng/zigpy-znp)
[![Coverage](https://coveralls.io/repos/github/zha-ng/zigpy-znp/badge.svg?branch=master)](https://coveralls.io/github/zha-ng/zigpy-znp?branch=master)

[zigpy-znp](https://github.com/zha-ng/zigpy-zhp/) is a Python implementation for the [Zigpy](https://github.com/zigpy/) project to implement support for [TI ZNP interface](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/developing_zigbee_applications/znp_interface/znp_interface.html?highlight=znp) for [Zigbee](https://www.zigbee.org) Network Processors from Texas Instruments.

- https://github.com/zha-ng/zigpy-znp

The Z-Stack ZNP by Texas Instruments are cost-effective, low power, Zigbee Network Processors that provides full Zigbee functionality with a minimal development effort.

In this solution, the Zigbee stack runs on a SoC and the application runs on an external microcontroller. The Z-Stack ZNP handles all the Zigbee protocol tasks, and leaves the resources of the application microcontroller free to handle the application.

This makes it easy for users to add Zigbee to new or existing products at the same time as it provides great flexibility in choice of microcontroller.

Z-Stack ZNP interfaces to any microcontroller through a range of serial interfaces.

[zigpy](https://github.com/zigpy/zigpy/)** currently has support for controlling Zigbee device types such as binary sensors (e.g., motion and door sensors), sensors (e.g., temperature sensors), lightbulbs, switches, and fans. A working implementation of zigbe exist in **[Home Assistant](https://www.home-assistant.io)** (Python based open source home automation software) as part of its **[ZHA component](https://www.home-assistant.io/components/zha/)**

## Compatible hardware

zigpy-znp is being tested with the CC2531 SoC but it might also work with other Z-Stack ZNP SoCs from Texas Instruments.

# Releases of zigpy-znp via PyPI
Tagged versions of zigpy-znp are also released via PyPI

- https://pypi.org/project/zigpy-znp/
- https://pypi.org/project/zigpy-znp//#history
- https://pypi.org/project/zigpy-znp//#files
