# Building Z-Stack

All of the tools are cross-platform but these instructions have only been tested on Windows.

## Software

Download the following installers. The total installed size is going to be 7GB:

 - **SimpleLink SDK TI IDE** (1GB): https://www.ti.com/tool/download/SIMPLELINK-CC13X2-26X2-SDK
 - **Simplelink CC13X2 26X2 SDK** (600MB): https://www.ti.com/tool/download/SIMPLELINK-CC13X2-26X2-SDK
 - **UniFlash** (125MB): https://www.ti.com/tool/download/UNIFLASH

## Installation
 
 1. Install UniFlash.
 2. Install the IDE. This will take 10 minutes. The progress bar will be stuck at 99% for about 9 of those 10 minutes. You might have to reboot after.
    - **WARNING: make sure you install it to a path without spaces, like `C:\TI`**. The build tools break if there are paths with spaces.
    - Perform a "Custom Installation" and select only the **SimipleLink CC13xx and CC26xx Wireless MCUs**.
 3. Install the SDK to the same path. This will take about 15 minutes.

## Setting up a project

 4. On startup you will have to pick a workspace directory. Don't pick one with spaces or non-ASCII characters in the path name.
 5. In the <kbd>File</kbd> > <kbd>Import...</kbd> dialog, select **Code Compositor Studio > CCS Projects** and click <kbd>Next</kbd>.
 6. In the **Select search-directory:** file chooser, navigate to `C:\TI\simplelink_cc13x2_26x2_sdk_4_10_00_78\examples\rtos`.
 7. Near the bottom of the **Discovered projects** list, select `znp_CC26X2R1_LAUNCHXL_tirtos_ccs` and click <kbd>Finish</kbd>.

## Tweak network settings (optional)

 8. Click on `znp.syscfg` in the project tree. Most settings can be configured at runtime so the only interesting ones change table sizes and timeouts.

## Build the project

 9. Right click on the project name and select <kbd>Team</kbd> > <kbd>Apply Patch</kbd> near the bottom. Apply the patch for your specific board.
 10. Right click on the project name again and select <kbd>Build Project</kbd> to compile the firmware.

     - You may receive an error such at this:
       ```
       subdir_rules.mk:24: recipe for target 'build-1699726977-inproc' failed
             0 [main] sh.exe" 3132 sync_with_child: child 3564(0x220) died before initialization with status code 0xC0000142
            12 [main] sh.exe" 3132 sync_with_child: *** child state waiting for longjmp
       C:/Users/Username/AppData/Local/Temp/make13332-3.sh: fork: Resource temporarily unavailable
       gmake[1]: *** [makefile:60: rom_sysbios.obj] Error 128
       ```
     
       If so, you probably have [another `make.exe` in your `PATH`](https://e2e.ti.com/support/tools/ccs/f/81/p/527017/1917891#1917891). For me it was WinAVR. There's probably a way to fix Eclipse but uninstalling WinAVR was easier.

## Flashing the firmware

 11. Under the project tree there there will be a **Binaries** subtree. Right click on the generated binary and select <kbd>Show In</kbd> > <kbd>System Explorer</kbd>.
 12. Find the file with the same name as the highlighted binary *but with the `.hex` suffix*. It will be about 400KB.
 13. Launch UniFlash. It will auto-detect your board and 