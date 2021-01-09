import os
import time
import typing
import asyncio
import logging
import warnings
import itertools
import contextlib

import zigpy.zdo
import zigpy.util
import zigpy.types
import zigpy.config
import zigpy.device
import async_timeout
import zigpy.endpoint
import zigpy.profiles
import zigpy.zcl.foundation
from zigpy.zcl import clusters
from zigpy.types import ExtendedPanId, deserialize as list_deserialize
from zigpy.zdo.types import CLUSTERS as ZDO_CLUSTERS, ZDOCmd, ZDOHeader, MultiAddress
from zigpy.exceptions import DeliveryError

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.znp.nib import NIB, CC2531NIB, parse_nib
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse
from zigpy_znp.types.nvids import OsalNvIds
from zigpy_znp.zigbee.zdo_converters import ZDO_CONVERTERS

with warnings.catch_warnings():
    warnings.filterwarnings(
        action="ignore",
        module="aiohttp",
        message='"@coroutine" decorator is deprecated',
        category=DeprecationWarning,
    )
    import zigpy.application


ZDO_ENDPOINT = 0
PROBE_TIMEOUT = 5  # seconds
STARTUP_TIMEOUT = 5  # seconds
ZDO_REQUEST_TIMEOUT = 15  # seconds
DATA_CONFIRM_TIMEOUT = 8  # seconds
DEVICE_JOIN_MAX_DELAY = 2  # seconds
NETWORK_COMMISSIONING_TIMEOUT = 30  # seconds

REQUEST_MAX_RETRIES = 5
REQUEST_ERROR_RETRY_DELAY = 0.5  # second

# Errors that go away on their own after waiting for a bit
REQUEST_TRANSIENT_ERRORS = {
    t.Status.BUFFER_FULL,
    t.Status.MAC_CHANNEL_ACCESS_FAILURE,
    t.Status.MAC_NO_RESOURCES,
    t.Status.MEM_ERROR,
    t.Status.NWK_TABLE_FULL,
}

REQUEST_ROUTING_ERRORS = {
    t.Status.APS_NO_ACK,
    t.Status.NWK_NO_ROUTE,
    t.Status.MAC_NO_ACK,
    t.Status.MAC_TRANSACTION_EXPIRED,
}

REQUEST_RETRYABLE_ERRORS = REQUEST_TRANSIENT_ERRORS | REQUEST_ROUTING_ERRORS

DEFAULT_TC_LINK_KEY = t.TCLinkKey(
    ExtAddr=t.EUI64.convert("FF:FF:FF:FF:FF:FF:FF:FF"),  # global
    Key=t.KeyData(b"ZigBeeAlliance09"),
    TxFrameCounter=0,
    RxFrameCounter=0,
)
ZSTACK_CONFIGURE_SUCCESS = b"\x55"

LOGGER = logging.getLogger(__name__)


class ZNPCoordinator(zigpy.device.Device):
    """
    Coordinator zigpy device that keeps track of our endpoints and clusters.
    """

    @property
    def manufacturer(self):
        return "Texas Instruments"

    @property
    def model(self):
        if self.application._znp.version == 1.2:
            model = "CC2531"
            version = "Home 1.2"
        elif self.application._znp.version == 3.0:
            model = "CC2531"
            version = "3.0.1/3.0.2"
        else:
            model = "CC13X2/CC26X2"
            version = "3.30.00/3.40.00/4.10.00"

        return f"{model}, Z-Stack {version}"


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA
    SCHEMA_DEVICE = conf.SCHEMA_DEVICE

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=conf.CONFIG_SCHEMA(config))

        self._znp: typing.Optional[ZNP] = None

        # It's simpler to work with Task objects if they're never actually None
        self._reconnect_task = asyncio.Future()
        self._reconnect_task.cancel()

        self._nib = NIB()
        self._network_key = None
        self._network_key_seq = None
        self._concurrent_requests_semaphore = None
        self._currently_waiting_requests = 0
        self._route_discovery_futures = {}
        self._join_announce_tasks = {}

    ##################################################################
    # Implementation of the core zigpy ControllerApplication methods #
    ##################################################################

    @property
    def network_key(self) -> typing.Optional[t.KeyData]:
        # This is not a standard Zigpy property
        return self._network_key

    @property
    def network_key_seq(self) -> typing.Optional[t.uint8_t]:
        # This is not a standard Zigpy property
        return self._network_key_seq

    @classmethod
    async def probe(cls, device_config: conf.ConfigType) -> bool:
        """
        Checks whether the device represented by `device_config` is a valid ZNP radio.
        Doesn't throw any errors.
        """

        znp = ZNP(conf.CONFIG_SCHEMA({conf.CONF_DEVICE: device_config}))
        LOGGER.debug("Probing %s", znp._port_path)

        try:
            async with async_timeout.timeout(PROBE_TIMEOUT):
                await znp.connect()

            result = True
        except Exception as e:
            result = False
            LOGGER.warning(
                "Failed to probe ZNP radio with config %s", device_config, exc_info=e
            )

        znp.close()

        return result

    async def shutdown(self):
        """
        Gracefully shuts down the application and cleans up all resources.
        This method calls ZNP.close, which calls UART.close, etc.
        """

        self._reconnect_task.cancel()

        for f in self._route_discovery_futures.values():
            f.cancel()

        self._route_discovery_futures.clear()

        if self._znp is not None:
            self._znp.close()
            self._znp = None

    async def startup(self, auto_form=False):
        """
        Performs application startup.

        This entails creating the ZNP object, connecting to the radio, potentially
        forming a network, and configuring our settings.
        """

        try:
            return await self._startup(auto_form=auto_form)
        except Exception:
            await self.shutdown()
            raise

    async def _startup(self, auto_form=False):
        assert self._znp is None

        znp = ZNP(self.config)
        await znp.connect()

        # We only assign `self._znp` after it has successfully connected
        self._znp = znp
        self._znp.set_application(self)

        self._bind_callbacks()

        # Next, read out the NVRAM item that Zigbee2MQTT writes when it has configured
        # a device to make sure that our network settings will not be reset.
        if self._znp.version == 1.2:
            configured_nv_item = OsalNvIds.HAS_CONFIGURED_ZSTACK1
        else:
            configured_nv_item = OsalNvIds.HAS_CONFIGURED_ZSTACK3

        try:
            configured_value = await self._znp.nvram.osal_read(configured_nv_item)
            is_configured = configured_value == ZSTACK_CONFIGURE_SUCCESS
        except KeyError:
            is_configured = False

        if not is_configured:
            if not auto_form:
                raise RuntimeError("Cannot start application, network is not formed")

            LOGGER.info("ZNP is not configured, forming a new network")

            # Network formation requires multiple resets so it will write the NVRAM
            # settings itself
            await self.form_network()
        else:
            # Issue a reset first to make sure we aren't permitting joins
            await self._reset()

            LOGGER.info("ZNP is already configured, not forming a new network")
            await self._write_stack_settings(reset_if_changed=True)

        # At this point the device state should the same, regardless of whether we just
        # formed a new network or are restoring one
        if self.znp_config[conf.CONF_TX_POWER] is not None:
            dbm = self.znp_config[conf.CONF_TX_POWER]

            await self._znp.request(
                c.SYS.SetTxPower.Req(TXPower=dbm), RspStatus=t.Status.SUCCESS
            )

        # Both versions of Z-Stack use this callback
        started_as_coordinator = self._znp.wait_for_response(
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator)
        )

        # The AUTOSTART startup NV item doesn't do anything.
        if self._znp.version == 1.2:
            # Z-Stack Home 1.2 has a simple startup sequence
            await self._znp.request(
                c.ZDO.StartupFromApp.Req(StartDelay=100),
                RspState=c.zdo.StartupState.RestoredNetworkState,
            )
        else:
            # Z-Stack 3 uses the BDB subsystem
            bdb_commissioning_done = self._znp.wait_for_response(
                c.AppConfig.BDBCommissioningNotification.Callback(
                    partial=True, RemainingModes=c.app_config.BDBCommissioningMode.NONE
                )
            )

            # According to the forums, this is the correct startup sequence, including
            # the formation failure error
            await self._znp.request_callback_rsp(
                request=c.AppConfig.BDBStartCommissioning.Req(
                    Mode=c.app_config.BDBCommissioningMode.NwkFormation
                ),
                RspStatus=t.Status.SUCCESS,
                callback=c.AppConfig.BDBCommissioningNotification.Callback(
                    partial=True,
                    Status=c.app_config.BDBCommissioningStatus.NetworkRestored,
                ),
            )

            await bdb_commissioning_done

        # The startup sequence should not take forever
        async with async_timeout.timeout(STARTUP_TIMEOUT):
            await started_as_coordinator

        # The CC2531 running Z-Stack Home 1.2 overrides the LED setting if it is changed
        # before the coordinator has started.
        if self.znp_config[conf.CONF_LED_MODE] is not None:
            await self._set_led_mode(led=0xFF, mode=self.znp_config[conf.CONF_LED_MODE])

        device_info = await self._znp.request(
            c.Util.GetDeviceInfo.Req(), RspStatus=t.Status.SUCCESS
        )

        self._ieee = device_info.IEEE
        self._nwk = 0x0000

        # Add the coordinator as a zigpy device. We do this up here because
        # `self._register_endpoint()` adds endpoints to this device object.
        self.devices[self.ieee] = ZNPCoordinator(self, self.ieee, self.nwk)

        # Give our Zigpy device a valid node descriptor
        node_descriptor_rsp = await self._znp.request_callback_rsp(
            request=c.ZDO.NodeDescReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.NodeDescRsp.Callback(Src=0x0000, NWK=0x0000, partial=True),
        )
        self.zigpy_device.node_desc = node_descriptor_rsp.NodeDescriptor

        # Register our endpoints
        await self._register_endpoint(
            endpoint=1,
            profile_id=zigpy.profiles.zha.PROFILE_ID,
            device_id=zigpy.profiles.zha.DeviceType.IAS_CONTROL,
            input_clusters=[clusters.general.Ota.cluster_id],
            output_clusters=[
                clusters.security.IasZone.cluster_id,
                clusters.security.IasWd.cluster_id,
            ],
        )

        await self._register_endpoint(
            endpoint=2,
            profile_id=zigpy.profiles.zll.PROFILE_ID,
            device_id=zigpy.profiles.zll.DeviceType.CONTROLLER,
        )

        await self._load_device_info()

        # Now that we know what device we are, set the max concurrent requests
        if self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS] == "auto":
            max_concurrent_requests = 2 if isinstance(self._nib, CC2531NIB) else 16
        else:
            max_concurrent_requests = self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS]

        self._concurrent_requests_semaphore = asyncio.Semaphore(max_concurrent_requests)

        LOGGER.info(
            "Currently on channel %d. Limiting concurrent requests to %d",
            self.channel,
            max_concurrent_requests,
        )

        # XXX: The CC2531 running Z-Stack Home 1.2 permanently permits joins on startup
        # unless they are explicitly disabled. We can't fix this but we can disable them
        # as early as possible to shrink the window of opportunity for unwanted joins.
        await self.permit(time_s=0)

    async def update_network_channel(self, channel: t.uint8_t):
        """
        Changes the network channel, increments the beacon update ID, and waits until
        the changes take effect.

        Does nothing if the new channel is the same as the old.
        """

        if self.channel == channel:
            return

        await self._znp.request(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=t.Channels.from_channel_list([channel]),
                ScanDuration=0xFE,  # switch channels
                ScanCount=0,
                NwkManagerAddr=0x0000,
            ),
            RspStatus=t.Status.SUCCESS,
        )

        # The above command takes a few seconds to work
        while self.channel != channel:
            await self._load_device_info()
            await asyncio.sleep(1)

    async def form_network(self):
        """
        Clears the current config and forms a new network with a random network key,
        PAN ID, and extended PAN ID.
        """

        # First, make the settings consistent and randomly generate missing values
        channel = self.config[conf.CONF_NWK][conf.CONF_NWK_CHANNEL]
        channels = self.config[conf.CONF_NWK][conf.CONF_NWK_CHANNELS]
        pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_PAN_ID]
        extended_pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_EXTENDED_PAN_ID]
        network_key = self.config[conf.CONF_NWK][conf.CONF_NWK_KEY]

        if pan_id is None:
            # Let Z-Stack pick one at random, hopefully not conflicting with others
            pan_id = t.uint16_t(0xFFFF)

        if extended_pan_id is None:
            # It's not documented whether or not Z-Stack will pick this randomly as well
            # if a value of 00:00:00:00:00:00:00:00 is provided but the chances of a
            # collision using `os.urandom` are astronomically small
            extended_pan_id = ExtendedPanId(os.urandom(8))

        if network_key is None:
            network_key = t.KeyData(os.urandom(16))

        # Override `channels` with a single channel if one is explicitly set
        if channel is not None:
            channels = t.Channels.from_channel_list([channel])

        # Delete any existing HAS_CONFIGURED_ZSTACK* NV items. One (or both) may fail.
        await self._znp.nvram.osal_delete(OsalNvIds.HAS_CONFIGURED_ZSTACK1)
        await self._znp.nvram.osal_delete(OsalNvIds.HAS_CONFIGURED_ZSTACK3)

        # Instruct Z-Stack to reset everything on the next boot
        await self._znp.nvram.osal_write(
            OsalNvIds.STARTUP_OPTION,
            t.StartupOptions.ClearState | t.StartupOptions.ClearConfig,
        )

        # And reset to clear everything
        await self._reset()

        # Now that we've cleared everything, write back our Z-Stack settings
        LOGGER.debug("Updating network settings")

        await self._write_stack_settings(reset_if_changed=False)
        await self._znp.nvram.osal_write(OsalNvIds.PANID, pan_id, create=True)
        await self._znp.nvram.osal_write(
            OsalNvIds.APS_USE_EXT_PANID, extended_pan_id, create=True
        )
        await self._znp.nvram.osal_write(OsalNvIds.PRECFGKEY, network_key, create=True)
        await self._znp.nvram.osal_write(
            OsalNvIds.PRECFGKEYS_ENABLE, t.Bool(True), create=True
        )
        await self._znp.nvram.osal_write(OsalNvIds.CHANLIST, channels, create=True)

        # Z-Stack Home 1.2 doesn't have the BDB subsystem
        if self._znp.version > 1.2:
            await self._znp.request(
                c.AppConfig.BDBSetChannel.Req(IsPrimary=True, Channel=channels),
                RspStatus=t.Status.SUCCESS,
            )
            await self._znp.request(
                c.AppConfig.BDBSetChannel.Req(
                    IsPrimary=False, Channel=t.Channels.NO_CHANNELS
                ),
                RspStatus=t.Status.SUCCESS,
            )

        # Finally, form the network
        LOGGER.debug("Forming the network")

        started_as_coordinator = self._znp.wait_for_response(
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator)
        )

        # Handle the startup progress messages
        async with self._znp.capture_responses(
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
            if self._znp.version > 1.2:
                # Z-Stack 3 uses the BDB subsystem
                commissioning_rsp = await self._znp.request_callback_rsp(
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

                if (
                    commissioning_rsp.Status
                    != c.app_config.BDBCommissioningStatus.Success
                ):
                    raise RuntimeError(f"Network formation failed: {commissioning_rsp}")
            else:
                await self._znp.nvram.osal_write(
                    OsalNvIds.TCLK_SEED,
                    value=DEFAULT_TC_LINK_KEY,
                    create=True,
                )

                # In Z-Stack 1.2.2, StartupFromApp actually does what it says
                await self._znp.request(
                    c.ZDO.StartupFromApp.Req(StartDelay=100),
                    RspState=c.zdo.StartupState.NewNetworkState,
                )

            # Both versions still end with this callback
            await started_as_coordinator

        LOGGER.debug("Waiting for the NIB to be populated")

        # Even though the device says it is "ready" at this point, it takes a few more
        # seconds for `_NIB.nwkState` to switch from `NwkState.NWK_INIT`. There does
        # not appear to be any user-facing MT command to read this information.
        while True:
            try:
                nib = parse_nib(await self._znp.nvram.osal_read(OsalNvIds.NIB))

                LOGGER.debug("Current NIB is %s", nib)

                # Usually this works after the first attempt
                if nib.nwkLogicalChannel != 0 and nib.nwkPanId != 0xFFFE:
                    break
            except KeyError:
                pass

            await asyncio.sleep(1)

        # Create the NV item that keeps track of whether or not we're fully configured.
        if self._znp.version == 1.2:
            configured_nv_item = OsalNvIds.HAS_CONFIGURED_ZSTACK1
        else:
            configured_nv_item = OsalNvIds.HAS_CONFIGURED_ZSTACK3

        await self._znp.nvram.osal_write(
            configured_nv_item, ZSTACK_CONFIGURE_SUCCESS, create=True
        )

        # Finally, reset once more to reset the device back to a "normal" state so that
        # we can continue the normal application startup sequence.
        await self._reset()

    def get_dst_address(self, cluster):
        """
        Helper to get a dst address for bind/unbind operations.

        Allows radios to provide correct information, especially for radios which listen
        on specific endpoints only.
        """

        dst_addr = MultiAddress()
        dst_addr.addrmode = 0x03
        dst_addr.ieee = self.ieee
        dst_addr.endpoint = self._find_endpoint(
            dst_ep=cluster.endpoint,
            profile=cluster.endpoint.profile_id,
            cluster=cluster.cluster_id,
        )

        return dst_addr

    @zigpy.util.retryable_request
    async def request(
        self,
        device,
        profile,
        cluster,
        src_ep,
        dst_ep,
        sequence,
        data,
        expect_reply=True,
        use_ieee=False,
    ) -> typing.Tuple[t.Status, str]:
        tx_options = c.af.TransmitOptions.SUPPRESS_ROUTE_DISC_NETWORK

        if expect_reply:
            tx_options |= c.af.TransmitOptions.ACK_REQUEST

        if use_ieee:
            destination = t.AddrModeAddress(mode=t.AddrMode.IEEE, address=device.ieee)
        else:
            destination = t.AddrModeAddress(mode=t.AddrMode.NWK, address=device.nwk)

        return await self._send_request(
            dst_addr=destination,
            dst_ep=dst_ep,
            src_ep=src_ep,
            profile=profile,
            cluster=cluster,
            sequence=sequence,
            options=tx_options,
            radius=30,
            data=data,
        )

    async def broadcast(
        self,
        profile,
        cluster,
        src_ep,
        dst_ep,
        grpid,
        radius,
        sequence,
        data,
        broadcast_address=zigpy.types.BroadcastAddress.RX_ON_WHEN_IDLE,
    ) -> typing.Tuple[t.Status, str]:
        assert grpid == 0

        return await self._send_request(
            dst_addr=t.AddrModeAddress(
                mode=t.AddrMode.Broadcast, address=broadcast_address
            ),
            dst_ep=dst_ep,
            src_ep=src_ep,
            profile=profile,
            cluster=cluster,
            sequence=sequence,
            options=c.af.TransmitOptions.NONE,
            radius=radius,
            data=data,
        )

    async def mrequest(
        self,
        group_id,
        profile,
        cluster,
        src_ep,
        sequence,
        data,
        *,
        hops=0,
        non_member_radius=3,
    ) -> typing.Tuple[t.Status, str]:
        return await self._send_request(
            dst_addr=t.AddrModeAddress(mode=t.AddrMode.Group, address=group_id),
            dst_ep=src_ep,
            src_ep=src_ep,
            profile=profile,
            cluster=cluster,
            sequence=sequence,
            options=c.af.TransmitOptions.NONE,
            radius=hops,
            data=data,
        )

    async def force_remove(self, device: zigpy.device.Device) -> None:
        """
        Attempts to forcibly remove a device from the network.
        """

        LOGGER.warning("Z-Stack does not support force remove")

    async def permit(self, time_s=60, node=None):
        """
        Overrides the `permit` method to throw an error when joins are permitted on only
        the coordinator.
        """

        if node is not None and node == self.ieee:
            raise RuntimeError("Joins cannot be permitted only on the coordinator")

        return await super().permit(time_s=time_s, node=node)

    async def permit_ncp(self, time_s: int) -> None:
        """
        Permits joins on the coordinator.
        """

        # Z-Stack does not have a way to change just the trust center policy without
        # also permitting joins on the coordinator. Sending a unicast permit join
        # request to 0x0000 causes the coordinator to later reject joins done through
        # another router if the coordinator is also not permitting joins, unfortunately
        # forcing this method to be a no-op.
        pass

    async def permit_with_key(self, node: t.EUI64, code: bytes, time_s=60):
        """
        Permits a new device to join with the given IEEE and Install Code.
        """

        key = zigpy.util.convert_install_code(code)
        install_code_format = c.app_config.InstallCodeFormat.KeyDerivedFromInstallCode

        if key is None:
            raise ValueError(f"Invalid install code: {code!r}")

        await self._znp.request(
            c.AppConfig.BDBAddInstallCode.Req(
                InstallCodeFormat=install_code_format,
                IEEE=node,
                InstallCode=t.Bytes(key),
            ),
            RspStatus=t.Status.SUCCESS,
        )

        # Temporarily only allow joins that use an install code
        await self._znp.request(
            c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(
                BdbJoinUsesInstallCodeKey=True
            ),
            RspStatus=t.Status.SUCCESS,
        )

        try:
            await self.permit(time_s)
            await asyncio.sleep(time_s)
        finally:
            # Revert back to normal. The BDB config is not persistent so if this request
            # fails, we will be back to normal the next time Z-Stack resets.
            await self._znp.request(
                c.AppConfig.BDBSetJoinUsesInstallCodeKey.Req(
                    BdbJoinUsesInstallCodeKey=False
                ),
                RspStatus=t.Status.SUCCESS,
            )

    def connection_lost(self, exc):
        """
        Propagated up from UART through ZNP when the connection is lost.
        Spawns the auto-reconnect task.
        """

        self._znp = None

        # exc=None means the connection was closed
        if exc is None:
            LOGGER.debug("Connection was purposefully closed. Not reconnecting.")
            return

        # Reconnect in the background using our previously-detected port.
        if self._reconnect_task.done():
            LOGGER.debug("Restarting background reconnection task")
            self._reconnect_task = asyncio.create_task(self._reconnect())

    #####################################################
    # Z-Stack message callbacks attached during startup #
    #####################################################

    def _bind_callbacks(self) -> None:
        """
        Binds all of the necessary message callbacks to their associated methods.

        Z-Stack intercepts most (but not all!) ZDO requests/responses and replaces them
        ZNP requests/responses.
        """

        self._znp.callback_for_response(
            c.AF.IncomingMsg.Callback(partial=True), self.on_af_message
        )

        # ZDO requests need to be handled explicitly, one by one
        self._znp.callback_for_response(
            c.ZDO.EndDeviceAnnceInd.Callback(partial=True),
            self.on_zdo_device_announce,
        )

        self._znp.callback_for_response(
            c.ZDO.TCDevInd.Callback.Callback(partial=True),
            self.on_zdo_tc_device_join,
        )

        self._znp.callback_for_response(
            c.ZDO.LeaveInd.Callback(partial=True), self.on_zdo_device_leave
        )

        self._znp.callback_for_response(
            c.ZDO.SrcRtgInd.Callback(partial=True), self.on_zdo_relays_message
        )

        self._znp.callback_for_response(
            c.ZDO.PermitJoinInd.Callback(partial=True), self.on_zdo_permit_join_message
        )

    def on_zdo_permit_join_message(self, msg: c.ZDO.PermitJoinInd.Callback) -> None:
        """
        Coordinator join status change message. Only sent with Z-Stack 1.2 and 3.0.
        """

        if msg.Duration == 0:
            LOGGER.info("Coordinator is not permitting joins anymore")
        else:
            LOGGER.info("Coordinator is permitting joins for %d seconds", msg.Duration)

    def on_zdo_relays_message(self, msg: c.ZDO.SrcRtgInd.Callback) -> None:
        """
        ZDO source routing message callback
        """

        LOGGER.info("ZDO device relays: %s", msg)

        try:
            device = self.get_device(nwk=msg.DstAddr)
        except KeyError:
            LOGGER.warning(
                "Received a ZDO message from an unknown device: 0x%04x", msg.DstAddr
            )
            return

        # `relays` is a property with a setter that emits an event
        device.relays = msg.Relays

    def on_zdo_device_announce(self, msg: c.ZDO.EndDeviceAnnceInd.Callback) -> None:
        """
        ZDO end device announcement callback
        """

        LOGGER.info("ZDO device announce: %s", msg)

        # Cancel an existing join timer so we don't double announce
        if msg.IEEE in self._join_announce_tasks:
            self._join_announce_tasks.pop(msg.IEEE).cancel()

        # Sometimes devices change their NWK when announcing so re-join it.
        self.handle_join(
            nwk=msg.NWK,
            ieee=msg.IEEE,
            parent_nwk=None,
        )

        device = self.get_device(ieee=msg.IEEE)

        # We turn this back into a ZDO message and let zigpy handle it
        self._receive_zdo_message(
            cluster=ZDOCmd.Device_annce,
            tsn=0xFF,
            sender=device,
            NWKAddr=msg.NWK,
            IEEEAddr=msg.IEEE,
            Capability=msg.Capabilities,
        )

    def on_zdo_tc_device_join(self, msg: c.ZDO.TCDevInd.Callback) -> None:
        """
        ZDO trust center device join callback.
        """

        LOGGER.info("TC device join: %s", msg)

        # Perform route discovery (just in case) when a device joins the network so that
        # we can begin initialization as soon as possible.
        asyncio.create_task(self._discover_route(msg.SrcNwk))

        if msg.SrcIEEE in self._join_announce_tasks:
            self._join_announce_tasks.pop(msg.SrcIEEE).cancel()

        # Some devices really don't like zigpy beginning its initialization process
        # before the device has announced itself. Wait a second or two before calling
        # `handle_join`, just in case the device announces itself first.
        self._join_announce_tasks[msg.SrcIEEE] = asyncio.get_running_loop().call_later(
            DEVICE_JOIN_MAX_DELAY,
            lambda: self.handle_join(
                nwk=msg.SrcNwk,
                ieee=msg.SrcIEEE,
                parent_nwk=msg.ParentNwk,
            ),
        )

    def on_zdo_device_leave(self, msg: c.ZDO.LeaveInd.Callback) -> None:
        LOGGER.info("ZDO device left: %s", msg)
        self.handle_leave(nwk=msg.NWK, ieee=msg.IEEE)

    def on_af_message(self, msg: c.AF.IncomingMsg.Callback) -> None:
        """
        Handler for all non-ZDO messages.
        """

        try:
            device = self.get_device(nwk=msg.SrcAddr)
        except KeyError:
            LOGGER.warning(
                "Received an AF message from an unknown device: 0x%04x", msg.SrcAddr
            )
            return

        device.radio_details(lqi=msg.LQI, rssi=None)

        # XXX: Is it possible to receive messages on non-assigned endpoints?
        if msg.DstEndpoint in self.zigpy_device.endpoints:
            profile = self.zigpy_device.endpoints[msg.DstEndpoint].profile_id
        else:
            LOGGER.warning("Received a message on an unregistered endpoint: %s", msg)
            profile = zigpy.profiles.zha.PROFILE_ID

        self.handle_message(
            sender=device,
            profile=profile,
            cluster=msg.ClusterId,
            src_ep=msg.SrcEndpoint,
            dst_ep=msg.DstEndpoint,
            message=msg.Data,
        )

    ####################
    # Internal methods #
    ####################

    @property
    def zigpy_device(self) -> zigpy.device.Device:
        """
        Reference to zigpy device 0x0000, the coordinator.
        """

        return self.devices[self.ieee]

    @property
    def znp_config(self) -> conf.ConfigType:
        """
        Shortcut property to access the ZNP radio config.
        """

        return self.config[conf.CONF_ZNP_CONFIG]

    async def _set_led_mode(self, *, led, mode) -> None:
        """
        Attempts to set the provided LED's mode. A Z-Stack bug causes the underlying
        command to never receive a response if the board has no LEDs, requiring this
        wrapper function prevent the command from taking many seconds to time out.
        """

        # XXX: If Z-Stack is not compiled with HAL_LED, it will just not respond at all
        try:
            async with async_timeout.timeout(0.1):
                await self._znp.request(
                    c.Util.LEDControl.Req(LED=led, Mode=mode),
                    RspStatus=t.Status.SUCCESS,
                )
        except (asyncio.TimeoutError, CommandNotRecognized):
            LOGGER.info("This build of Z-Stack does not appear to support LED control")

    async def _write_stack_settings(self, *, reset_if_changed: bool) -> None:
        """
        Writes network-independent Z-Stack settings to NVRAM.
        If no settings actually change, no reset will be performed.
        """

        # It's better to be explicit than rely on the NVRAM defaults
        settings = {
            OsalNvIds.LOGICAL_TYPE: t.DeviceLogicalType.Coordinator,
            # Source routing
            OsalNvIds.CONCENTRATOR_ENABLE: t.Bool(True),
            OsalNvIds.CONCENTRATOR_DISCOVERY: t.uint8_t(120),
            OsalNvIds.CONCENTRATOR_RC: t.Bool(True),
            OsalNvIds.SRC_RTG_EXPIRY_TIME: t.uint8_t(255),
            OsalNvIds.NWK_CHILD_AGE_ENABLE: t.Bool(False),
            # Default is 20 in Z-Stack 3.0.1, 30 in Z-Stack 3/4
            OsalNvIds.BCAST_DELIVERY_TIME: t.uint8_t(30),
            # We want to receive all ZDO callbacks to proxy them back to zigpy
            OsalNvIds.ZDO_DIRECT_CB: t.Bool(True),
        }

        any_changed = False

        for nvid, value in settings.items():
            try:
                current_value = await self._znp.nvram.osal_read(nvid)
            except InvalidCommandResponse:
                current_value = None

            # There is no point in issuing a write if the value will not change
            if current_value != value.serialize():
                await self._znp.nvram.osal_write(nvid, value)
                any_changed = True

        if reset_if_changed and any_changed:
            # Reset to make the above NVRAM writes take effect
            await self._reset()

    @contextlib.asynccontextmanager
    async def _limit_concurrency(self):
        """
        Async context manager that prevents devices from being overwhelmed by requests.
        Mainly a thin wrapper around `asyncio.Semaphore` that logs when it has to wait.
        """

        start_time = time.time()
        was_locked = self._concurrent_requests_semaphore.locked()

        if was_locked:
            self._currently_waiting_requests += 1
            LOGGER.debug(
                "Max concurrency reached, delaying requests (%s enqueued)",
                self._currently_waiting_requests,
            )

        try:
            async with self._concurrent_requests_semaphore:
                if was_locked:
                    LOGGER.debug(
                        "Previously delayed request is now running, "
                        "delayed by %0.2f seconds",
                        time.time() - start_time,
                    )

                yield
        finally:
            if was_locked:
                self._currently_waiting_requests -= 1

    def _receive_zdo_message(
        self,
        cluster: ZDOCmd,
        *,
        tsn: t.uint8_t,
        sender: zigpy.device.Device,
        **zdo_kwargs,
    ) -> None:
        """
        Internal method that is mainly called by our ZDO request/response converters to
        receive a "fake" ZDO message constructed from a cluster and args/kwargs.
        """

        field_names, field_types = ZDO_CLUSTERS[cluster]
        assert set(zdo_kwargs) == set(field_names)

        # Type cast all of the field args and kwargs
        zdo_args = [t(zdo_kwargs[name]) for name, t in zip(field_names, field_types)]
        message = t.serialize_list([t.uint8_t(tsn)] + zdo_args)

        LOGGER.debug("Pretending we received a ZDO message: %s", message)

        self.handle_message(
            sender=sender,
            profile=zigpy.profiles.zha.PROFILE_ID,
            cluster=cluster,
            src_ep=ZDO_ENDPOINT,
            dst_ep=ZDO_ENDPOINT,
            message=message,
        )

    async def _reconnect(self) -> None:
        """
        Endlessly tries to reconnect to the currently configured radio.

        Relies on the fact that `self.startup()` only modifies `self` upon a successful
        connection to be essentially stateless.
        """

        for attempt in itertools.count(start=1):
            LOGGER.debug(
                "Trying to reconnect to %s, attempt %d",
                self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH],
                attempt,
            )

            try:
                await self._startup()
                return
            except Exception as e:
                LOGGER.error("Failed to reconnect", exc_info=e)
                await asyncio.sleep(
                    self._config[conf.CONF_ZNP_CONFIG][
                        conf.CONF_AUTO_RECONNECT_RETRY_DELAY
                    ]
                )

    async def _register_endpoint(
        self,
        endpoint,
        profile_id=zigpy.profiles.zha.PROFILE_ID,
        device_id=zigpy.profiles.zha.DeviceType.CONFIGURATION_TOOL,
        device_version=0b0000,
        latency_req=c.af.LatencyReq.NoLatencyReqs,
        input_clusters=[],
        output_clusters=[],
    ):
        """
        Method to register an endpoint simultaneously with both zigpy and Z-Stack.

        This lets us keep track of our own endpoint information without duplicating
        that information again, and exposing it to higher layers (e.g. Home Assistant).
        """

        # Create a corresponding endpoint on our Zigpy device first
        zigpy_ep = self.zigpy_device.add_endpoint(endpoint)
        zigpy_ep.profile_id = profile_id
        zigpy_ep.device_type = device_id

        for cluster in input_clusters:
            zigpy_ep.add_input_cluster(cluster)

        for cluster in output_clusters:
            zigpy_ep.add_output_cluster(cluster)

        zigpy_ep.status = zigpy.endpoint.Status.ZDO_INIT

        return await self._znp.request(
            c.AF.Register.Req(
                Endpoint=endpoint,
                ProfileId=profile_id,
                DeviceId=device_id,
                DeviceVersion=device_version,
                LatencyReq=latency_req,  # completely ignored by Z-Stack
                InputClusters=input_clusters,
                OutputClusters=output_clusters,
            ),
            RspStatus=t.Status.SUCCESS,
        )

    async def _load_device_info(self):
        """
        Loads low-level network information from NVRAM.
        """

        # Parsing the NIB struct gives us access to low-level info, like the channel
        self._nib = parse_nib(await self._znp.nvram.osal_read(OsalNvIds.NIB))
        LOGGER.debug("Parsed NIB: %s", self._nib)

        nwkkey = await self._znp.nvram.osal_read(OsalNvIds.NWKKEY)

        if self._znp.version < 3.30:
            key_info, _ = t.NwkActiveKeyItemsCC2531.deserialize(nwkkey)
        else:
            key_info, _ = t.NwkActiveKeyItems.deserialize(nwkkey)

        self._channel = self._nib.nwkLogicalChannel
        self._channels = self._nib.channelList
        self._pan_id = self._nib.nwkPanId
        self._ext_pan_id = self._nib.extendedPANID

        self._network_key = key_info.Active.Key
        self._network_key_seq = key_info.Active.KeySeqNum

        LOGGER.debug("Parsed key info: %s", key_info)

    async def _reset(self):
        """
        Performs a soft reset within Z-Stack.
        A hard reset resets the serial port, causing the device to disconnect.
        """

        await self._znp.request_callback_rsp(
            request=c.SYS.ResetReq.Req(Type=t.ResetType.Soft),
            callback=c.SYS.ResetInd.Callback(partial=True),
        )

    def _find_endpoint(self, dst_ep: int, profile: int, cluster: int) -> int:
        """
        Zigpy defaults to sending messages with src_ep == dst_ep. This does not work
        with Z-Stack, which requires endpoints to be registered explicitly on startup.
        """

        if dst_ep == ZDO_ENDPOINT:
            return ZDO_ENDPOINT

        # Always fall back to endpoint 1
        candidates = [1]

        for ep_id, endpoint in self.zigpy_device.endpoints.items():
            if ep_id == ZDO_ENDPOINT:
                continue

            if endpoint.profile_id != profile:
                continue

            # An exact match, no need to continue further
            # TODO: pass in `is_server_cluster` or something similar
            if cluster in endpoint.out_clusters or cluster in endpoint.in_clusters:
                return endpoint.endpoint_id

            # Otherwise, keep track of the candidate cluster
            # if we don't find anything better
            candidates.append(endpoint.endpoint_id)

        return candidates[-1]

    async def _send_zdo_request(
        self, dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
    ):
        """
        Zigpy doesn't send ZDO requests via TI's ZDO_* MT commands, so it will never
        receive a reply because ZNP intercepts ZDO replies, never sends a DataConfirm,
        and instead replies with one of its ZDO_* MT responses.

        This method translates the ZDO_* MT response into one zigpy can handle.
        """

        LOGGER.debug(
            "Intercepted a ZDO request: dst_addr=%s, dst_ep=%s, src_ep=%s, "
            "cluster=%s, sequence=%s, options=%s, radius=%s, data=%s",
            dst_addr,
            dst_ep,
            src_ep,
            cluster,
            sequence,
            options,
            radius,
            data,
        )

        assert dst_ep == ZDO_ENDPOINT

        # Deserialize the ZDO request
        zdo_hdr, data = ZDOHeader.deserialize(cluster, data)
        field_names, field_types = ZDO_CLUSTERS[cluster]
        zdo_args, _ = list_deserialize(data, field_types)
        zdo_kwargs = dict(zip(field_names, zdo_args))

        # TODO: Check out `ZDO.MsgCallbackRegister`

        if cluster not in ZDO_CONVERTERS:
            LOGGER.error(
                "ZDO converter for cluster %s has not been implemented!"
                " Please open a GitHub issue and attach a debug log:"
                " https://github.com/zigpy/zigpy-znp/issues/new",
                cluster,
            )
            raise RuntimeError("No ZDO converter")

        # Call the converter with the ZDO request's kwargs
        req_factory, rsp_factory, zdo_rsp_factory = ZDO_CONVERTERS[cluster]
        request = req_factory(dst_addr, **zdo_kwargs)
        callback = rsp_factory(dst_addr)

        LOGGER.debug(
            "Intercepted AP ZDO request %s(%s) and replaced with %s",
            cluster,
            zdo_kwargs,
            request,
        )

        # The coordinator responds to broadcasts
        if dst_addr.mode == t.AddrMode.Broadcast:
            callback = callback.replace(Src=0x0000)

        async with async_timeout.timeout(ZDO_REQUEST_TIMEOUT):
            response = await self._znp.request_callback_rsp(
                request=request, RspStatus=t.Status.SUCCESS, callback=callback
            )

        # We should only send zigpy unicast responses
        if dst_addr.mode == t.AddrMode.NWK:
            zdo_rsp_cluster, zdo_response_kwargs = zdo_rsp_factory(response)

            self._receive_zdo_message(
                cluster=zdo_rsp_cluster,
                tsn=sequence,
                sender=self.get_device(nwk=dst_addr.address),
                **zdo_response_kwargs,
            )

        return response

    async def _send_request_raw(
        self,
        dst_addr,
        dst_ep,
        src_ep,
        profile,
        cluster,
        sequence,
        options,
        radius,
        data,
        *,
        relays=None,
    ):
        """
        Used by `request`/`mrequest`/`broadcast` to send a request.
        Picks the correct request sending mechanism and fixes endpoint information.
        """

        # ZDO requests must be handled by the translation layer, since Z-Stack will
        # "steal" the responses
        if dst_ep == ZDO_ENDPOINT:
            return await self._send_zdo_request(
                dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
            )

        # Zigpy just sets src == dst, which doesn't work for devices with many endpoints
        # We pick ours based on the registered endpoints.
        src_ep = self._find_endpoint(dst_ep=dst_ep, profile=profile, cluster=cluster)

        if relays is None:
            request = c.AF.DataRequestExt.Req(
                DstAddrModeAddress=dst_addr,
                DstEndpoint=dst_ep,
                DstPanId=0x0000,
                SrcEndpoint=src_ep,
                ClusterId=cluster,
                TSN=sequence,
                Options=options,
                Radius=radius,
                Data=data,
            )
        else:
            request = c.AF.DataRequestSrcRtg.Req(
                DstAddr=dst_addr.address,
                DstEndpoint=dst_ep,
                SrcEndpoint=src_ep,
                ClusterId=cluster,
                TSN=sequence,
                Options=options,
                Radius=radius,
                SourceRoute=relays,  # force the packet to go through specific parents
                Data=data,
            )

        if dst_addr.mode == t.AddrMode.Broadcast:
            # Broadcasts will not receive a confirmation but they still take time
            # and use up concurrency slots
            response = await self._znp.request(
                request=request, RspStatus=t.Status.SUCCESS
            )

            await asyncio.sleep(0.1 * self._nib.BroadcastDeliveryTime)
        else:
            async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
                # Shield from cancellation to prevent requests that time out
                # in higher layers from missing expected responses
                response = await asyncio.shield(
                    self._znp.request_callback_rsp(
                        request=request,
                        RspStatus=t.Status.SUCCESS,
                        callback=c.AF.DataConfirm.Callback(
                            partial=True,
                            TSN=sequence,
                            # XXX: can this ever not match?
                            # Endpoint=src_ep,
                        ),
                    )
                )

                # Both the callback and the response can have an error status
                if response.Status != t.Status.SUCCESS:
                    raise InvalidCommandResponse(
                        f"Unsuccessful request status code: {response.Status!r}",
                        response,
                    )

        return response

    async def _discover_route(self, nwk: t.NWK) -> None:
        """
        Instructs the coordinator to re-discover routes to the provided NWK.
        Runs concurrently and at most once per NWK, even if called multiple times.
        """

        # Route discovery with Z-Stack 1.2 and Z-Stack 3.0.2 on the CC2531 doesn't
        # appear to work very well (Z2M#2901)
        if self._znp.version < 3.30:
            return

        if nwk in self._route_discovery_futures:
            return await self._route_discovery_futures[nwk]

        future = asyncio.get_running_loop().create_future()
        self._route_discovery_futures[nwk] = future

        try:
            await self._znp.request(
                c.ZDO.ExtRouteDisc.Req(
                    Dst=nwk,
                    Options=c.zdo.RouteDiscoveryOptions.UNICAST,
                    Radius=30,
                ),
            )

            await asyncio.sleep(0.1 * self._nib.RouteDiscoveryTime)
        finally:
            future.set_result(True)
            del self._route_discovery_futures[nwk]

    async def _send_request(
        self,
        dst_addr,
        dst_ep,
        src_ep,
        profile,
        cluster,
        sequence,
        options,
        radius,
        data,
    ) -> typing.Tuple[t.Status, str]:
        """
        Fault-tolerant wrapper around `_send_request_raw` that transparently attempts to
        repair routes and contact the device through other methods when Z-Stack errors
        are encountered.
        """

        if dst_addr.mode == t.AddrMode.NWK:
            device = self.get_device(nwk=dst_addr.address)
        elif dst_addr.mode == t.AddrMode.IEEE:
            device = self.get_device(ieee=dst_addr.address)
        else:
            device = None

        status = None
        response = None
        association = None
        force_relays = None

        tried_assoc_remove = False
        tried_route_discovery = False
        tried_disable_route_discovery_suppression = False
        tried_last_good_route = False

        # Don't release the concurrency-limiting semaphore until we are done trying.
        # There is no point in allowing requests to take turns getting buffer errors.
        try:
            async with self._limit_concurrency():
                for attempt in range(REQUEST_MAX_RETRIES):
                    try:
                        # ZDO requests do not generate `AF.DataConfirm` messages
                        # indicating that a route is missing so we need to explicitly
                        # check for one.
                        if (
                            dst_ep == ZDO_ENDPOINT
                            and dst_addr.mode == t.AddrMode.NWK
                            and dst_addr.address != 0x0000
                        ):
                            route_status = await self._znp.request(
                                c.ZDO.ExtRouteChk.Req(
                                    Dst=dst_addr.address,
                                    RtStatus=c.zdo.RouteStatus.ACTIVE,
                                    Options=(
                                        c.zdo.RouteOptions.MTO_ROUTE
                                        | c.zdo.RouteOptions.NO_ROUTE_CACHE
                                    ),
                                )
                            )

                            if route_status.Status != c.zdo.RoutingStatus.SUCCESS:
                                await self._discover_route(dst_addr.address)

                        response = await self._send_request_raw(
                            dst_addr=dst_addr,
                            dst_ep=dst_ep,
                            src_ep=src_ep,
                            profile=profile,
                            cluster=cluster,
                            sequence=sequence,
                            options=options,
                            radius=radius,
                            data=data,
                            relays=force_relays,
                        )
                        break
                    except InvalidCommandResponse as e:
                        status = e.response.Status

                        if status not in REQUEST_RETRYABLE_ERRORS:
                            raise

                        # We cannot do anything but retry if the error is transient or
                        # we are not sending a unicast request. Retry at least once.
                        if (
                            status in REQUEST_TRANSIENT_ERRORS
                            or attempt == 0
                            or device is None
                        ):
                            LOGGER.debug(
                                "Request failed (%s), retry attempt %s of %s",
                                e,
                                attempt + 1,
                                REQUEST_MAX_RETRIES,
                            )
                            await asyncio.sleep(3 * REQUEST_ERROR_RETRY_DELAY)
                            continue

                        # If we can't contact the device by forcing a specific route,
                        # there is not point in trying this more than once.
                        if tried_last_good_route and force_relays is not None:
                            force_relays = None

                        # Child aging is disabled so if a child switches parents from
                        # the coordinator to another router, we will not be able to
                        # re-discover a route to it. We have to manually drop the child
                        # to do this.
                        if (
                            status == t.Status.MAC_TRANSACTION_EXPIRED
                            and association is None
                            and not tried_assoc_remove
                            and self._znp.version >= 3.30
                        ):
                            # XXX: do we use NWK or IEEE?
                            association = await self._znp.request(
                                c.Util.AssocGetWithAddress.Req(
                                    IEEE=device.ieee,
                                    NWK=device.nwk,
                                )
                            )

                            if (
                                association.Device.nodeRelation
                                != c.util.NodeRelation.NOTUSED
                            ):
                                try:
                                    await self._znp.request(
                                        c.Util.AssocRemove.Req(IEEE=device.ieee)
                                    )
                                    tried_assoc_remove = True

                                    # Route discovery must be performed right after
                                    await self._discover_route(device.nwk)
                                except CommandNotRecognized:
                                    LOGGER.debug(
                                        "The UTIL.AssocRemove command is available only"
                                        " in Z-Stack 3 releases built after 20201017"
                                    )
                        elif not tried_route_discovery:
                            # If that doesn't work, try re-discovering the route.
                            # While we can in theory poll and wait until it is fixed,
                            # letting the retry mechanism deal with it simpler.
                            await self._discover_route(device.nwk)
                            tried_route_discovery = True
                        elif not tried_disable_route_discovery_suppression:
                            # Disable route discovery suppression. This appears to
                            # generate a bit more network traffic.
                            options &= ~c.af.TransmitOptions.SUPPRESS_ROUTE_DISC_NETWORK
                            tried_disable_route_discovery_suppression = True
                        elif (
                            not tried_last_good_route
                            and device is not None
                            and device.relays is not None
                        ):
                            # `ZDO.SrcRtgInd` callbacks tell us the last path taken by
                            # messages from the device back to the coordinator. Sending
                            # packets backwards via this same route may work.
                            force_relays = device.relays[::-1]
                            tried_last_good_route = True

                        LOGGER.debug(
                            "Request failed (%s), retry attempt %s of %s",
                            e,
                            attempt + 1,
                            REQUEST_MAX_RETRIES,
                        )

                        # We've tried everything already so at this point just wait
                        await asyncio.sleep(REQUEST_ERROR_RETRY_DELAY)
                else:
                    raise DeliveryError(
                        f"Request failed after {REQUEST_MAX_RETRIES} attempts:"
                        f" {status!r}"
                    )
        finally:
            # We *must* re-add the device association if we previously removed it but
            # the request still failed. Otherwise, it may be a direct child and we will
            # not be able to find it again.
            if tried_assoc_remove and response is None:
                await self._znp.request(
                    c.Util.AssocAdd.Req(
                        NWK=device.nwk,
                        IEEE=device.ieee,
                        NodeRelation=association.Device.nodeRelation,
                    )
                )

        if response.Status != t.Status.SUCCESS:
            return response.Status, "Failed to send request"

        return response.Status, "Sent request successfully"
