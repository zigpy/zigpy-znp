import os
import time
import typing
import asyncio
import logging
import warnings
import itertools
import contextlib
import async_timeout

import zigpy.zdo
import zigpy.util
import zigpy.types
import zigpy.device
import zigpy.config
import zigpy.profiles
import zigpy.endpoint
import zigpy.zcl.foundation

from zigpy.zcl import clusters
from zigpy.types import (
    ExtendedPanId,
    deserialize as list_deserialize,
    Struct as ZigpyStruct,
)
from zigpy.zdo.types import MultiAddress, ZDOCmd, ZDOHeader, CLUSTERS as ZDO_CLUSTERS
from zigpy.exceptions import DeliveryError

import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c

from zigpy_znp.api import ZNP
from zigpy_znp.znp.nib import parse_nib, OldNIB
from zigpy_znp.exceptions import InvalidCommandResponse
from zigpy_znp.types.nvids import NwkNvIds
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
ZDO_REQUEST_TIMEOUT = 10  # seconds
DATA_CONFIRM_TIMEOUT = 5  # seconds
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
        # There is no way to query the Z-Stack version or even the hardware at runtime.
        # Instead we have to rely on these sorts of "hints"
        if isinstance(self.application._nib, OldNIB):
            return "CC2531"
        else:
            return "CC13X2/CC26X2"


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA
    SCHEMA_DEVICE = conf.SCHEMA_DEVICE

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=conf.CONFIG_SCHEMA(config))

        self._znp: typing.Optional[ZNP] = None

        # It's simpler to work with Task objects if they're never actually None
        self._reconnect_task = asyncio.Future()
        self._reconnect_task.cancel()

        self._nib = None
        self._concurrent_requests_semaphore = None

    ##################################################################
    # Implementation of the core zigpy ControllerApplication methods #
    ##################################################################

    @property
    def channel(self):
        # This value is accessible only from the NIB struct. There does not appear to be
        # a MT command to read it.

        if self._nib is None:
            return None

        return self._nib.nwkLogicalChannel

    @classmethod
    async def probe(cls, device_config: conf.ConfigType) -> bool:
        """
        Checks whether the device represented by `device_config` is a valid ZNP radio.
        Doesn't throw any errors.
        """

        znp = ZNP(conf.CONFIG_SCHEMA({conf.CONF_DEVICE: device_config}))
        LOGGER.debug("Probing %s", znp._port_path)

        try:
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

        if self._znp is not None:
            self._znp.close()

    async def startup(self, auto_form=False):
        """
        Performs application startup.

        This entails creating the ZNP object, connecting to the radio, potentially
        forming a network, and configuring our settings.
        """

        znp = ZNP(self.config)
        znp.set_application(self)
        await znp.connect()

        # We only assign `self._znp` after it has successfully connected
        self._znp = znp
        self._bind_callbacks()

        # XXX: To make sure we don't switch to the wrong device upon reconnect,
        #      update our config to point to the last-detected port.
        if self._config[conf.CONF_DEVICE][conf.CONF_DEVICE_PATH] == "auto":
            self._config[conf.CONF_DEVICE][
                conf.CONF_DEVICE_PATH
            ] = self._znp._uart.transport.serial.name

        # Next, read out the NVRAM item that Zigbee2MQTT writes when it has configured
        # a device to make sure that our network settings will not be reset.
        try:
            is_configured = (
                await self._znp.nvram_read(NwkNvIds.HAS_CONFIGURED_ZSTACK3)
            ) == b"\x55"
        except InvalidCommandResponse as e:
            assert e.response.Status == t.Status.INVALID_PARAMETER
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

        if self.znp_config[conf.CONF_LED_MODE] is not None:
            led_mode = self.znp_config[conf.CONF_LED_MODE]

            await self._znp.request(
                c.Util.LEDControl.Req(LED=0xFF, Mode=led_mode),
                RspStatus=t.Status.SUCCESS,
            )

        device_info = await self._znp.request(
            c.Util.GetDeviceInfo.Req(), RspStatus=t.Status.SUCCESS
        )

        self._ieee = device_info.IEEE
        self._nwk = 0x0000

        # Add the coordinator as a zigpy device. We do this up here because
        # `self._register_endpoint()` adds endpoints to this device object.
        self.devices[self.ieee] = ZNPCoordinator(self, self.ieee, self.nwk)

        # Start the application and wait until it's ready
        started_as_coordinator = self._znp.wait_for_response(
            c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator)
        )

        bdb_commissioning_done = self._znp.wait_for_response(
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True, RemainingModes=c.app_config.BDBCommissioningMode.NONE
            )
        )

        # The AUTOSTART startup NV item doesn't do anything.
        # According to the forums, this is the correct startup sequence, including
        # the formation failure error
        await self._znp.request_callback_rsp(
            request=c.AppConfig.BDBStartCommissioning.Req(
                Mode=c.app_config.BDBCommissioningMode.NwkFormation
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True, Status=c.app_config.BDBCommissioningStatus.NetworkRestored
            ),
        )

        # The startup sequence should not take forever
        async with async_timeout.timeout(20):
            # These often arrive in random order
            await asyncio.gather(started_as_coordinator, bdb_commissioning_done)

        # Get the currently active endpoints
        endpoints = await self._znp.request_callback_rsp(
            request=c.ZDO.ActiveEpReq.Req(DstAddr=0x0000, NWKAddrOfInterest=0x0000),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.ActiveEpRsp.Callback(partial=True),
        )

        # Clear them out
        for endpoint in endpoints.ActiveEndpoints:
            await self._znp.request(
                c.AF.Delete.Req(Endpoint=endpoint), RspStatus=t.Status.SUCCESS
            )

        # And register our own
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
            max_concurrent_requests = 2 if self.is_cc2531 else 16
        else:
            max_concurrent_requests = self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS]

        self._concurrent_requests_semaphore = asyncio.Semaphore(max_concurrent_requests)

        LOGGER.info(
            "Using channel mask %s, currently on channel %d."
            " Limiting concurrent requests to %d",
            self.channels,
            self.channel,
            max_concurrent_requests,
        )

    async def update_network(
        self,
        *,
        channel: typing.Optional[t.uint8_t] = None,
        channels: typing.Optional[t.Channels] = None,
        extended_pan_id: typing.Optional[t.ExtendedPanId] = None,
        network_key: typing.Optional[t.KeyData] = None,
        pan_id: typing.Optional[t.PanId] = None,
        tc_address: typing.Optional[t.EUI64] = None,
        tc_link_key: typing.Optional[t.KeyData] = None,
        update_id: int = 0,
        reset: bool = True,
    ):
        """
        Updates network settings at runtime, after the application has started.
        """

        if (
            channel is not None
            and channels is not None
            and not t.Channels.from_channel_list([channel]) & channels
        ):
            raise ValueError("Channel does not overlap with channel mask")

        if tc_link_key is not None:
            LOGGER.warning("Trust center link key in config is not yet supported")

        if tc_address is not None:
            LOGGER.warning("Trust center address in config is not yet supported")

        if channels is not None:
            await self._znp.nvram_write(NwkNvIds.CHANLIST, channels)
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

        if channel is not None:
            # XXX: We modify the logical channel value directly in the NIB.
            #      Is there no better way?
            nib = parse_nib(await self._znp.nvram_read(NwkNvIds.NIB))
            nib.nwkLogicalChannel = channel
            await self._znp.nvram_write(NwkNvIds.NIB, nib.serialize())

        if pan_id is not None:
            await self._znp.nvram_write(NwkNvIds.PANID, pan_id)

        if extended_pan_id is not None:
            # There is no Util request to do this
            await self._znp.nvram_write(NwkNvIds.EXTENDED_PAN_ID, extended_pan_id)

        if network_key is not None:
            await self._znp.nvram_write(NwkNvIds.PRECFGKEY, network_key)
            await self._znp.nvram_write(NwkNvIds.PRECFGKEYS_ENABLE, t.Bool(True))

        if reset:
            # We have to reset afterwards
            await self._reset()
            await self._load_device_info()

    async def form_network(self):
        """
        Clears the current config and forms a new network with a random network key,
        PAN ID, and extended PAN ID.
        """

        # Delete any existing HAS_CONFIGURED_ZSTACK3 NV item. This may fail.
        await self._znp.request(
            c.SYS.OSALNVDelete.Req(Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1)
        )

        # Instruct Z-Stack to reset everything on the next boot
        await self._znp.nvram_write(
            NwkNvIds.STARTUP_OPTION,
            t.StartupOptions.ClearState | t.StartupOptions.ClearConfig,
        )

        # And reset to clear everything
        await self._reset()

        # Now that we've cleared everything, write back our Z-Stack settings
        await self._write_stack_settings(reset_if_changed=False)

        pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_PAN_ID]

        if pan_id is None:
            # Let Z-Stack pick one at random, hopefully not conflicting with others
            pan_id = t.uint16_t(0xFFFF)

        extended_pan_id = self.config[conf.CONF_NWK][conf.CONF_NWK_EXTENDED_PAN_ID]

        if extended_pan_id is None:
            # It's not documented whether or not Z-Stack will pick this randomly as well
            # if a value of 00:00:00:00:00:00:00:00 is provided but the chances of a
            # collision using `os.urandom` are astronomically small
            extended_pan_id = ExtendedPanId(os.urandom(8))

        LOGGER.debug("Updating network settings")

        # Update the network settings.
        # Not resetting before we form the network is important!
        await self.update_network(
            # We don't set the channel in here because it will have no effect
            channels=self.config[conf.CONF_NWK][conf.CONF_NWK_CHANNELS],
            pan_id=pan_id,
            extended_pan_id=extended_pan_id,
            network_key=t.KeyData(os.urandom(16)),
            reset=False,
        )

        # Finally, form the network
        LOGGER.debug("Forming the network")

        # Form the network and capture expected progress messages so they don't appear
        # as warnings within logs
        async with self._znp.capture_responses(
            [
                c.ZDO.StateChangeInd.Callback(
                    State=t.DeviceState.StartingAsCoordinator
                ),
                c.ZDO.StateChangeInd.Callback(State=t.DeviceState.StartedAsCoordinator),
                c.AppConfig.BDBCommissioningNotification.Callback(
                    partial=True, Status=c.app_config.BDBCommissioningStatus.InProgress
                ),
            ]
        ):
            bdb_commissioning_rsp = await self._znp.request_callback_rsp(
                request=c.AppConfig.BDBStartCommissioning.Req(
                    Mode=c.app_config.BDBCommissioningMode.NwkFormation
                ),
                RspStatus=t.Status.SUCCESS,
                callback=c.AppConfig.BDBCommissioningNotification.Callback(
                    partial=True, RemainingModes=c.app_config.BDBCommissioningMode.NONE
                ),
            )

        if bdb_commissioning_rsp.Status != c.app_config.BDBCommissioningStatus.Success:
            raise RuntimeError(f"Network formation failed: {bdb_commissioning_rsp}")

        LOGGER.debug("Waiting for the network NIB to be populated")

        # Even though the device is "ready" at this point, for some reason it takes
        # a few more seconds for the NIB to update with our correct logical channel
        while True:
            nib = parse_nib(await self._znp.nvram_read(NwkNvIds.NIB))

            # Usually this works after the first attempt
            if nib.nwkLogicalChannel:
                break

            await asyncio.sleep(1)

        # Only at this point can we update our logical channel
        channel = self.config[conf.CONF_NWK][conf.CONF_NWK_CHANNEL]

        if channel is not None and channel != nib.nwkLogicalChannel:
            LOGGER.debug(
                "Z-Stack started with channel %d. Updating to %d.",
                nib.nwkLogicalChannel,
                channel,
            )
            await self.update_network(channel=channel)

        # Create the NV item that keeps track of whether or not we're configured.
        # This is the NV item used by Zigbee2MQTT, pulled in from zigbee-shepherd, and
        # allows for this device to be used with Zigbee2MQTT as well.
        osal_create_rsp = await self._znp.request(
            c.SYS.OSALNVItemInit.Req(
                Id=NwkNvIds.HAS_CONFIGURED_ZSTACK3, ItemLen=1, Value=b"\x55"
            )
        )

        if osal_create_rsp.Status not in (t.Status.SUCCESS, t.Status.NV_ITEM_UNINIT):
            raise RuntimeError(
                f"Network formation failed: could not create"
                f" HAS_CONFIGURED_ZSTACK3 NV item: {osal_create_rsp}"
            )  # pragma: no cover

        # Initializing the item doesn't guarantee that it holds this exact value
        await self._znp.nvram_write(NwkNvIds.HAS_CONFIGURED_ZSTACK3, b"\x55")

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
        tx_options = c.af.TransmitOptions.RouteDiscovery

        if expect_reply:
            tx_options |= c.af.TransmitOptions.APSAck

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
            src_ep=src_ep,  # not actually used?
            profile=profile,
            cluster=cluster,
            sequence=sequence,
            options=c.af.TransmitOptions.NONE,
            radius=hops,
            data=data,
        )

    async def force_remove(self, device) -> None:
        """
        Forcibly removes a direct child from the network.
        """

        async with self._limit_concurrency():
            leave_rsp = await self._znp.request_callback_rsp(
                request=c.ZDO.MgmtLeaveReq.Req(
                    DstAddr=0x0000,  # We handle it
                    IEEE=device.ieee,
                    RemoveChildren_Rejoin=c.zdo.LeaveOptions.NONE,
                ),
                RspStatus=t.Status.SUCCESS,
                callback=c.ZDO.MgmtLeaveRsp.Callback(Src=0x0000, partial=True),
            )

        assert leave_rsp.Status == t.ZDOStatus.SUCCESS

        # TODO: see what happens when we forcibly remove a device that isn't our child

    async def permit_ncp(self, time_s: int) -> None:
        """
        Permits new devices to join the network *only through us*.
        Zigpy sends a broadcast to all routers on its own.
        """

        response = await self._znp.request_callback_rsp(
            request=c.ZDO.MgmtPermitJoinReq.Req(
                AddrMode=t.AddrMode.NWK,
                Dst=0x0000,  # Only us!
                Duration=time_s,
                # "This field shall always have a value of 1,
                #  indicating a request to change the
                #  Trust Center policy."
                TCSignificance=1,
            ),
            RspStatus=t.Status.SUCCESS,
            callback=c.ZDO.MgmtPermitJoinRsp.Callback(partial=True),
        )

        if response.Status != t.Status.SUCCESS:
            raise RuntimeError(f"Permit join response failure: {response}")

    def connection_lost(self, exc):
        """
        Propagated up from lower layers (UART and ZNP) when the connection is lost.
        Spawns the auto-reconnect task.
        """

        self._znp = None

        # exc=None means that the connection was closed
        if exc is None:
            LOGGER.debug("Connection was purposefully closed. Not reconnecting.")
            return

        # Reconnect in the background using our previously-detected port.
        LOGGER.debug("Starting background reconnection task")

        self._reconnect_task.cancel()
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
            c.ZDO.EndDeviceAnnceInd.Callback(partial=True), self.on_zdo_device_announce,
        )

        self._znp.callback_for_response(
            c.ZDO.TCDevInd.Callback.Callback(partial=True), self.on_zdo_tc_device_join,
        )

        self._znp.callback_for_response(
            c.ZDO.LeaveInd.Callback(partial=True), self.on_zdo_device_leave
        )

        self._znp.callback_for_response(
            c.ZDO.SrcRtgInd.Callback(partial=True), self.on_zdo_relays_message
        )

    def on_zdo_relays_message(self, msg: c.ZDO.SrcRtgInd.Callback) -> None:
        """
        ZDO source routing message callback
        """

        LOGGER.info("ZDO device relays: %s", msg)
        device = self.get_device(nwk=msg.DstAddr)
        device.relays = msg.Relays

    def on_zdo_device_announce(self, msg: c.ZDO.EndDeviceAnnceInd.Callback) -> None:
        """
        ZDO end device announcement callback
        """

        LOGGER.info("ZDO device announce: %s", msg)

        # We turn this back into a ZDO message and let zigpy handle it
        self._receive_zdo_message(
            cluster=ZDOCmd.Device_annce,
            tsn=0xFF,
            sender=self.get_device(ieee=msg.IEEE),
            NWKAddr=msg.NWK,
            IEEEAddr=msg.IEEE,
            Capability=msg.Capabilities,
        )

    def on_zdo_tc_device_join(self, msg: c.ZDO.TCDevInd.Callback) -> None:
        """
        ZDO trust center device join callback
        """

        LOGGER.info("TC device join: %s", msg)
        self.handle_join(nwk=msg.SrcNwk, ieee=msg.SrcIEEE, parent_nwk=msg.ParentNwk)

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
    def is_cc2531(self) -> bool:
        """
        There really are only two ZNP radios: the cheap CC2531 and the high-power ones.
        """

        return isinstance(self._nib, OldNIB)

    @property
    def znp_config(self) -> conf.ConfigType:
        """
        Shortcut property to access the ZNP radio config.
        """

        return self.config[conf.CONF_ZNP_CONFIG]

    async def _write_stack_settings(self, *, reset_if_changed: bool) -> None:
        """
        Writes network-independent Z-Stack settings to NVRAM.
        If no settings actually change, no reset will be performed.
        """

        # It's better to be explicit than rely on the NVRAM defaults
        settings = {
            NwkNvIds.LOGICAL_TYPE: t.DeviceLogicalType.Coordinator,
            # Source routing
            NwkNvIds.CONCENTRATOR_ENABLE: t.Bool(True),
            NwkNvIds.CONCENTRATOR_DISCOVERY: t.uint8_t(120),
            NwkNvIds.CONCENTRATOR_RC: t.Bool(True),
            NwkNvIds.SRC_RTG_EXPIRY_TIME: t.uint8_t(255),
            NwkNvIds.NWK_CHILD_AGE_ENABLE: t.Bool(False),
            # We want to receive all ZDO callbacks to proxy them back to zigpy
            NwkNvIds.ZDO_DIRECT_CB: t.Bool(True),
        }

        any_changed = False

        for nvid, value in settings.items():
            try:
                current_value = await self._znp.nvram_read(nvid)
            except InvalidCommandResponse:
                current_value = None

            # There is no point in issuing a write if the value will not change
            if current_value != value.serialize():
                await self._znp.nvram_write(nvid, value)
                any_changed = True

        if reset_if_changed and any_changed:
            # Reset to make the above NVRAM writes take effect
            await self._reset()

    @contextlib.asynccontextmanager
    async def _limit_concurrency(self):
        """
        Async context manager that prevents devices from being overwhelmed by requests.
        Mainly a thin wrapper around `asyncio.Semaphore` that logs when it has to wait.

        TODO: it would be better to also delay requests in response to `TABLE_FULL`.
        """

        start_time = time.time()
        was_locked = self._concurrent_requests_semaphore.locked()

        if was_locked:
            LOGGER.debug("Max concurrency reached, delaying requests")

        async with self._concurrent_requests_semaphore:
            if was_locked:
                LOGGER.debug(
                    "Previously delayed request is now running, "
                    "delayed by %0.2f seconds",
                    time.time() - start_time,
                )

            yield

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
        zdo_args = []

        for name, field_type in zip(field_names, field_types):
            zdo_arg = zdo_kwargs[name]

            if issubclass(field_type, ZigpyStruct) and hasattr(ZigpyStruct, "_fields"):
                # Old-style zigpy structs do not have "copy constructors"
                new_obj = field_type()

                for field_name, _ in new_obj._fields:
                    setattr(new_obj, field_name, getattr(zdo_arg, field_name))
            else:
                new_obj = field_type(zdo_arg)

            zdo_args.append(zdo_arg)

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
                await self.startup()

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
        # Parsing the NIB struct gives us access to low-level info, like the channel
        self._nib = parse_nib(await self._znp.nvram_read(NwkNvIds.NIB))
        LOGGER.debug("Parsed NIB: %s", self._nib)

        # Util.GetNvInfo reads all of these but it has an endianness bug with CHANLIST
        self._pan_id, _ = t.PanId.deserialize(
            await self._znp.nvram_read(NwkNvIds.PANID)
        )
        self._channels, _ = t.Channels.deserialize(
            await self._znp.nvram_read(NwkNvIds.CHANLIST)
        )
        self._ext_pan_id, _ = t.EUI64.deserialize(
            await self._znp.nvram_read(NwkNvIds.EXTENDED_PAN_ID)
        )

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

        candidates = []

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

        if not candidates:
            raise ValueError(
                f"Could not pick endpoint for dst_ep={dst_ep},"
                f" profile={profile}, and cluster={cluster}"
            )

        # XXX: pick the first one?
        return candidates[0]

    async def _send_zdo_request(
        self, dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
    ):
        """
        Zigpy doesn't send ZDO requests via TI's ZDO_* MT commands,
        so it will never receive a reply because ZNP intercepts ZDO replies, never
        sends a DataConfirm, and instead replies with one of its ZDO_* MT responses.

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

        device = self.get_device(nwk=dst_addr.address)

        if cluster not in ZDO_CONVERTERS:
            LOGGER.error(
                "ZDO converter for cluster %s has not been implemented!"
                " Please open a GitHub issue and attach a debug log:"
                " https://github.com/zha-ng/zigpy-znp/issues/new",
                cluster,
            )
            return t.Status.FAILURE, "No ZDO converter"

        # Call the converter with the ZDO request's kwargs
        req_factory, rsp_factory, zdo_rsp_factory = ZDO_CONVERTERS[cluster]
        request = req_factory(dst_addr.address, device, **zdo_kwargs)
        callback = rsp_factory(dst_addr.address)

        LOGGER.debug(
            "Intercepted AP ZDO request %s(%s) and replaced with %s",
            cluster,
            zdo_kwargs,
            request,
        )

        try:
            async with self._limit_concurrency():
                async with async_timeout.timeout(ZDO_REQUEST_TIMEOUT):
                    response = await self._znp.request_callback_rsp(
                        request=request, RspStatus=t.Status.SUCCESS, callback=callback
                    )
        except InvalidCommandResponse as e:
            raise DeliveryError(f"Could not send command: {e.response.Status}") from e

        zdo_rsp_cluster, zdo_response_kwargs = zdo_rsp_factory(response)

        self._receive_zdo_message(
            cluster=zdo_rsp_cluster, tsn=sequence, sender=device, **zdo_response_kwargs
        )

        return response.Status, "Request sent successfully"

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
        Used by `request`/`mrequest`/`broadcast` to send a request.
        Picks the correct request sending mechanism and fixes endpoint information.
        """

        if dst_ep == ZDO_ENDPOINT and not (
            cluster == ZDOCmd.Mgmt_Permit_Joining_req
            and dst_addr.mode == t.AddrMode.Broadcast
        ):
            return await self._send_zdo_request(
                dst_addr, dst_ep, src_ep, cluster, sequence, options, radius, data
            )

        # Zigpy just sets src == dst, which doesn't work for devices with many endpoints
        # We pick ours based on the registered endpoints.
        src_ep = self._find_endpoint(dst_ep=dst_ep, profile=profile, cluster=cluster)

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

        if dst_addr.mode == t.AddrMode.Broadcast:
            # We won't always get a data confirmation
            response = await self._znp.request(
                request=request, RspStatus=t.Status.SUCCESS
            )
        else:
            async with self._limit_concurrency():
                async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
                    response = await self._znp.request_callback_rsp(
                        request=request,
                        RspStatus=t.Status.SUCCESS,
                        callback=c.AF.DataConfirm.Callback(partial=True, TSN=sequence),
                    )

                LOGGER.debug("Received a data request confirmation: %s", response)

        if response.Status != t.Status.SUCCESS:
            LOGGER.warning("Failed to send request %s: %s", request, response.Status)
            return response.Status, "Invalid response status"

        return response.Status, "Request sent successfully"
