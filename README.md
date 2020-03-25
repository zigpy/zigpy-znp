# zigpy-ZNP

[![Build Status](https://travis-ci.com/puddly/zigpy-znp.svg?branch=dev)](https://travis-ci.com/puddly/zigpy-znp)
[![Coverage Status](https://coveralls.io/repos/github/puddly/casserole/badge.svg?branch=dev)](https://coveralls.io/github/puddly/casserole?branch=dev)

[zigpy-znp](https://github.com/puddly/zigpy-zhp/) adds support for common [Texas Instruments Zigbee Network Processors](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/developing_zigbee_applications/znp_interface/znp_interface.html) to the [Zigpy](https://github.com/zigpy/) project, implementing a Zigbee stack.

## Compatible hardware

Hardware capable of running the TI Z-Stack versions 3 and above should all be supported but testing is done with the [TI LAUNCHXL-CC26X2R1](https://www.ti.com/tool/LAUNCHXL-CC26X2R1) (CC2652) running [Z-Stack 3.30.00.03 with @Koenkk's config tweaks](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/Z-Stack_3.x.0/bin).
