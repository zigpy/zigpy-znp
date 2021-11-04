# zigpy-znp command line tools
The command line tools bundled with zigpy-znp do not depend in any way on Home Assistant
and will work with any Texas Instruments radio previously used with ZHA or Zigbee2MQTT.


# Table of Contents
- [Installation](#installation)
  * [In Home Assistant OS](#in-home-assistant-os)
  * [In other environments](#in-other-environments)
    + [Installing Python 3.7 or above](#installing-python-37-or-above)
      - [Linux](#linux)
      - [macOS](#macos)
      - [Windows](#windows)
    + [Creating a virtualenv (recommended)](#creating-a-virtualenv-recommended)
    + [Installing zigpy-znp](#installing-zigpy-znp)
- [Tools](#tools)
  * [Backup and restore](#backup-and-restore)
    + [Network backup](#network-backup)
    + [NVRAM backup](#nvram-backup)
  * [NVRAM reset](#nvram-reset)
  * [Network formation](#network-formation)
  * [Network scan](#network-scan)
  * [Energy scan](#energy-scan)
  * [CC2531 tools](#cc2531-tools)
    + [Network migration for coordinator upgrades](#network-migration-for-coordinator-upgrades)
    + [Flash operations](#flash-operations)
      - [Flash read](#flash-read)
      - [Flash write](#flash-write)


# Installation
## In Home Assistant OS
zigpy-znp is already installed by Home Assistant's ZHA component and is used to communicate
with your radio. You only need to gain access to the correct Docker container and temporarily
disable ZHA to run any of the tools:

1. Install [community "SSH & Web Terminal" addon](https://github.com/hassio-addons/addon-ssh/blob/main/ssh/DOCS.md) (not the official "Terminal & SSH" addon!) and configure your credentials. Note: the addon will fail to start if you use an insecure password so it's better to configure it with public key authentication.
2. Disable "Protection mode" in the addon's configuration.
3. At the shell, log into the main Home Assistant Docker container:
    ```bash
    docker exec -it homeassistant bash
    ```

4. Since ZHA is still using your Zigbee radio, you must temporarily *disable* the ZHA
   integration before continuing. This is done with the three-dot dropdown menu in the
   "Integrations" section of the Home Assistant web UI.

## In other environments
### Installing Python 3.7 or above
#### Linux
For Ubuntu 20.04:

```console
$ sudo apt install python3 python3-virtualenv  # ensure this is Python 3.7 or above
```

#### macOS
[Homebrew](https://brew.sh/) allows easy installation of recent Python releases.

```console
$ brew install python@3
```
If you want to use virtualenv (see below), install it as well
```console
$ brew install virtualenv
```

#### Windows
Download the latest release of Python 3 from the [Python homepage](https://www.python.org/downloads/).

If you are using a zzh! or any other device with a CH340 USB-serial adapter, you may have
to install a driver before the COM port is recognized. SparkFun Electronics has a detailed
guide on how to do this here: https://learn.sparkfun.com/tutorials/how-to-install-ch340-drivers/all#windows-710 .

Device Manager will tell you the radio's assigned `COM` port.

If you are not already using the [Windows Terminal](https://www.microsoft.com/en-us/p/windows-terminal/9n0dx20hk701?activetab=pivot:overviewtab) by Microsoft, I suggest you try it. Otherwise, open a PowerShell or Command Prompt window.

The Windows `py` launcher will be used in place of `python` in all subsequent commands
so instead of running this:

```console
> python -m zigpy_znp.tools.foo
```

Run this:

```console
> py -3 -m zigpy_znp.tools.foo
```

### Creating a virtualenv (recommended)
It is recommended you install Python packages within a virtualenv to prevent dependency
conflicts. You will need to activate the virtualenv again if you close your terminal
emulator.

For Linux and macOS:

```console
$ virtualenv -p 3 venv
$ source venv/bin/activate
```

For Windows:

```console
> py -3 -m venv venv
> venv\Scripts\activate.ps1  # for PowerShell
> venv\Scripts\activate.bat  # for cmd.exe
```

### Installing zigpy-znp
The latest stable release from the PyPI
```console
$ pip install zigpy-znp
```

Or, the latest commit from the `dev` branch, cloned with `git`:
```console
$ pip install git+https://github.com/zigpy/zigpy-znp.git@dev
```

Same as above, but downloaded as a tarball, if you do not have `git` installed:
```
$ pip install https://github.com/zigpy/zigpy-znp/archive/dev.tar.gz
```

# Tools
All tools can be passed `-v` and `-vv` flags for extra verbosity and accept serial port
paths, COM devices, and serial ports exposed over TCP:

```console
> py -3 -m zigpy_znp.tools.network_backup COM4
$ python -m zigpy_znp.tools.network_backup socket://192.168.1.123:4567
$ python -m zigpy_znp.tools.network_backup /dev/serial/by-id/...
$ python -m zigpy_znp.tools.network_backup /dev/cu.usbmodem14101
```

## Backup and restore
Firmware upgrades usually erase network settings so **you should perform a backup before
upgrading**. Currently there are two formats: a high-level backup format independent of
zigpy-znp, and a complete low-level NVRAM backup of the device.

<span id="network-backup-beta"></span> <!-- so old links still work -->
### Network backup
A high-level and stack-agnostic backup of your device's network data using the
[Open Coordinator Backup Format](https://github.com/zigpy/open-coordinator-backup/)
allows you to snapshot the device state and move your network between any supported
hardware and firmware versions.

```console
$ python -m zigpy_znp.tools.network_backup /dev/serial/by-id/old_radio -o network_backup.json
$ python -m zigpy_znp.tools.network_restore /dev/serial/by-id/new_radio -i network_backup.json
```

For example, a network backup will allow you to migrate from a CC2531 with Z-Stack Home
1.2 to a zzh! without re-joining any devices. The backup format is human-readable and 
fully documented so you can fill out the appropriate information by hand to form a network
if you are migrating from a coordinator that isn't currently supported.

To get ZHA to utilize your new radio, either:
 1. Remove and re-add the ZHA integration. Your existing entities will not disappear.
 2. Directly edit `/config/.storage/core.config_entries`, update the coordinator's
    `path`, and change the `baudrate` to `115200`.

### NVRAM backup
In contrast to the high-level coordinator backup described above, an exhaustive, low-level
NVRAM backup can be performed to clone your entire device state. The backed up data is
opaque and contains little human-readable information.

Note: the NVRAM structure is device- and firmware-specific so **an NVRAM backup can only be
restored to a device similar to the original**:

 - CC2531 with Z-Stack Home 1.2 is **only** compatible with another CC2531 running Z-Stack Home 1.2.
 - CC2531 with Z-Stack 3.0 is **only** compatible with another CC2531 running Z-Stack 3.0.
 - Newer chips like the CC2652R/RB and the CC1352P (zzh!, Slaesh's stick, and the LAUNCHXL boards) **are all cross-compatible**.

```console
$ python -m zigpy_znp.tools.nvram_read /dev/serial/by-id/old_radio -o backup.json
$ python -m zigpy_znp.tools.nvram_write /dev/serial/by-id/new_radio -i backup.json
```

## NVRAM reset
Erase your device's NVRAM entries to fully reset it:

```console
$ python -m zigpy_znp.tools.nvram_reset /dev/serial/by-id/your-radio
```

Some warnings are normal, as not all entries will be present in every device.

## Network formation
Form a new network on the command line:

```console
$ python -m zigpy_znp.tools.form_network /dev/serial/by-id/your-radio
```

Currently no command line options are supported so the network will be formed only on
channel 15 with randomly-generated settings.

## Network scan
Nearby routers can be discovered by performing an active network scan. Pass `-a` to
prevent beacon deduplication and pass `-c 11,15` to narrow the set of channels scanned.

```console
$ python -m zigpy_znp.tools.network_scan -a -c 11 /dev/cu.usbmodem14201
1616102905.35 [EPID: 00:aa:bb:cc:dd:ee:ff:aa, PID: 0x8C9F, from: 0x0000]: Channel=11 PermitJoins=0 RtrCapacity=1 DevCapacity=1 ProtoVer=2 StackProf=2 Depth=  0 UpdateId= 0 LQI=  0
...
```

## Energy scan
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

## CC2531 tools
### Network migration for coordinator upgrades
Follow the [installation instructions at the top of this page](#installation) to setup
Python and install the zigpy-znp package. Once you are inside of the virtualenv (if you
created one), [create a backup of your CC2531's network settings](#network-backup-beta)
and restore it to your new coordinator.

### Flash operations
The CC2531 serial bootloader can be interfaced with as long as the CC2531 was plugged in
no later than 60 seconds ago and no data has been written to the serial port. As long as
the green LED or the red LED is lit, you can enter the bootloader by either pressing the
button closest to the antenna (the LED will turn red), or running one of the following
commands:

#### Flash read
This reads only the firmware. NVRAM regions are not accessible from the serial bootloader.

```console
$ python -m zigpy_znp.tools.flash_read -o firmware.bin /dev/cu.usbmodem14101
```

#### Flash write
It is recommended you erase NVRAM after switching major firmware versions.

```console
$ python -m zigpy_znp.tools.flash_write -i firmware.bin /dev/cu.usbmodem14101
```

The firmware is checksummed before flashing so you will not be able to flash the wrong
file. Only `.bin` files (not `.hex`!) without the serial bootloader can be flashed.
