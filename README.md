# zigpy-znp

[![Build Status](https://travis-ci.org/zha-ng/zigpy-znp.svg?branch=dev)](https://travis-ci.org/zha-ng/zigpy-znp)
[![Coverage Status](https://coveralls.io/repos/github/zha-ng/zigpy-znp/badge.svg?branch=dev)](https://coveralls.io/github/zha-ng/zigpy-znp?branch=dev)

**[zigpy-znp](https://github.com/zha-ng/zigpy-zhp/)** is a Python library that adds support for common [Texas Instruments ZNP (Zigbee Network Processors)](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/introduction.html) [Zigbee](https://www.zigbee.org) radio modules to [zigpy](https://github.com/zigpy/), a Python Zigbee stack project. 

Together with zigpy and compatible home automation software (namely Home Assistant's [ZHA (Zigbee Home Automation) integration component](https://www.home-assistant.io/integrations/zha/)), you can directly control most Zigbee devices such as Philips Hue, GE, OSRAM LIGHTIFY, Xiaomi/Aqara, IKEA Tradfri, Samsung SmartThings, and many more.

This zigpy-znp library allows Zigpy to interact with Texas Instruments ZNP (Zigbee Network Processor) coordinator firmware via TI Z-Stack Monitor and Test(MT) APIs using an UART/serial interface. Radio module hardware compatible include but is possibly not limited to Texas Instruments CC13x2 and CC26x2R based chips flashed with Z-Stack 3.x coordinator firmware.

# Installation
Install the Python module within your virtual environment:

```shell
(venv) $ pip install zigpy-znp
```

If you are using Home Assistant, copy `custom_components/custom_zha_radios.py` into your `custom_components` folder and create a new entry in your `configuration.yaml` file:

```yaml
custom_zha_radios:
 znp:
   module: zigpy_znp.zigbee.application
   description: TI CC13x2, CC26x2, and ZZH
```

# Configuration

Below are the defaults with the top-level Home Assistant `zha:` key:

```yaml
zha:
  zigpy_config:
    znp_config:
      tx_power: None           # if set, must be between -22 (low) and 19 (high)
      led_mode: None           # if set, must be one of: off, on, blink, flash, toggle
      skip_bootloader: True    # skips the 60s bootloader delay on some CC2531 sticks
```

# Backup and restore
A complete NVRAM backup can be performed to migrate between different radios **based on the same chip**. Anything else is untested.

```shell
(venv) $ python -m zigpy_znp.tools.nvram_read /dev/serial/by-id/old_radio -o backup.json
(venv) $ python -m zigpy_znp.tools.nvram_write /dev/serial/by-id/new_radio -i backup.json
```

Tested migrations:

 - LAUNCHXL-CC26X2R1 running 3.30.00.03 to and from the zig-a-zig-ah! running 4.10.00.78.

# Hardware requirements
USB-adapters, GPIO-modules, and development-boards running recent TI Z-Stack releases (i.e. CC13x2 and CC26x2) are supported. Reference hardware for this project includes:

 - [TI LAUNCHXL-CC26X2R1](https://www.ti.com/tool/LAUNCHXL-CC26X2R1) running [Z-Stack 3.30.00.03](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/Z-Stack_3.x.0/bin). You can flash `CC26X2R1_20191106.hex` using [TI's UNIFLASH](https://www.ti.com/tool/download/UNIFLASH).
 - [Electrolama's zig-a-zig-ah!](https://electrolama.com/projects/zig-a-zig-ah/) running [Z-Stack 4.10.00.78](https://github.com/Koenkk/Z-Stack-firmware/tree/develop/coordinator/Z-Stack_3.x.0/bin). You can flash `CC26X2R1_20200417.hex` using [cc2538-bsl](https://github.com/JelmerT/cc2538-bsl).

Z-Stack versions 3.x and above are currently required and all communication with the radio module is done over the the Z-Stack Monitor and Test (MT) interface via a serial port.

## Texas Instruments Chip Part Numbers
Texas Instruments (TI) has quite a few different wireless MCU chips and they are all used/mentioned in open-source Zigbee world which can be daunting if you are just starting out. Here is a quick summary of part numbers and key features.

### Supported newer generation TI chips

#### 2.4GHz frequency only chips
- CC2652R = 2.4GHz only wireless MCU for IEEE 802.15.4 multi-protocol (Zigbee, Bluetooth, Thread, IEEE 802.15.4g IPv6-enabled smart objects like 6LoWPAN, and proprietary systems). Cortex-M0 core for radio stack and Cortex-M4F core for application use, plenty of RAM. Free compiler option from TI.
- CC2652RB = Pin compatible "Crystal-less" CC2652R (so you could use it if you were to build your own zzh and omit the crystal) but not firmware compatible.
- CC2652P = CC2652R with a built-in RF PA. Not pin or firmware compatible with CC2652R/CC2652RB. 

#### Multi frequency chips
- CC1352R = Sub 1 GHz & 2.4 GHz wireless MCU. Essentially CC2652R with an extra sub-1GHz radio.
- CC1352P = CC1352R with a built in RF PA.

### Unsupported older generation TI chips
- CC2530 = 2.4GHz Zigbee and IEEE 802.15.4 wireless MCU. 8051 core, has very little RAM. Needs expensive compiler license for official TI stack.
- CC2531 = CC2530 with built-in USB. Used in the cheap "Zigbee sticks" sold everywhere.

### Auxiliary TI chips
- CC2591 and CC2592 = 2.4 GHz range extenders. These are not wireless MCUs, just auxillary PA (Power Amplifier) and LNA (Low Noise Amplifier) in the same package to improve RF (Radio Frequency) range of any 2.4 GHz radio chip.

# Releases via PyPI

Tagged versions will also be released via PyPI

 - https://pypi.org/project/zigpy-znp/
 - https://pypi.org/project/zigpy-znp/#history
 - https://pypi.org/project/zigpy-znp/#files

# External documentation and reference

- http://www.ti.com/tool/LAUNCHXL-CC26X2R1
- http://www.ti.com/tool/LAUNCHXL-CC1352P

# How to contribute

If you are looking to make a code or documentation contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

# Related projects

### Zigpy
**[zigpy](https://github.com/zigpy/zigpy)** is [Zigbee protocol stack](https://en.wikipedia.org/wiki/Zigbee) integration project to implement the **[Zigbee Home Automation](https://www.zigbee.org/)** standard as a Python library. Zigbee Home Automation integration with zigpy allows you to connect one of many off-the-shelf Zigbee adapters using one of the available Zigbee radio library modules compatible with zigpy to control Zigbee devices. There is currently support for controlling Zigbee device types such as binary sensors (e.g. motion and door sensors), analog sensors (e.g. temperature sensors), lightbulbs, switches, and fans. Zigpy is tightly integrated with [Home Assistant](https://www.home-assistant.io)'s [ZHA component](https://www.home-assistant.io/components/zha/) and provides a user-friendly interface for working with a Zigbee network.
