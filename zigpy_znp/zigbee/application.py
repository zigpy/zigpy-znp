from __future__ import annotations

import os
import time
import asyncio
import logging
import itertools
import contextlib

import zigpy.zcl
import zigpy.zdo
import zigpy.util
import zigpy.state
import zigpy.types
import zigpy.config
import zigpy.device
import async_timeout
import zigpy.profiles
import zigpy.zdo.types as zdo_t
import zigpy.application
from zigpy.types import deserialize as list_deserialize
from zigpy.exceptions import DeliveryError

import zigpy_znp.const as const
import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
from zigpy_znp.types import AddrMode
from zigpy_znp.utils import combine_concurrent_calls
from zigpy_znp.exceptions import CommandNotRecognized, InvalidCommandResponse
from zigpy_znp.types.nvids import OsalNvIds
from zigpy_znp.zigbee.device import ZNPCoordinator

ZDO_ENDPOINT = 0
ZHA_ENDPOINT = 1
ZDO_PROFILE = 0x0000

# All of these are in seconds
PROBE_TIMEOUT = 5
STARTUP_TIMEOUT = 5
DATA_CONFIRM_TIMEOUT = 8
IEEE_ADDR_DISCOVERY_TIMEOUT = 5
DEVICE_JOIN_MAX_DELAY = 5
WATCHDOG_PERIOD = 30

REQUEST_MAX_RETRIES = 5
REQUEST_ERROR_RETRY_DELAY = 0.5

# Errors that go away on their own after waiting for a bit
REQUEST_TRANSIENT_ERRORS = {
    t.Status.BUFFER_FULL,
    t.Status.MAC_CHANNEL_ACCESS_FAILURE,
    t.Status.MAC_TRANSACTION_OVERFLOW,
    t.Status.MAC_NO_RESOURCES,
    t.Status.MEM_ERROR,
    t.Status.NWK_TABLE_FULL,
}

REQUEST_ROUTING_ERRORS = {
    t.Status.APS_NO_ACK,
    t.Status.APS_NOT_AUTHENTICATED,
    t.Status.NWK_NO_ROUTE,
    t.Status.NWK_INVALID_REQUEST,
    t.Status.MAC_NO_ACK,
    t.Status.MAC_TRANSACTION_EXPIRED,
}

REQUEST_RETRYABLE_ERRORS = REQUEST_TRANSIENT_ERRORS | REQUEST_ROUTING_ERRORS

LOGGER = logging.getLogger(__name__)


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA
    SCHEMA_DEVICE = conf.SCHEMA_DEVICE

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=conf.CONFIG_SCHEMA(config))

        self._znp: ZNP | None = None

        # It's simpler to work with Task objects if they're never actually None
        self._reconnect_task: asyncio.Future = asyncio.Future()
        self._reconnect_task.cancel()

        self._watchdog_task: asyncio.Future = asyncio.Future()
        self._watchdog_task.cancel()

        self._version_rsp = None
        self._concurrent_requests_semaphore = None
        self._currently_waiting_requests = 0

        self._join_announce_tasks: dict[t.EUI64, asyncio.TimerHandle] = {}

    ##################################################################
    # Implementation of the core zigpy ControllerApplication methods #
    ##################################################################

    @classmethod
    async def probe(cls, device_config):
        try:
            async with async_timeout.timeout(PROBE_TIMEOUT):
                return await super().probe(device_config)
        except asyncio.TimeoutError:
            return False

    async def connect(self):
        assert self._znp is None

        znp = ZNP(self.config)
        await znp.connect()

        # We only assign `self._znp` after it has successfully connected
        self._znp = znp
        self._znp.set_application(self)

        self._bind_callbacks()

    async def disconnect(self):
        self._reconnect_task.cancel()
        self._watchdog_task.cancel()

        if self._znp is not None:
            try:
                await self._znp.reset(wait_for_reset=False)
            except Exception as e:
                LOGGER.warning("Failed to reset before disconnect: %s", e)
            finally:
                self._znp.close()
                self._znp = None

    def close(self):
        self._reconnect_task.cancel()
        self._watchdog_task.cancel()

        # This will close the UART, which will then close the transport
        if self._znp is not None:
            self._znp.close()
            self._znp = None

    async def add_endpoint(self, descriptor: zdo_t.SimpleDescriptor) -> None:
        """
        Registers a new endpoint on the device.
        """

        await self._znp.request(
            c.AF.Register.Req(
                Endpoint=descriptor.endpoint,
                ProfileId=descriptor.profile,
                DeviceId=descriptor.device_type,
                DeviceVersion=descriptor.device_version,
                LatencyReq=c.af.LatencyReq.NoLatencyReqs,
                InputClusters=descriptor.input_clusters,
                OutputClusters=descriptor.output_clusters,
            ),
            RspStatus=t.Status.SUCCESS,
        )

    async def load_network_info(self, *, load_devices=False) -> None:
        """
        Loads network information from NVRAM.
        """

        await self._znp.load_network_info(load_devices=load_devices)

        self.state.node_info = self._znp.node_info
        self.state.network_info = self._znp.network_info

    async def write_network_info(
        self,
        *,
        network_info: zigpy.state.NetworkInfo,
        node_info: zigpy.state.NodeInfo,
    ) -> None:
        """
        Writes network and node state to NVRAM.
        """

        network_info.stack_specific.setdefault("zstack", {})

        if "tclk_seed" not in network_info.stack_specific["zstack"]:
            network_info.stack_specific["zstack"]["tclk_seed"] = os.urandom(16).hex()

        return await self._znp.write_network_info(
            network_info=network_info, node_info=node_info
        )

    async def start_network(self, *, read_only=False):
        if self.state.node_info == zigpy.state.NodeInfo():
            await self.load_network_info()

        if not read_only:
            await self._znp.migrate_nvram()
            await self._write_stack_settings()

        await self._znp.reset()

        if self.znp_config[conf.CONF_TX_POWER] is not None:
            await self.set_tx_power(dbm=self.znp_config[conf.CONF_TX_POWER])

        await self._znp.start_network()

        self._version_rsp = await self._znp.request(c.SYS.Version.Req())

        # The CC2531 running Z-Stack Home 1.2 overrides the LED setting if it is changed
        # before the coordinator has started.
        if self.znp_config[conf.CONF_LED_MODE] is not None:
            await self._set_led_mode(led=0xFF, mode=self.znp_config[conf.CONF_LED_MODE])

        await self.register_endpoints()

        # Receive a callback for every known ZDO command
        for cluster_id in zdo_t.ZDOCmd:
            # Ignore outgoing ZDO requests, only receive announcements and responses
            if cluster_id.name.endswith(("_req", "_set")):
                continue

            await self._znp.request(c.ZDO.MsgCallbackRegister.Req(ClusterId=cluster_id))

        # Setup the coordinator as a zigpy device and initialize it to request node info
        self.devices[self.state.node_info.ieee] = ZNPCoordinator(
            self, self.state.node_info.ieee, self.state.node_info.nwk
        )
        await self._device.schedule_initialize()

        # Now that we know what device we are, set the max concurrent requests
        if self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS] == "auto":
            max_concurrent_requests = 16 if self._znp.nvram.align_structs else 2
        else:
            max_concurrent_requests = self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS]

        self._concurrent_requests_semaphore = asyncio.Semaphore(max_concurrent_requests)

        if self.state.network_info.network_key.key == const.Z2M_NETWORK_KEY:
            LOGGER.warning(
                "Your network is using the insecure Zigbee2MQTT network key!"
            )

        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def set_tx_power(self, dbm: int) -> None:
        """
        Sets the radio TX power.
        """

        rsp = await self._znp.request(c.SYS.SetTxPower.Req(TXPower=dbm))

        if self._znp.version >= 3.30 and rsp.StatusOrPower != t.Status.SUCCESS:
            # Z-Stack 3's response indicates success or failure
            raise InvalidCommandResponse(
                f"Failed to set TX power: {t.Status(rsp.StatusOrPower & 0xFF)!r}", rsp
            )
        elif self._znp.version < 3.30 and rsp.StatusOrPower != dbm:
            # Old Z-Stack releases used the response status field to indicate the power
            # setting that was actually applied
            LOGGER.warning(
                "Requested TX power %d was adjusted to %d", dbm, rsp.StatusOrPower
            )

    def get_dst_address(self, cluster: zigpy.zcl.Cluster) -> zdo_t.MultiAddress:
        """
        Helper to get a dst address for bind/unbind operations.

        Allows radios to provide correct information, especially for radios which listen
        on specific endpoints only.
        """

        dst_addr = zdo_t.MultiAddress()
        dst_addr.addrmode = 0x03
        dst_addr.ieee = self.state.node_info.ieee
        dst_addr.endpoint = self._find_endpoint(
            dst_ep=cluster.endpoint.endpoint_id,
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
    ) -> tuple[t.Status, str]:
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
    ) -> tuple[t.Status, str]:
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
    ) -> tuple[t.Status, str]:
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

    async def permit(self, time_s: int = 60, node: t.EUI64 = None):
        """
        Permit joining the network via a specific node or via all router nodes.
        """

        LOGGER.info("Permitting joins for %d seconds", time_s)

        # If joins were permitted through a specific router, older Z-Stack builds
        # did not allow the key to be distributed unless the coordinator itself was
        # also permitting joins. This also needs to happen if we're permitting joins
        # through the coordinator itself.
        #
        # Fixed in https://github.com/Koenkk/Z-Stack-firmware/commit/efac5ee46b9b437
        if (
            time_s == 0
            or self._zstack_build_id < 20210708
            or node == self.state.node_info.ieee
        ):
            response = await self._znp.request_callback_rsp(
                request=c.ZDO.MgmtPermitJoinReq.Req(
                    AddrMode=t.AddrMode.NWK,
                    Dst=self.state.node_info.nwk,
                    Duration=time_s,
                    TCSignificance=1,
                ),
                RspStatus=t.Status.SUCCESS,
                callback=c.ZDO.MgmtPermitJoinRsp.Callback(
                    Src=self.state.node_info.nwk, partial=True
                ),
            )

            if response.Status != t.Status.SUCCESS:
                raise RuntimeError(f"Failed to permit joins on coordinator: {response}")

        await super().permit(time_s=time_s, node=node)

    async def permit_ncp(self, time_s: int) -> None:
        """
        Permits joins only on the coordinator.
        """

        # Z-Stack does not need any special code to do this

    async def force_remove(self, dev: zigpy.device.Device) -> None:
        """
        Send a lower-level leave command to the device
        """

        # Z-Stack does not have any way to do this

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

        LOGGER.debug("Connection lost: %s", exc)

        self.close()

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

        self._znp.callback_for_response(
            c.ZDO.MsgCbIncoming.Callback(partial=True), self.on_zdo_message
        )

        # These are responses to a broadcast but we ignore all but the first
        self._znp.callback_for_response(
            c.ZDO.IEEEAddrRsp.Callback(partial=True),
            self.on_intentionally_unhandled_message,
        )

    def on_intentionally_unhandled_message(self, msg: t.CommandBase) -> None:
        """
        Some commands are unhandled but frequently sent by devices on the network. To
        reduce unnecessary logging messages, they are given an explicit callback.
        """

    async def on_zdo_message(self, msg: c.ZDO.MsgCbIncoming.Callback) -> None:
        """
        Global callback for all ZDO messages.
        """

        message = t.uint8_t(msg.TSN).serialize() + msg.Data
        hdr, data = zdo_t.ZDOHeader.deserialize(msg.ClusterId, message)
        names, types = zdo_t.CLUSTERS[msg.ClusterId]
        args, data = list_deserialize(data, types)
        kwargs = dict(zip(names, args))

        if msg.ClusterId == zdo_t.ZDOCmd.Device_annce:
            self.on_zdo_device_announce(*args)
            device = self.get_device(ieee=kwargs["IEEEAddr"])
        else:
            try:
                device = await self._get_or_discover_device(nwk=msg.Src)
            except KeyError:
                LOGGER.warning(
                    "Received a ZDO message from an unknown device: %s", msg.Src
                )
                return

        self.handle_message(
            sender=device,
            profile=ZDO_PROFILE,
            cluster=msg.ClusterId,
            src_ep=ZDO_ENDPOINT,
            dst_ep=ZDO_ENDPOINT,
            message=message,
        )

    def on_zdo_permit_join_message(self, msg: c.ZDO.PermitJoinInd.Callback) -> None:
        """
        Coordinator join status change message. Only sent with Z-Stack 1.2 and 3.0.
        """

        if msg.Duration == 0:
            LOGGER.info("Coordinator is not permitting joins anymore")
        else:
            LOGGER.info("Coordinator is permitting joins for %d seconds", msg.Duration)

    async def on_zdo_relays_message(self, msg: c.ZDO.SrcRtgInd.Callback) -> None:
        """
        ZDO source routing message callback
        """

        try:
            device = await self._get_or_discover_device(nwk=msg.DstAddr)
        except KeyError:
            LOGGER.warning(
                "Received a ZDO message from an unknown device: %s", msg.DstAddr
            )
            return

        # `relays` is a property with a setter that emits an event
        device.relays = msg.Relays

    def on_zdo_device_announce(self, nwk: t.NWK, ieee: t.EUI64, capabilities) -> None:
        """
        ZDO end device announcement callback
        """

        LOGGER.info(
            "ZDO device announce: nwk=%s, ieee=%s, capabilities=%s",
            nwk,
            ieee,
            capabilities,
        )

        # Cancel an existing join timer so we don't double announce
        if ieee in self._join_announce_tasks:
            self._join_announce_tasks.pop(ieee).cancel()

        # Sometimes devices change their NWK when announcing so re-join it.
        self.handle_join(nwk=nwk, ieee=ieee, parent_nwk=None)

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

        # If the device already exists, immediately trigger a join to update its NWK.
        try:
            self.get_device(ieee=msg.SrcIEEE)
        except KeyError:
            pass
        else:
            self.handle_join(
                nwk=msg.SrcNwk,
                ieee=msg.SrcIEEE,
                parent_nwk=msg.ParentNwk,
            )
            return

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

    async def on_af_message(self, msg: c.AF.IncomingMsg.Callback) -> None:
        """
        Handler for all non-ZDO messages.
        """

        try:
            device = await self._get_or_discover_device(nwk=msg.SrcAddr)
        except KeyError:
            LOGGER.warning(
                "Received an AF message from an unknown device: %s", msg.SrcAddr
            )
            return

        device.radio_details(lqi=msg.LQI, rssi=None)

        # XXX: Is it possible to receive messages on non-assigned endpoints?
        if msg.DstEndpoint in self._device.endpoints:
            profile = self._device.endpoints[msg.DstEndpoint].profile_id
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
    def _zstack_build_id(self) -> t.uint32_t:
        """
        Z-Stack build ID, more recently the build date.
        """

        # Old versions of Z-Stack do not include `CodeRevision` in the version response
        if self._version_rsp.CodeRevision is None:
            return t.uint32_t(0x00000000)

        return self._version_rsp.CodeRevision

    @property
    def znp_config(self) -> conf.ConfigType:
        """
        Shortcut property to access the ZNP radio config.
        """

        return self.config[conf.CONF_ZNP_CONFIG]

    async def _watchdog_loop(self):
        """
        Watchdog loop to periodically test if Z-Stack is still running.
        """

        LOGGER.debug("Starting watchdog loop")

        while True:
            await asyncio.sleep(WATCHDOG_PERIOD)

            # No point in trying to test the port if it's already disconnected
            if self._znp is None:
                break

            try:
                await self._znp.request(c.SYS.Ping.Req())
            except Exception as e:
                LOGGER.error(
                    "Watchdog check failed",
                    exc_info=e,
                )

                # Treat the watchdog failure as a disconnect
                self.connection_lost(e)

                return

    @combine_concurrent_calls
    async def _get_or_discover_device(self, nwk: t.NWK) -> zigpy.device.Device:
        """
        Finds a device by its NWK address. If a device does not exist in the zigpy
        database, attempt to look up its new NWK address. If it does not exist in the
        zigpy database, treat the device as a new join.
        """

        try:
            return self.get_device(nwk=nwk)
        except KeyError:
            pass

        LOGGER.debug("Device with NWK 0x%04X not in database", nwk)

        try:
            async with async_timeout.timeout(IEEE_ADDR_DISCOVERY_TIMEOUT):
                ieee_addr_rsp = await self._znp.request_callback_rsp(
                    request=c.ZDO.IEEEAddrReq.Req(
                        NWK=nwk,
                        RequestType=c.zdo.AddrRequestType.SINGLE,
                        StartIndex=0,
                    ),
                    RspStatus=t.Status.SUCCESS,
                    callback=c.ZDO.IEEEAddrRsp.Callback(partial=True, NWK=nwk),
                )
        except asyncio.TimeoutError:
            raise KeyError(f"Unknown device: 0x{nwk:04X}")
        else:
            ieee = ieee_addr_rsp.IEEE

        try:
            device = self.get_device(ieee=ieee)
        except KeyError:
            LOGGER.debug("Treating unknown device as a new join")
            self.handle_join(nwk=nwk, ieee=ieee, parent_nwk=None)

            return self.get_device(ieee=ieee)

        # The `Device` object could have been updated while this coroutine is running
        if device.nwk == nwk:
            return device

        LOGGER.warning(
            "Device %s changed its NWK from %s to %s",
            device.ieee,
            device.nwk,
            nwk,
        )

        # Notify zigpy of the change
        self.handle_join(nwk=nwk, ieee=ieee, parent_nwk=None)

        # `handle_join` will update the NWK
        assert device.nwk == nwk

        return device

    async def _set_led_mode(self, *, led: t.uint8_t, mode: c.util.LEDMode) -> None:
        """
        Attempts to set the provided LED's mode. A Z-Stack bug causes the underlying
        command to never receive a response if the board has no LEDs, requiring this
        wrapper function to prevent the command from taking many seconds to time out.
        """

        # XXX: If Z-Stack is not compiled with HAL_LED, it will just not respond at all
        try:
            async with async_timeout.timeout(0.5):
                await self._znp.request(
                    c.UTIL.LEDControl.Req(LED=led, Mode=mode),
                    RspStatus=t.Status.SUCCESS,
                )
        except (asyncio.TimeoutError, CommandNotRecognized):
            LOGGER.info("This build of Z-Stack does not appear to support LED control")

    async def _write_stack_settings(self) -> bool:
        """
        Writes network-independent Z-Stack settings to NVRAM.
        If no settings actually change, no reset will be performed.
        """

        # It's better to be explicit than rely on the NVRAM defaults
        settings = {
            OsalNvIds.LOGICAL_TYPE: t.uint8_t(self.state.node_info.logical_type),
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
                current_value = await self._znp.nvram.osal_read(
                    nvid, item_type=type(value)
                )
            except InvalidCommandResponse:
                current_value = None

            # There is no point in issuing a write if the value will not change
            if current_value != value:
                await self._znp.nvram.osal_write(nvid, value)
                any_changed = True

        return any_changed

    @contextlib.asynccontextmanager
    async def _limit_concurrency(self):
        """
        Async context manager that prevents devices from being overwhelmed by requests.
        Mainly a thin wrapper around `asyncio.Semaphore` that logs when it has to wait.
        """

        # Allow sending some requests before the application has fully started
        if self._concurrent_requests_semaphore is None:
            yield
            return

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
                await self.connect()
                await self.initialize()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                LOGGER.error("Failed to reconnect", exc_info=e)

                if self._znp is not None:
                    self._znp.close()
                    self._znp = None

                await asyncio.sleep(
                    self._config[conf.CONF_ZNP_CONFIG][
                        conf.CONF_AUTO_RECONNECT_RETRY_DELAY
                    ]
                )

    def _find_endpoint(self, dst_ep: int, profile: int, cluster: int) -> int:
        """
        Zigpy defaults to sending messages with src_ep == dst_ep. This does not work
        with all versions of Z-Stack, which requires endpoints to be registered
        explicitly on startup.
        """

        if dst_ep == ZDO_ENDPOINT:
            return ZDO_ENDPOINT

        # Newer Z-Stack releases ignore profiles and will work properly with endpoint 1
        if self._zstack_build_id >= 20210708:
            return ZHA_ENDPOINT

        # Always fall back to endpoint 1
        candidates = [ZHA_ENDPOINT]

        for ep_id, endpoint in self._device.endpoints.items():
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

        # Zigpy just sets src == dst, which doesn't work for devices with many endpoints
        # We pick ours based on the registered endpoints when using an older firmware
        src_ep = self._find_endpoint(dst_ep=dst_ep, profile=profile, cluster=cluster)

        if relays is None:
            if dst_addr.mode == AddrMode.NWK and len(data) < 128:
                request = c.AF.DataRequest.Req(
                    DstAddr=dst_addr.address,
                    DstEndpoint=dst_ep,
                    SrcEndpoint=src_ep,
                    ClusterId=cluster,
                    TSN=sequence,
                    Options=options,
                    Radius=radius,
                    Data=data,
                )
            else:
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

        # Z-Stack requires special treatment when sending ZDO requests
        if dst_ep == ZDO_ENDPOINT:
            # XXX: Joins *must* be sent via a ZDO command, even if they are directly
            # addressing another device. The router will receive the ZDO request and a
            # device will try to join, but Z-Stack will never send the network key.
            if cluster == zdo_t.ZDOCmd.Mgmt_Permit_Joining_req:
                if dst_addr.mode == t.AddrMode.Broadcast:
                    # The coordinator responds to broadcasts
                    permit_addr = self.state.node_info.nwk
                else:
                    # Otherwise, the destination device responds
                    permit_addr = dst_addr.address

                await self._znp.request_callback_rsp(
                    request=c.ZDO.MgmtPermitJoinReq.Req(
                        AddrMode=dst_addr.mode,
                        Dst=dst_addr.address,
                        Duration=data[1],
                        TCSignificance=data[2],
                    ),
                    RspStatus=t.Status.SUCCESS,
                    callback=c.ZDO.MgmtPermitJoinRsp.Callback(
                        Src=permit_addr, partial=True
                    ),
                )
            # Internally forward ZDO requests destined for the coordinator back to zigpy
            # so we can send internal Z-Stack requests when necessary
            elif (
                # Broadcast that will reach the device
                dst_addr.mode == t.AddrMode.Broadcast
                and dst_addr.address
                in (
                    zigpy.types.BroadcastAddress.ALL_DEVICES,
                    zigpy.types.BroadcastAddress.RX_ON_WHEN_IDLE,
                    zigpy.types.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
                )
            ) or (
                # Or a direct unicast request
                dst_addr.mode == t.AddrMode.NWK
                and dst_addr.address == self._device.nwk
            ):
                self.handle_message(
                    sender=self._device,
                    profile=profile,
                    cluster=cluster,
                    src_ep=src_ep,
                    dst_ep=dst_ep,
                    message=data,
                )

        if dst_ep == ZDO_ENDPOINT or dst_addr.mode == t.AddrMode.Broadcast:
            # Broadcasts and ZDO requests will not receive a confirmation
            response = await self._znp.request(
                request=request, RspStatus=t.Status.SUCCESS
            )
        else:
            async with async_timeout.timeout(DATA_CONFIRM_TIMEOUT):
                # Shield from cancellation to prevent requests that time out in higher
                # layers from missing expected responses
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
                        # Multicasts eventually receive a confirmation but waiting for
                        # it is unnecessary
                        background=(dst_addr.mode == t.AddrMode.Group),
                    )
                )

                # Both the callback and the response can have an error status
                if response.Status != t.Status.SUCCESS:
                    raise InvalidCommandResponse(
                        f"Unsuccessful request status code: {response.Status!r}",
                        response,
                    )

        return response

    @combine_concurrent_calls
    async def _discover_route(self, nwk: t.NWK) -> None:
        """
        Instructs the coordinator to re-discover routes to the provided NWK.
        Runs concurrently and at most once per NWK, even if called multiple times.
        """

        # Route discovery with Z-Stack 1.2 and Z-Stack 3.0.2 on the CC2531 doesn't
        # appear to work very well (Z2M#2901)
        if self._znp.version < 3.30:
            return

        await self._znp.request(
            c.ZDO.ExtRouteDisc.Req(
                Dst=nwk,
                Options=c.zdo.RouteDiscoveryOptions.UNICAST,
                Radius=30,
            ),
        )

        await asyncio.sleep(0.1 * 13)

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
    ) -> tuple[t.Status, str]:
        """
        Fault-tolerant wrapper around `_send_request_raw` that transparently attempts to
        repair routes and contact the device through other methods when Z-Stack errors
        are encountered.
        """

        try:
            if dst_addr.mode == t.AddrMode.NWK:
                device = self.get_device(nwk=dst_addr.address)
            elif dst_addr.mode == t.AddrMode.IEEE:
                device = self.get_device(ieee=dst_addr.address)
            else:
                device = None
        except KeyError:
            # Sometimes a request is sent to a device not in the database. This should
            # work, the device object is only for recovery.
            device = None

        status = None
        response = None
        association = None
        force_relays = None

        tried_assoc_remove = False
        tried_route_discovery = False
        tried_last_good_route = False
        tried_ieee_address = False

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
                            and dst_addr.address != self.state.node_info.nwk
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

                        # Just retry if:
                        #  - this is our first failure
                        #  - the error is transient and is not a routing issue
                        #  - or we are not sending a unicast request
                        if (
                            attempt == 0
                            or status in REQUEST_TRANSIENT_ERRORS
                            or dst_addr.mode not in (t.AddrMode.NWK, t.AddrMode.IEEE)
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

                        # If we fail to contact the device with its IEEE address, don't
                        # try again.
                        if (
                            tried_ieee_address
                            and dst_addr.mode == t.AddrMode.IEEE
                            and device is not None
                        ):
                            dst_addr = t.AddrModeAddress(
                                mode=t.AddrMode.NWK,
                                address=device.nwk,
                            )

                        # Child aging is disabled so if a child switches parents from
                        # the coordinator to another router, we will not be able to
                        # re-discover a route to it. We have to manually drop the child
                        # to do this.
                        if (
                            status == t.Status.MAC_TRANSACTION_EXPIRED
                            and device is not None
                            and association is None
                            and not tried_assoc_remove
                            and self._znp.version >= 3.30
                        ):
                            association = await self._znp.request(
                                c.UTIL.AssocGetWithAddress.Req(
                                    IEEE=device.ieee,
                                    NWK=0x0000,  # IEEE takes priority
                                )
                            )

                            if (
                                association.Device.nodeRelation
                                != c.util.NodeRelation.NOTUSED
                            ):
                                try:
                                    await self._znp.request(
                                        c.UTIL.AssocRemove.Req(IEEE=device.ieee)
                                    )
                                    tried_assoc_remove = True

                                    # Route discovery must be performed right after
                                    await self._discover_route(device.nwk)
                                except CommandNotRecognized:
                                    LOGGER.debug(
                                        "The UTIL.AssocRemove command is available only"
                                        " in Z-Stack 3 releases built after 20201017"
                                    )
                        elif not tried_last_good_route and device is not None:
                            # `ZDO.SrcRtgInd` callbacks tell us the last path taken by
                            # messages from the device back to the coordinator. Sending
                            # packets backwards via this same route may work.
                            force_relays = (device.relays or [])[::-1]
                            tried_last_good_route = True
                        elif (
                            not tried_route_discovery
                            and dst_addr.mode == t.AddrMode.NWK
                        ):
                            # If that doesn't work, try re-discovering the route.
                            # While we can in theory poll and wait until it is fixed,
                            # letting the retry mechanism deal with it simpler.
                            await self._discover_route(dst_addr.address)
                            tried_route_discovery = True
                        elif (
                            not tried_ieee_address
                            and device is not None
                            and dst_addr.mode == t.AddrMode.NWK
                        ):
                            # Try using the device's IEEE address instead of its NWK.
                            # If it works, the NWK will be updated when relays arrive.
                            tried_ieee_address = True
                            dst_addr = t.AddrModeAddress(
                                mode=t.AddrMode.IEEE,
                                address=device.ieee,
                            )

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
                    c.UTIL.AssocAdd.Req(
                        NWK=association.Device.shortAddr,
                        IEEE=device.ieee,
                        NodeRelation=association.Device.nodeRelation,
                    )
                )

        if response.Status != t.Status.SUCCESS:
            return response.Status, "Failed to send request"

        return response.Status, "Sent request successfully"
