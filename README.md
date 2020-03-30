# zigpy-znp

[![Build Status](https://travis-ci.com/zha-ng/zigpy-znp.svg?branch=dev)](https://travis-ci.com/zha-ng/zigpy-znp)
[![Coverage Status](https://coveralls.io/repos/github/zha-ng/zigpy-znp/badge.svg?branch=dev)](https://coveralls.io/github/zha-ng/zigpy-znp?branch=dev)

[zigpy-znp](https://github.com/zha-ng/zigpy-zhp/) adds support for common [Texas Instruments Zigbee Network Processors](http://dev.ti.com/tirex/content/simplelink_zigbee_sdk_plugin_2_20_00_06/docs/zigbee_user_guide/html/zigbee/developing_zigbee_applications/znp_interface/znp_interface.html) to the [Zigpy](https://github.com/zigpy/) project, implementing a Zigbee stack.

## Compatible hardware

Hardware capable of running the TI Z-Stack versions 3 and above should all be supported (i.e. CC13x2 and CC26x2) but testing is done with the [TI LAUNCHXL-CC26X2R1](https://www.ti.com/tool/LAUNCHXL-CC26X2R1) (CC2652) running [Z-Stack 3.30.00.03 with @Koenkk's config tweaks](https://github.com/Koenkk/Z-Stack-firmware/tree/master/coordinator/Z-Stack_3.x.0/bin).
