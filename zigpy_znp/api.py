from __future__ import annotations

import os
import time
import typing
import asyncio
import logging
import itertools
import contextlib
import dataclasses
from collections import Counter, defaultdict

import zigpy.state
import async_timeout
import zigpy.zdo.types as zdo_t
import zigpy.exceptions
from zigpy.exceptions import NetworkNotFormed

import zigpy_znp
import zigpy_znp.const as const
import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.logger as log
import zigpy_znp.commands as c
from zigpy_znp import uart
from zigpy_znp.nvram import NVRAMHelper
from zigpy_znp.utils import (
    CatchAllResponse,
    BaseResponseListener,
    OneShotResponseListener,
    CallbackResponseListener,
)
from zigpy_znp.frames import GeneralFrame
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

if typing.TYPE_CHECKING:
    import typing_extensions

LOGGER = logging.getLogger(__name__)


# All of these are in seconds
STARTUP_TIMEOUT = 15
AFTER_BOOTLOADER_SKIP_BYTE_DELAY = 2.5
NETWORK_COMMISSIONING_TIMEOUT = 60
BOOTLOADER_PIN_TOGGLE_DELAY = 0.15
CONNECT_PING_TIMEOUT = 0.50
CONNECT_PROBE_TIMEOUT = 10

NVRAM_MIGRATION_ID = 1


class ZNP:
    def __init__(self, config: conf.ConfigType):
        self._uart = None
        self._app = None
        self._config = config

        self._listeners = defaultdict(list)
        self._sync_request_lock = asyncio.Lock()

        self.capabilities = None  # type: int
        self.version = None  # type: float

        self.nvram = NVRAMHelper(self)
        self.network_info: zigpy.state.NetworkInfo = None
        self.node_info: zigpy.state.NodeInfo = None

    def set_application(self, app):
        assert self._app is None
        self._app = app

    async def detect_zstack_version(self) -> float:
        """
        Feature detects the major version of Z-Stack running on the device.
        """

        # Z-Stack 1.2 does not have the AppConfig subsystem
        if not self.capabilities & t.MTCapabilities.APP_CNF:
            return 1.2

        try:
            # Only Z-Stack 3.30+ has the new NVRAM system
            await self.nvram.read(
                item_id=ExNvIds.TCLK_TABLE,
                sub_id=0x0000,
                item_type=t.Bytes,
            )
            return 3.30
        except KeyError:
            return 3.30
        except CommandNotRecognized:
            return 3.0

    async def _load_network_info(self, *, load_devices=False):
        """
        Loads low-level network information from NVRAM.
        Loading key data greatly increases the runtime so it not enabled by default.
        """

        from zigpy_znp.znp import security

        nib = await self.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)

        if nib.nwkLogicalChannel == 0 or not nib.nwkKeyLoaded:
            raise NetworkNotFormed()

        # This NVRAM item is the very first thing initialized in `zgInit`
        if (
            self.version >= 3.0
            and await self.nvram.osal_read(
                OsalNvIds.BDBNODEISONANETWORK, item_type=t.uint8_t
            )
            != 1
        ):
            raise NetworkNotFormed()

        ieee = await self.nvram.osal_read(OsalNvIds.EXTADDR, item_type=t.EUI64)
        logical_type = await self.nvram.osal_read(
            OsalNvIds.LOGICAL_TYPE, item_type=t.DeviceLogicalType
        )

        node_info = zigpy.state.NodeInfo(
            ieee=ieee,
            nwk=nib.nwkDevAddress,
            logical_type=zdo_t.LogicalType(logical_type),
        )

        key_desc = await self.nvram.osal_read(
            OsalNvIds.NWK_ACTIVE_KEY_INFO, item_type=t.NwkKeyDesc
        )

        nwk_frame_counter = await security.read_nwk_frame_counter(
            self, ext_pan_id=nib.extendedPANID
        )

        version = await self.request(c.SYS.Version.Req())

        network_info = zigpy.state.NetworkInfo(
            source=f"zigpy-znp@{zigpy_znp.__version__}",
            extended_pan_id=nib.extendedPANID,
            pan_id=nib.nwkPanId,
            nwk_update_id=nib.nwkUpdateId,
            channel=nib.nwkLogicalChannel,
            channel_mask=nib.channelList,
            security_level=nib.SecurityLevel,
            network_key=zigpy.state.Key(
                key=key_desc.Key,
                seq=key_desc.KeySeqNum,
                tx_counter=nwk_frame_counter,
                rx_counter=0,
                partner_ieee=node_info.ieee,
            ),
            tc_link_key=zigpy.state.Key(
                key=const.DEFAULT_TC_LINK_KEY,
                seq=0,
                tx_counter=0,
                rx_counter=0,
                partner_ieee=node_info.ieee,
            ),
            children=[],
            nwk_addresses={},
            key_table=[],
            stack_specific={},
            metadata={"zstack": version.as_dict()},
        )

        tclk_seed = None

        if self.version > 1.2:
            try:
                tclk_seed = await self.nvram.osal_read(
                    OsalNvIds.TCLK_SEED, item_type=t.KeyData
                )
            except ValueError:
                if self.version != 3.0:
                    raise

                # CC2531s that have been cross-flashed from 1.2 -> 3.0 can have NVRAM
                # entries from both. Ignore deserialization length errors for the
                # trailing data to allow them to be backed up.
                tclk_seed_value = await self.nvram.osal_read(
                    OsalNvIds.TCLK_SEED, item_type=t.Bytes
                )

                tclk_seed = self.nvram.deserialize(
                    tclk_seed_value, t.KeyData, allow_trailing=True
                )
                LOGGER.error(
                    "Your adapter's NVRAM is inconsistent! Perform a network backup,"
                    " re-flash its firmware, and restore the backup."
                )

            network_info.stack_specific = {
                "zstack": {
                    "tclk_seed": tclk_seed.serialize().hex(),
                }
            }

        # This takes a few seconds
        if load_devices:
            for dev in await security.read_devices(self, tclk_seed=tclk_seed):
                if dev.node_info.nwk == 0xFFFE:
                    dev = dev.replace(
                        node_info=dataclasses.replace(dev.node_info, nwk=None)
                    )

                if dev.is_child:
                    network_info.children.append(dev.node_info.ieee)

                if dev.node_info.nwk is not None:
                    network_info.nwk_addresses[dev.node_info.ieee] = dev.node_info.nwk

                if dev.key is not None:
                    network_info.key_table.append(dev.key)

        self.network_info = network_info
        self.node_info = node_info

    async def load_network_info(self, *, load_devices=False):
        """
        Loads low-level network information from NVRAM.
        Loading key data greatly increases the runtime so it not enabled by default.
        """

        try:
            await self._load_network_info(load_devices=load_devices)
        except KeyError as e:
            raise NetworkNotFormed() from e

    async def start_network(self):
        # Both startup sequences end with the same callback
        started_as_coordinator = self.wait_for_response(
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator)
        )

        # Handle the startup progress messages
        async with self.capture_responses(
            [
                c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartingAsCoordinator
                ),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    partial=True,
                    Status=c.app_config.BDBCommissioningStatus.InProgress,
                ),
            ]
        ):
            try:
                if self.version > 1.2:
                    # Z-Stack 3 uses the BDB subsystem
                    commissioning_rsp = await self.request_callback_rsp(
                        request=c.AppConfig.BDBStartCommissioning.Req(
                            Mode=c.app_config.BDBCommissioningMode.NwkFormation
                        ),
                        RspStatus=t.Status.SUCCESS,
                        callback=c.AppConfig.BDBCommissioningNotification.Callback(
                            partial=True,
                            RemainingModes=c.app_config.BDBCommissioningMode.NONE,
                        ),
                        timeout=NETWORK_COMMISSIONING_TIMEOUT,
                    )

                    # This is the correct startup sequence according to the forums,
                    # including the formation failure error.  Success is only returned
                    # when the network is first formed.
                    if commissioning_rsp.Status not in (
                        c.app_config.BDBCommissioningStatus.FormationFailure,
                        c.app_config.BDBCommissioningStatus.Success,
                    ):
                        raise zigpy.exceptions.FormationFailure(
                            f"Network formation failed: {commissioning_rsp}"
                        )
                else:
                    # In Z-Stack 1.2.2, StartupFromApp actually does what it says
                    rsp = await self.request(c.ZDO.StartupFromApp.Req(StartDelay=100))

                    if rsp.State not in (
                        c.zdo.StartupState.NewNetworkState,
                        c.zdo.StartupState.RestoredNetworkState,
                    ):
                        raise InvalidCommandResponse(
                            f"Invalid startup response state: {rsp.State}", rsp
                        )

                # Both versions still end with this callback
                async with async_timeout.timeout(STARTUP_TIMEOUT):
                    await started_as_coordinator
            except asyncio.TimeoutError as e:
                raise zigpy.exceptions.FormationFailure(
                    "Network formation refused: there is too much RF interference."
                    " Make sure your coordinator is on a USB 2.0 extension cable and"
                    " away from any sources of interference, like USB 3.0 ports, SSDs,"
                    " 2.4GHz routers, motherboards, etc."
                ) from e

        LOGGER.debug("Waiting for NIB to stabilize")

        # Even though the device says it is "ready" at this point, it takes a few more
        # seconds for `_NIB.nwkState` to switch from `NwkState.NWK_INIT`. There does
        # not appear to be any user-facing MT command to read this information.
        while True:
            try:
                nib = await self.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)
            except KeyError:
                pass
            else:
                LOGGER.debug("Current NIB is %s", nib)

                # Usually this works after the first attempt
                if nib.nwkLogicalChannel != 0 and nib.nwkPanId != 0xFFFE:
                    break

            await asyncio.sleep(1)

    async def reset_network_info(self):
        """
        Resets node network information and leaves the current network.
        """

        # Delete any existing NV items that store formation state
        await self.nvram.osal_delete(OsalNvIds.HAS_CONFIGURED_ZSTACK1)
        await self.nvram.osal_delete(OsalNvIds.HAS_CONFIGURED_ZSTACK3)
        await self.nvram.osal_delete(OsalNvIds.ZIGPY_ZNP_MIGRATION_ID)
        await self.nvram.osal_delete(OsalNvIds.BDBNODEISONANETWORK)

        # Instruct Z-Stack to reset everything on the next boot
        await self.nvram.osal_write(
            OsalNvIds.STARTUP_OPTION,
            t.StartupOptions.ClearState | t.StartupOptions.ClearConfig,
        )

        await self.reset()

    async def write_network_info(
        self,
        *,
        network_info: zigpy.state.NetworkInfo,
        node_info: zigpy.state.NodeInfo,
    ) -> None:
        """
        Writes network and node state to NVRAM.
        """
        from zigpy_znp.znp import security

        await self.reset_network_info()

        # Form a network with completely random settings to get NVRAM to a known state
        for item, value in {
            OsalNvIds.PANID: t.uint16_t(0xFFFF),
            OsalNvIds.APS_USE_EXT_PANID: t.EUI64(os.urandom(8)),
            OsalNvIds.PRECFGKEY: os.urandom(16),
            # XXX: Z2M requires this item to be False
            OsalNvIds.PRECFGKEYS_ENABLE: t.Bool(False),
            # Z-Stack will scan all of thse channels during formation
            OsalNvIds.CHANLIST: const.STARTUP_CHANNELS,
        }.items():
            await self.nvram.osal_write(item, value, create=True)

        # Z-Stack 3+ ignores `CHANLIST`
        if self.version > 1.2:
            await self.request(
                c.AppConfig.BDBSetChannel.Req(
                    IsPrimary=True, Channel=const.STARTUP_CHANNELS
                ),
                RspStatus=t.Status.SUCCESS,
            )
            await self.request(
                c.AppConfig.BDBSetChannel.Req(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.SUCCESS,
            )

        LOGGER.debug("Forming temporary network")
        await self.start_network()
        await self.reset()

        LOGGER.debug("Writing actual network settings")

        # Now that we have a formed network, update its state
        nib = await self.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)
        nib = nib.replace(
            nwkDevAddress=node_info.nwk,
            nwkPanId=network_info.pan_id,
            extendedPANID=network_info.extended_pan_id,
            nwkUpdateId=network_info.nwk_update_id,
            nwkLogicalChannel=network_info.channel,
            channelList=network_info.channel_mask,
            SecurityLevel=network_info.security_level,
            nwkManagerAddr=network_info.nwk_manager_id,
            nwkCoordAddress=0x0000,
        )

        key_info = t.NwkActiveKeyItems(
            Active=t.NwkKeyDesc(
                KeySeqNum=network_info.network_key.seq,
                Key=network_info.network_key.key,
            ),
            FrameCounter=network_info.network_key.tx_counter,
        )

        nvram = {
            OsalNvIds.NIB: nib,
            OsalNvIds.APS_USE_EXT_PANID: network_info.extended_pan_id,
            OsalNvIds.EXTENDED_PAN_ID: network_info.extended_pan_id,
            OsalNvIds.PRECFGKEY: key_info.Active.Key,
            OsalNvIds.CHANLIST: network_info.channel_mask,
            # If the EXTADDR entry is deleted, Z-Stack resets it to the hardware address
            OsalNvIds.EXTADDR: (
                None if node_info.ieee == t.EUI64.UNKNOWN else node_info.ieee
            ),
            OsalNvIds.LOGICAL_TYPE: t.DeviceLogicalType(node_info.logical_type),
            OsalNvIds.NWK_ACTIVE_KEY_INFO: key_info.Active,
            OsalNvIds.NWK_ALTERN_KEY_INFO: key_info.Active,
        }

        tclk_seed = None

        if self.version == 1.2:
            # TCLK_SEED is TCLK_TABLE_START in Z-Stack 1
            nvram[OsalNvIds.TCLK_SEED] = t.TCLinkKey(
                ExtAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),  # global
                Key=network_info.tc_link_key.key,
                TxFrameCounter=0,
                RxFrameCounter=0,
            )
        else:
            if network_info.tc_link_key.key != const.DEFAULT_TC_LINK_KEY:
                LOGGER.warning(
                    "TC link key is configured at build time in Z-Stack 3 and cannot be"
                    " changed at runtime: %s",
                    network_info.tc_link_key.key,
                )

            if (
                network_info.stack_specific is not None
                and network_info.stack_specific.get("zstack", {}).get("tclk_seed")
            ):
                tclk_seed = t.KeyData(
                    bytes.fromhex(network_info.stack_specific["zstack"]["tclk_seed"])
                )
            else:
                tclk_seed = t.KeyData(os.urandom(16))

            nvram[OsalNvIds.TCLK_SEED] = tclk_seed

        for key, value in nvram.items():
            if value is None:
                await self.nvram.osal_delete(key)
            else:
                await self.nvram.osal_write(key, value, create=True)

        await security.write_nwk_frame_counter(
            self,
            network_info.network_key.tx_counter,
            ext_pan_id=network_info.extended_pan_id,
        )

        devices = {}

        for ieee in network_info.children or []:
            devices[ieee] = security.StoredDevice(
                node_info=zigpy.state.NodeInfo(
                    nwk=network_info.nwk_addresses.get(ieee, 0xFFFE),
                    ieee=ieee,
                    logical_type=zdo_t.LogicalType.EndDevice,
                ),
                key=None,
                is_child=True,
            )

        for key in network_info.key_table or []:
            device = devices.get(key.partner_ieee)

            if device is None:
                device = security.StoredDevice(
                    node_info=zigpy.state.NodeInfo(
                        nwk=network_info.nwk_addresses.get(key.partner_ieee, 0xFFFE),
                        ieee=key.partner_ieee,
                        logical_type=None,
                    ),
                    key=None,
                    is_child=False,
                )

            devices[key.partner_ieee] = device.replace(key=key)

        LOGGER.debug("Writing children and keys")

        # Recompute the TCLK if necessary
        if self.version > 1.2:
            optimal_tclk_seed = security.find_optimal_tclk_seed(
                devices.values(), tclk_seed
            )

            if tclk_seed != optimal_tclk_seed:
                LOGGER.warning(
                    "Provided TCLK seed %s is not optimal, using %s instead.",
                    tclk_seed,
                    optimal_tclk_seed,
                )

                await self.nvram.osal_write(OsalNvIds.TCLK_SEED, optimal_tclk_seed)
                tclk_seed = optimal_tclk_seed

        await security.write_devices(
            znp=self,
            devices=list(devices.values()),
            tclk_seed=tclk_seed,
            counter_increment=0,
        )

        # Prevent an unnecessary NVRAM migration from running
        await self.nvram.osal_write(
            OsalNvIds.ZIGPY_ZNP_MIGRATION_ID, t.uint8_t(NVRAM_MIGRATION_ID), create=True
        )

        if self.version == 1.2:
            await self.nvram.osal_write(
                OsalNvIds.HAS_CONFIGURED_ZSTACK1,
                const.ZSTACK_CONFIGURE_SUCCESS,
                create=True,
            )
        else:
            await self.nvram.osal_write(
                OsalNvIds.HAS_CONFIGURED_ZSTACK3,
                const.ZSTACK_CONFIGURE_SUCCESS,
                create=True,
            )

        # Reset after writing network settings to allow Z-Stack to recreate NVRAM items
        # that were intentionally deleted.
        await self.reset()

        LOGGER.debug("Done!")

    async def migrate_nvram(self) -> bool:
        """
        Migrates NVRAM entries using the `ZIGPY_ZNP_MIGRATION_ID` NVRAM item.
        Returns `True` if a migration was performed, `False` otherwise.
        """

        from zigpy_znp.znp import security

        try:
            migration_id = await self.nvram.osal_read(
                OsalNvIds.ZIGPY_ZNP_MIGRATION_ID, item_type=t.uint8_t
            )
        except KeyError:
            migration_id = 0

        initial_migration_id = migration_id

        # Migration 1: empty `ADDRMGR` entries are version-dependent and were improperly
        #              written for CC253x devices.
        #
        #              This migration is stateless and can safely be run more than once:
        #              the only downside is that startup times increase by 10s on newer
        #              coordinators, which is why the migration ID is persisted.
        if migration_id < 1:
            try:
                entries = await security.read_addr_manager_entries(self)
            except KeyError:
                pass
            else:
                fixed_entries = []

                for entry in entries:
                    if entry.extAddr != t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"):
                        fixed_entries.append(entry)
                    elif self.version == 3.30:
                        fixed_entries.append(const.EMPTY_ADDR_MGR_ENTRY_ZSTACK3)
                    else:
                        fixed_entries.append(const.EMPTY_ADDR_MGR_ENTRY_ZSTACK1)

                if entries != fixed_entries:
                    LOGGER.warning(
                        "Repairing %d invalid empty address manager entries (total %d)",
                        sum(i != j for i, j in zip(entries, fixed_entries)),
                        len(entries),
                    )
                    await security.write_addr_manager_entries(self, fixed_entries)

            migration_id = 1

        if initial_migration_id == migration_id:
            return False

        await self.nvram.osal_write(
            OsalNvIds.ZIGPY_ZNP_MIGRATION_ID, t.uint8_t(migration_id), create=True
        )
        await self.reset()

        return True

    async def reset(self, *, wait_for_reset: bool = True) -> None:
        """
        Performs a soft reset within Z-Stack.
        A hard reset resets the serial port, causing the device to disconnect.
        """

        if wait_for_reset:
            await self.request_callback_rsp(
                request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
                callback=c.SYS.ResetInd.Callback(partial=True),
            )
        else:
            await self.request(c.SYS.ResetReq.Req(Type=t.ResetType.Soft))

    @property
    def _port_path(self) -> str:
        return self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH]

    @property
    def _znp_config(self) -> conf.ConfigType:
        return self._config[conf.CONF_ZNP_CONFIG]

    async def _skip_bootloader(self) -> c.SYS.Ping.Rsp:
        """
        Attempt to skip the bootloader and return the ping response.
        """

        async def ping_task():
            LOGGER.debug("Toggling RTS/DTR pins to skip bootloader or reset chip")

            # The default sequence is DTR=false and RTS toggling false/true/false
            for dtr, rts in zip(
                self._znp_config[conf.CONF_CONNECT_DTR_STATES],
                self._znp_config[conf.CONF_CONNECT_RTS_STATES],
            ):
                self._uart.set_dtr_rts(dtr=dtr, rts=rts)
                await asyncio.sleep(BOOTLOADER_PIN_TOGGLE_DELAY)

            # First, just try pinging
            try:
                async with async_timeout.timeout(CONNECT_PING_TIMEOUT):
                    return await self.request(c.SYS.Ping.Req())
            except asyncio.TimeoutError:
                pass

            # If that doesn't work, send the bootloader skip bytes and try again.
            # Sending a bunch at a time fixes UART issues when the radio was previously
            # probed with another library at a different baudrate.
            LOGGER.debug("Sending CC253x bootloader skip bytes")
            self._uart.write(256 * bytes([c.ubl.BootloaderRunMode.FORCE_RUN]))

            await asyncio.sleep(AFTER_BOOTLOADER_SKIP_BYTE_DELAY)

            # At this point we have nothing left to try
            while True:
                try:
                    async with async_timeout.timeout(2 * CONNECT_PING_TIMEOUT):
                        return await self.request(c.SYS.Ping.Req())
                except asyncio.TimeoutError:
                    pass

        async with self.capture_responses([CatchAllResponse()]) as responses:
            ping_task = asyncio.create_task(ping_task())

            try:
                async with async_timeout.timeout(CONNECT_PROBE_TIMEOUT):
                    result = await responses.get()
            except Exception:
                ping_task.cancel()
                raise
            else:
                LOGGER.debug("Radio is alive: %s", result)

            # Give the ping task a little bit extra time to finish. Radios often queue
            # requests so when the reset indication is received, they will all be
            # immediately answered
            if not ping_task.done():
                LOGGER.debug("Giving ping task %0.2fs to finish", CONNECT_PING_TIMEOUT)

                try:
                    async with async_timeout.timeout(CONNECT_PING_TIMEOUT):
                        result = await ping_task  # type:ignore[misc]
                except asyncio.TimeoutError:
                    ping_task.cancel()

        if isinstance(result, c.SYS.Ping.Rsp):
            return result

        return await self.request(c.SYS.Ping.Req())

    async def connect(self, *, test_port=True) -> None:
        """
        Connects to the device specified by the "device" section of the config dict.

        The `test_port` kwarg allows port testing to be disabled, mainly to get into the
        bootloader.
        """

        # So we cannot connect twice
        assert self._uart is None

        try:
            self._uart = await uart.connect(self._config[conf.CONF_DEVICE], self)

            # To allow the ZNP interface to be used for bootloader commands, we have to
            # prevent any data from being sent
            if test_port:
                # The reset indication callback is sent when some sticks start up
                self.capabilities = (await self._skip_bootloader()).Capabilities

                # We need to know how structs are packed to deserialize frames correctly
                await self.nvram.determine_alignment()
                self.version = await self.detect_zstack_version()

                LOGGER.debug("Detected Z-Stack %s", self.version)
        except (Exception, asyncio.CancelledError):
            LOGGER.debug("Connection to %s failed, cleaning up", self._port_path)
            self.close()
            raise

        LOGGER.debug("Connected to %s", self._uart.url)

    def connection_made(self) -> None:
        """
        Called by the UART object when a connection has been made.
        """

    def connection_lost(self, exc) -> None:
        """
        Called by the UART object to indicate that the port was closed. Propagates up
        to the `ControllerApplication` that owns this ZNP instance.
        """

        LOGGER.debug("We were disconnected from %s: %s", self._port_path, exc)

        if self._app is not None:
            self._app.connection_lost(exc)

    def close(self) -> None:
        """
        Cleans up resources, namely the listener queues.

        Calling this will reset ZNP to the same internal state as a fresh ZNP instance.
        """

        self._app = None

        for _header, listeners in self._listeners.items():
            for listener in listeners:
                listener.cancel()

        self._listeners.clear()
        self.version = None
        self.capabilities = None

        if self._uart is not None:
            self._uart.close()
            self._uart = None

    def remove_listener(self, listener: BaseResponseListener) -> None:
        """
        Unbinds a listener from ZNP.

        Used by `wait_for_responses` to remove listeners for completed futures,
        regardless of their completion reason.
        """

        # If ZNP is closed while it's still running, `self._listeners` will be empty.
        if not self._listeners:
            return

        LOGGER.log(log.TRACE, "Removing listener %s", listener)

        for header in listener.matching_headers():
            try:
                self._listeners[header].remove(listener)
            except ValueError:
                pass

            if not self._listeners[header]:
                LOGGER.log(
                    log.TRACE, "Cleaning up empty listener list for header %s", header
                )
                del self._listeners[header]

        counts = Counter()

        for listener in itertools.chain.from_iterable(self._listeners.values()):
            counts[type(listener)] += 1

        LOGGER.log(
            log.TRACE,
            "There are %d callbacks and %d one-shot listeners remaining",
            counts[CallbackResponseListener],
            counts[OneShotResponseListener],
        )

    def frame_received(self, frame: GeneralFrame) -> bool | None:
        """
        Called when a frame has been received. Returns whether or not the frame was
        handled by any listener.

        XXX: Can be called multiple times in a single event loop step!
        """

        if frame.header not in c.COMMANDS_BY_ID:
            LOGGER.error("Received an unknown frame: %s", frame)
            return False

        command_cls = c.COMMANDS_BY_ID[frame.header]

        try:
            command = command_cls.from_frame(frame, align=self.nvram.align_structs)
        except ValueError:
            # Some commands can be received corrupted. They are not useful:
            # https://github.com/home-assistant/core/issues/50005
            if command_cls == c.ZDO.ParentAnnceRsp.Callback:
                LOGGER.warning("Failed to parse broken %s as %s", frame, command_cls)
                return False

            raise

        LOGGER.debug("Received command: %s", command)

        matched = False
        one_shot_matched = False

        for listener in (
            self._listeners[command.header] + self._listeners[CatchAllResponse.header]
        ):
            # XXX: A single response should *not* resolve multiple one-shot listeners!
            #      `future.add_done_callback` doesn't remove our listeners synchronously
            #      so doesn't prevent this from happening.
            if one_shot_matched and isinstance(listener, OneShotResponseListener):
                continue

            if not listener.resolve(command):
                LOGGER.log(log.TRACE, "%s does not match %s", command, listener)
                continue

            matched = True
            LOGGER.log(log.TRACE, "%s matches %s", command, listener)

            if isinstance(listener, OneShotResponseListener):
                one_shot_matched = True

        if not matched:
            self._unhandled_command(command)

        return matched

    def _unhandled_command(self, command: t.CommandBase):
        """
        Called when a command that is not handled by any listener is received.
        """

        LOGGER.debug("Command was not handled")

    @contextlib.asynccontextmanager
    async def capture_responses(self, responses):
        """
        Captures all matched responses in a queue within the context manager.
        """

        queue = asyncio.Queue()
        listener = self.callback_for_responses(responses, callback=queue.put_nowait)

        try:
            yield queue
        finally:
            self.remove_listener(listener)

    def callback_for_responses(self, responses, callback) -> CallbackResponseListener:
        """
        Creates a callback listener that matches any of the provided responses.

        Only exists for consistency with `wait_for_responses`, since callbacks can be
        executed more than once.
        """

        listener = CallbackResponseListener(responses, callback=callback)

        LOGGER.log(log.TRACE, "Creating callback %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].append(listener)

        return listener

    def callback_for_response(
        self, response: t.CommandBase, callback
    ) -> CallbackResponseListener:
        """
        Creates a callback listener for a single response.
        """

        return self.callback_for_responses([response], callback)

    @typing.overload
    def wait_for_responses(
        self, responses, *, context: typing_extensions.Literal[False] = ...
    ) -> asyncio.Future:
        ...

    @typing.overload
    def wait_for_responses(
        self, responses, *, context: typing_extensions.Literal[True]
    ) -> tuple[asyncio.Future, OneShotResponseListener]:
        ...

    def wait_for_responses(
        self, responses, *, context: bool = False
    ) -> asyncio.Future | tuple[asyncio.Future, OneShotResponseListener]:
        """
        Creates a one-shot listener that matches any *one* of the given responses.
        """

        listener = OneShotResponseListener(responses)

        LOGGER.log(log.TRACE, "Creating one-shot listener %s", listener)

        for header in listener.matching_headers():
            self._listeners[header].append(listener)

        # Remove the listener when the future is done, not only when it gets a result
        listener.future.add_done_callback(lambda _: self.remove_listener(listener))

        if context:
            return listener.future, listener
        else:
            return listener.future

    def wait_for_response(self, response: t.CommandBase) -> asyncio.Future:
        """
        Creates a one-shot listener for a single response.
        """

        return self.wait_for_responses([response])

    async def request(
        self, request: t.CommandBase, timeout: int | None = None, **response_params
    ) -> t.CommandBase | None:
        """
        Sends a SREQ/AREQ request and returns its SRSP (only for SREQ), failing if any
        of the SRSP's parameters don't match `response_params`.
        """

        # Common mistake is to do `znp.request(c.SYS.Ping())`
        if type(request) is not request.Req:
            raise ValueError(f"Cannot send a command that isn't a request: {request!r}")

        # Construct a partial response out of the `Rsp*` kwargs if one is provided
        if request.Rsp:
            renamed_response_params = {}

            for param, value in response_params.items():
                if not param.startswith("Rsp"):
                    raise KeyError(
                        f"All response params must start with 'Rsp': {param!r}"
                    )

                renamed_response_params[param.replace("Rsp", "", 1)] = value

            # Construct our response before we send the request so that we fail early
            partial_response = request.Rsp(partial=True, **renamed_response_params)
        elif response_params:
            raise ValueError(
                f"Command has no response so response_params={response_params} "
                f"will have no effect"
            )

        frame = request.to_frame(align=self.nvram.align_structs)

        # We should only be sending one SREQ at a time, according to the spec
        async with self._sync_request_lock:
            LOGGER.debug("Sending request: %s", request)

            # If our request has no response, we cannot wait for one
            if not request.Rsp:
                LOGGER.debug("Request has no response, not waiting for one.")
                self._uart.send(frame)
                return None

            # We need to create the response listener before we send the request
            response_future = self.wait_for_responses(
                [
                    request.Rsp(partial=True),
                    c.RPCError.CommandNotRecognized.Rsp(
                        partial=True, RequestHeader=request.header
                    ),
                ]
            )

            self._uart.send(frame)

            # We should get a SRSP in a reasonable amount of time
            async with async_timeout.timeout(
                timeout or self._znp_config[conf.CONF_SREQ_TIMEOUT]
            ):
                # We lock until either a sync response is seen or an error occurs
                response = await response_future

        if isinstance(response, c.RPCError.CommandNotRecognized.Rsp):
            raise CommandNotRecognized(
                f"Fatal request error {response} in response to {request}"
            )

        # If the sync response we got is not what we wanted, this is an error
        if not partial_response.matches(response):
            raise InvalidCommandResponse(
                f"Expected SRSP response {partial_response}, got {response}", response
            )

        return response

    async def request_callback_rsp(
        self, *, request, callback, timeout=None, background=False, **response_params
    ):
        """
        Sends an SREQ, gets its SRSP confirmation, and waits for its real AREQ response.
        A bug-free version of:

            req_rsp = await req
            callback_rsp = await req_callback

        This is necessary because the SRSP and the AREQ may arrive in the same "chunk"
        from the UART and be handled in the same event loop step by ZNP.
        """

        # Every request should have a timeout to prevent deadlocks
        if timeout is None:
            timeout = self._znp_config[conf.CONF_ARSP_TIMEOUT]

        callback_rsp, listener = self.wait_for_responses([callback], context=True)

        # Typical request/response/callbacks are not backgrounded
        if not background:
            try:
                async with async_timeout.timeout(timeout):
                    await self.request(request, timeout=timeout, **response_params)

                    return await callback_rsp
            finally:
                self.remove_listener(listener)

        # Backgrounded callback handlers need to respect the provided timeout
        start_time = time.monotonic()

        try:
            async with async_timeout.timeout(timeout):
                request_rsp = await self.request(request, **response_params)
        except Exception:
            # If the SREQ/SRSP pair fails, we must cancel the AREQ listener
            self.remove_listener(listener)
            raise

        # If it succeeds, create a background task to receive the AREQ but take into
        # account the time it took to start the SREQ to ensure we do not grossly exceed
        # the timeout
        async def callback_catcher(timeout):
            try:
                async with async_timeout.timeout(timeout):
                    await callback_rsp
            finally:
                self.remove_listener(listener)

        callback_timeout = max(0, timeout - (time.monotonic() - start_time))
        asyncio.create_task(callback_catcher(callback_timeout))

        return request_rsp
