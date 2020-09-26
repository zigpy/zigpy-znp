# zigpy-znp

[![Build Status](https://travis-ci.org/zha-ng/zigpy-znp.svg?branch=dev)](https://travis-ci.org/zha-ng/zigpy-znp)
[![Coverage Status](https://coveralls.io/repos/github/zha-ng/zigpy-znp/badge.svg?branch=dev)](https://coveralls.io/github/zha-ng/zigpy-znp?branch=dev)

**[zigpy-znp](https://github.com/zha-ng/zigpy-zhp/)** is a Python library that adds support for common [Texas Instruments ZNP (Zigbee Network Processors)](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/introduction.html) [Zigbee](https://www.zigbee.org) radio modules to [zigpy](https://github.com/zigpy/), a Python Zigbee stack project.

Together with zigpy and compatible home automation software (namely Home Assistant's [ZHA (Zigbee Home Automation) integration component](https://www.home-assistant.io/integrations/zha/)), you can directly control Zigbee devices such as Philips Hue, GE, OSRAM LIGHTIFY, Xiaomi/Aqara, IKEA Tradfri, Samsung SmartThings, and many more.

# Installation

## Python module
Install the Python module within your virtual environment:

```console
$ virtualenv -p python3.8 venv                                 # if you don't already have one
$ source venv/bin/activate
(venv) $ pip install git+https://github.com/zha-ng/zigpy-znp/  # latest commit from Git
(venv) $ pip install zigpy-znp                                 # or, latest stable from PyPI
```

## Home Assistant
Stable releases of zigpy-znp are pre-installed by Home Assistant and are used for all new networks for TI radios running Z-Stack 3 or above. If you have already setup Home Assistant's ZHA component with a TI radio, ZHA may be using the [zigpy-cc](https://github.com/zigpy/zigpy-cc/) library to communicate with the radio hardware. Navigate to the folder containing your `configuration.yaml` file, edit `.storage/core.config_entries`, and change `"radio_type": "ti_cc"` to `"radio_type": "znp"`.

### Testing `dev` with Home Assistant Core

Upgrade the package within your virtual environment (requires `git`):

```console
(venv) $ pip install git+https://github.com/zha-ng/zigpy-znp/
```

Launch Home Assistant the `--skip-pip` command line option to prevent zigpy-znp from being downgraded. Running with this option may prevent newly added integrations from installing required packages.

### Testing `dev` with Home Assistant Supervised

 - Add https://github.com/home-assistant/hassio-addons-development as an addon repository.
 - Install the "Custom deps deployment" addon.
 - Add the following to your `configuration.yaml` file:
	```yaml
	pypi:
	  - git+https://github.com/zha-ng/zigpy-znp/
	```

# Configuration
Below are the defaults with the top-level Home Assistant `zha:` key.
You probably do not need to change these options, they are provided only for reference:

```yaml
zha:
  zigpy_config:
    znp_config:
      # "auto" picks the largest value that keeps the device's transmit buffer from getting full
      max_concurrent_requests: auto

      # Only if your stick has a built-in power amplifier (i.e. CC1352P and CC2592)
      # If set, must be between -22 (low) and 19 (high)
      tx_power:  

      # Only if your stick has a controllable LED (the CC2531)
      # If set, must be one of: off, on, blink, flash, toggle
      led_mode:


      ### Internal configuration, there's no reason to touch these values

      # Skips the 60s bootloader delay on CC2531 sticks
      skip_bootloader: True

      # Timeout for synchronous requests' responses
      sreq_timeout: 15

      # Timeout for asynchronous requests' callback responses
      arsp_timeout: 30

      # Delay between auto-reconnect attempts in case the device gets disconnected
      auto_reconnect_retry_delay: 5
```

# NVRAM Backup and restore
A complete NVRAM backup can be performed to migrate between different radios **based on the same chip**. Anything else will not work.

```console
(venv) $ python -m zigpy_znp.tools.nvram_read /dev/serial/by-id/old_radio -o backup.json
(venv) $ python -m zigpy_znp.tools.nvram_write /dev/serial/by-id/new_radio -i backup.json
```

Tested migrations:

 - LAUNCHXL-CC26X2R1 running 3.30.00.03 to and from the zig-a-zig-ah! running 4.10.00.78.

# Energy scan
Perform an energy scan to find a quiet Zigbee channel:

```console
$ python -m zigpy_znp.tools.energy_scan /dev/cu.usbmodem14101
Channel energy (mean of 1 / 5):
------------------------------------------------
 + Lower energy is better
 + Active Zigbee networks on a channel may still cause congestion
 + Using 26 in the USA may have lower TX power due to FCC regulations
 + Zigbee channels 15, 20, 25 fall between WiFi channels 1, 6, 11
 + Some Zigbee devices only join networks on channels 11, 13, 15, 20, or 25
------------------------------------------------
 - 11    61.57%  #############################################################
 - 12    60.78%  ############################################################
 - 13    12.16%  ############
 - 14    58.43%  ##########################################################
 - 15    57.65%  #########################################################
 - 16    29.80%  #############################
 - 17    38.82%  ######################################
 - 18    47.06%  ###############################################
 - 19    36.86%  ####################################
 - 20    10.98%  ##########
 - 21    16.47%  ################
 - 22    33.73%  #################################
 - 23    30.59%  ##############################
 - 24    20.39%  ####################
 - 25     5.88%  #####
 - 26*   20.39%  ####################
```

# Hardware requirements
USB-adapters, GPIO-modules, and development-boards running TI's Z-Stack are supported. Reference hardware for this project includes:

 - (**STABLE**) [TI LAUNCHXL-CC26X2R1](https://www.ti.com/tool/LAUNCHXL-CC26X2R1) running [Z-Stack 3.30.00.03](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/Z-Stack_3.x.0/bin). You can flash `CC26X2R1_20191106.hex` using [TI's UNIFLASH](https://www.ti.com/tool/download/UNIFLASH).
 - (**STABLE**) [Electrolama's zig-a-zig-ah!](https://electrolama.com/projects/zig-a-zig-ah/) running [Z-Stack 4.10.00.78](https://github.com/Koenkk/Z-Stack-firmware/tree/develop/coordinator/Z-Stack_3.x.0/bin). You can flash `CC26X2R1_20200417.hex` using [cc2538-bsl](https://github.com/JelmerT/cc2538-bsl).
 - (**BETA**) CC2531 running [Z-Stack 3.0.1](https://github.com/Koenkk/Z-Stack-firmware/blob/master/coordinator/Z-Stack_3.0.x/bin/CC2531_20190425.zip). You can flash `CC2531ZNP-without-SBL.bin` to your stick directly with `zigpy_znp`: `python -m zigpy_znp.tools.flash_write -i /path/to/CC2531ZNP-without-SBL.bin /dev/serial/by-id/YOUR-CC2531` if your stick already has a serial bootloader.
 - (**ALPHA**) CC2531 running [Z-Stack Home 1.2](https://github.com/Koenkk/Z-Stack-firmware/blob/master/coordinator/Z-Stack_Home_1.2/bin/default/CC2531_DEFAULT_20190608.zip). You can flash `CC2531ZNP-Prod.bin` to your stick directly with `zigpy_znp`: `python -m zigpy_znp.tools.flash_write -i /path/to/CC2531ZNP-Prod.bin /dev/serial/by-id/YOUR-CC2531` if your stick already has a serial bootloader.

## Texas Instruments Chip Part Numbers
Texas Instruments (TI) has quite a few different wireless MCU chips and they are all used/mentioned in open-source Zigbee world which can be daunting if you are just starting out. Here is a quick summary of part numbers and key features.

### Supported newer generation TI chips

#### 2.4GHz frequency only chips
- CC2652R: 2.4GHz only wireless MCU for IEEE 802.15.4 multi-protocol (Zigbee, Bluetooth, Thread, IEEE 802.15.4g IPv6-enabled smart objects like 6LoWPAN, and proprietary systems). Cortex-M0 core for radio stack and Cortex-M4F core for application use, plenty of RAM. Free compiler option from TI.
- CC2652RB: Pin compatible "Crystal-less" CC2652R (so you could use it if you were to build your own zzh and omit the crystal) but not firmware compatible.
- CC2652P: CC2652R with a built-in RF PA. Not pin or firmware compatible with CC2652R/CC2652RB. 

#### Multi frequency chips
- CC1352R: Sub 1 GHz & 2.4 GHz wireless MCU. Essentially CC2652R with an extra sub-1GHz radio.
- CC1352P: CC1352R with a built in RF PA.

### Auxiliary TI chips
- CC2591 and CC2592: 2.4 GHz range extenders. These are not wireless MCUs, just auxillary PA (Power Amplifier) and LNA (Low Noise Amplifier) in the same package to improve RF (Radio Frequency) range of any 2.4 GHz radio chip.

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
