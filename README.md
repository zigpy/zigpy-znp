# zigpy-znp

[![Build Status](https://travis-ci.org/zha-ng/zigpy-znp.svg?branch=dev)](https://travis-ci.org/zha-ng/zigpy-znp)
[![Coverage Status](https://coveralls.io/repos/github/zha-ng/zigpy-znp/badge.svg?branch=dev)](https://coveralls.io/github/zha-ng/zigpy-znp?branch=dev)

[zigpy-znp](https://github.com/zha-ng/zigpy-zhp/) is a Python library implemention which adds support for common [Texas Instruments ZNP (Zigbee Network Processors)](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/developing_zigbee_applications/znp_interface/znp_interface.html) based [Zigbee](https://www.zigbee.org) radio module chips hardware to [Zigpy](https://github.com/zigpy/), a Python Zigbee stack project. 

The goal of this project is to add native support for Texas Instruments Z-Stack 3 based USB sticks in Home Assistant's built-in ZHA (Zigbee Home Automation) integration component (via the [zigpy](https://github.com/zigpy/) library), allowing Home Assistant with such hardware to nativly support direct control of compatible Zigbee devices such as Philips HUE, GE, Osram Lightify, Xiaomi/Aqara, IKEA Tradfri, Samsung SmartThings, and many more.

- https://www.home-assistant.io/integrations/zha/

zigpy-znp allows Zigpy to interact with Texas Instruments ZNP (Zigbee Network Processor) coordinator firmware via TI Z-Stack Monitor and Test(MT) APIs using an UART/serial interface. Radio module hardware compatible include but is possibly not limited to Texas Instruments CC13x2 and CC26x2R chips flashed with Z-Stack 3.x coordinator firmware.

## WARNING! - Work in progress
Disclaimer: This software library is provided "AS IS", without warranty of any kind. The zigpy-znp project is still under early development as WIP (work in progress), as such it is not fully working yet. Testing of this library is currently onky recommended to developers and advanced testers of bleeding edge software looking to assist with early alpha-testing in on non-production systems, just for test purposes.

# Hardware requirement
USB-adapters and GPIO-modules based hardware capable of running the TI Z-Stack versions 3.0 and above (i.e. CC13x2 and CC26x2) should in theory all be supported by the zigpy-znp library but testing by the developers is currently only done with the [LAUNCHXL-CC26X2R1](https://www.ti.com/tool/LAUNCHXL-CC26X2R1) (Texas Instruments official CC2652 chip based development board) running [Z-Stack 3.30.00.03 with @Koenkk's config tweaks](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/Z-Stack_3.x.0/bin) as as reference hardware for the project. 

CC253x based hardware is not recommended as they might not be powerful enough to the TI Z-Stack 3 coordinator firmware.

Note that you also have to flash the chip a custom Z-Stack 3.x coordinator firmware before you can use the hardware, read the firmware requirement section below.

## Hardware being tested by zigpy-znp developers
  - [CC2531 USB stick hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
  - [CC2652R dev board hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)

 ## Hardware not yet tested by zigpy-znp developers
  - [CC1352P-2 dev board hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
  
## Hardware not recommended by zigpy-znp developers
  - [CC2531 USB stick hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
  - [CC2530 + CC2591 USB stick hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
  - [CC2530 + CC2592 dev board hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
  - [CC2538 + CC2592 dev board hardware flashed with Z-Stack 3 coordinator firmware from the Zigbee2mqtt project](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/)
 
## Firmware requirement
Z-Stack 3 firmware requirement is that they support Texas Instruments Z-Stack Monitor and Test(MT) APIs using an UART interface (serial communcation protocol), which they should do if they are flashed with Z-Stack 3.x "coordinator" firmware with config tweaks by @Koenkk (originally made for the Zigbee2mqtt project).

- https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator

Texas Instruments CC13x2 and CC26x2 based adapters/boards already come with a bootloader so can be flashed over USB using the official "Flash Programmer v2" from Texas Instruments.

- http://www.ti.com/tool/FLASH-PROGRAMMER

Again, using Texas Instruments CC253x based adapters/boards as a Z-Stack 3 coordinator is not recommended though they could potentially still be used for development porposes, (however note that Z-Stack 3 coordinator firmware should in theory perform better on CC2538 based adapters than on CC2530 or CC2531 based adapters). CC253x based adapters/boards does howwever not come with a bootloader so you will normally need special hardware equipment for flashing firmware them with using the ["Flash Programmer v1" (not v2) from Texas Instruments](http://www.ti.com/tool/FLASH-PROGRAMMER) and that device preparation process is best described by the [Zigbee2mqtt](https://www.zigbee2mqtt.io/) project whos community develops the Z-Stack coordinator firmware that this zigpy-znp libary requires. The Zigbee2mqtt project also has intructions for several alternative metods on how to initially flash their special Z-Stack 3 coordinator firmware on a new CC253x as well as other Texas Instruments CC based USB adapters and development boards that does not have a bootloader. They also have a FAQ and knowledgebase that can be useful for working with these supported hardware adapters/equipment as well as with Zigbee devices.

- https://www.zigbee2mqtt.io/information/supported_adapters.html
- https://www.zigbee2mqtt.io/getting_started/what_do_i_need.html
- https://www.zigbee2mqtt.io/getting_started/flashing_the_cc2531.html
- https://www.zigbee2mqtt.io/information/alternative_flashing_methods.html

## Port configuration

- To configure __usb__ port path for your TI CC serial device, just specify the TTY (serial com) port, example : `/dev/ttyACM0`

Developers hould note that that Texas Instruments recommends different baud rates for UART interface of different TI CC chips.
  - CC13x2 and CC26x2 supports flexible UART baud rate generation up to a maximum of 1.5 Mbps.
  - CC2538 also supports flexible UART baud rate generation but only up to a maximum of 460800 baud.
  - CC2530 and CC2531 default recommended UART baud rate is 115200 baud.

# Releases via PyPI

Tagged versions will also be released via PyPI

- TO-DO

# External documentation and reference

- http://www.ti.com/tool/LAUNCHXL-CC26X2R1
- http://www.ti.com/tool/LAUNCHXL-CC1352P

# How to contribute

If you are looking to make a code or documentation contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

# Related projects

### Zigpy
[zigpy](https://github.com/zigpy/zigpy)** is **[Zigbee protocol stack](https://en.wikipedia.org/wiki/Zigbee)** integration project to implement the **[Zigbee Home Automation](https://www.zigbee.org/)** standard as a Python 3 library. Zigbee Home Automation integration with zigpy allows you to connect one of many off-the-shelf Zigbee adapters using one of the available Zigbee radio library modules compatible with zigpy to control Zigbee based devices. There is currently support for controlling Zigbee device types such as binary sensors (e.g., motion and door sensors), sensors (e.g., temperature sensors), lightbulbs, switches, and fans. A working implementation of zigbe exist in **[Home Assistant](https://www.home-assistant.io)** (Python based open source home automation software) as part of its **[ZHA component](https://www.home-assistant.io/components/zha/)**
