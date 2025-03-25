from __future__ import annotations

import os
import sys
import asyncio
import logging

import zigpy.zcl
import zigpy.zdo
import zigpy.util
import zigpy.state
import zigpy.types
import zigpy.config
import zigpy.device

if sys.version_info[:2] < (3, 11):
    from async_timeout import timeout as asyncio_timeout  # pragma: no cover
else:
    from asyncio import timeout as asyncio_timeout  # pragma: no cover

import zigpy.profiles
import zigpy.zdo.types as zdo_t
import zigpy.application
import zigpy.config.defaults
from zigpy.exceptions import DeliveryError

import zigpy_znp.const as const
import zigpy_znp.types as t
import zigpy_znp.config as conf
import zigpy_znp.commands as c
from zigpy_znp.api import ZNP
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
EXTENDED_DATA_CONFIRM_TIMEOUT = 30
DEVICE_JOIN_MAX_DELAY = 5

LOGGER = logging.getLogger(__name__)


class RetryMethod(t.bitmap8):
    NONE = 0
    AssocRemove = 2 << 0


class ControllerApplication(zigpy.application.ControllerApplication):
    SCHEMA = conf.CONFIG_SCHEMA

    def __init__(self, config: conf.ConfigType):
        super().__init__(config=config)

        self._znp: ZNP | None = None
        self._version_rsp = None
        self._join_announce_tasks: dict[t.EUI64, asyncio.TimerHandle] = {}

    ##################################################################
    # Implementation of the core zigpy ControllerApplication methods #
    ##################################################################

    @classmethod
    async def probe(cls, device_config):
        try:
            async with asyncio_timeout(PROBE_TIMEOUT):
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
        if self._znp is not None:
            try:
                await self._znp.reset(wait_for_reset=False)
            except Exception as e:
                LOGGER.warning("Failed to reset before disconnect: %s", e)
            finally:
                await self._znp.disconnect()
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

    async def reset_network_info(self) -> None:
        """
        Resets node network information and leaves the current network.
        """

        await self._znp.reset_network_info()

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

        await self._znp.write_network_info(
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
        await self._znp.request(c.ZDO.MsgCallbackRegister.Req(ClusterId=0xFFFF))

        # Setup the coordinator as a zigpy device and initialize it to request node info
        self.devices[self.state.node_info.ieee] = ZNPCoordinator(
            self, self.state.node_info.ieee, self.state.node_info.nwk
        )
        await self._device.schedule_initialize()

        # Deprecate ZNP-specific config
        if self.znp_config[conf.CONF_MAX_CONCURRENT_REQUESTS] is not None:
            raise RuntimeError(
                "`zigpy_config:znp_config:max_concurrent_requests` is deprecated,"
                " move this key up to `zigpy_config:max_concurrent_requests` instead."
            )

        # Now that we know what device we are, set the max concurrent requests
        if self._config[conf.CONF_MAX_CONCURRENT_REQUESTS] in (
            None,
            zigpy.config.defaults.CONF_MAX_CONCURRENT_REQUESTS_DEFAULT,
        ):
            max_concurrent_requests = 16 if self._znp.nvram.align_structs else 2
        else:
            max_concurrent_requests = self._config[conf.CONF_MAX_CONCURRENT_REQUESTS]

        # Update the max value of the concurrent request semaphore at runtime
        self._concurrent_requests_semaphore.max_value = max_concurrent_requests

        if self.state.network_info.network_key.key == const.Z2M_NETWORK_KEY:
            LOGGER.warning(
                "Your network is using the insecure Zigbee2MQTT network key!"
            )

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

    async def permit_with_link_key(
        self, node: t.EUI64, link_key: t.KeyData, time_s: int = 60
    ) -> None:
        """
        Permits a new device to join with the given IEEE and link key.
        """

        await self._znp.request(
            c.AppConfig.BDBAddInstallCode.Req(
                InstallCodeFormat=(
                    c.app_config.InstallCodeFormat.KeyDerivedFromInstallCode
                ),
                IEEE=node,
                InstallCode=link_key.serialize(),
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

    async def _move_network_to_channel(
        self, new_channel: int, new_nwk_update_id: int
    ) -> None:
        """Moves device to a new channel."""
        await self._znp.request(
            request=c.ZDO.MgmtNWKUpdateReq.Req(
                Dst=0x0000,
                DstAddrMode=t.AddrMode.NWK,
                Channels=t.Channels.from_channel_list([new_channel]),
                ScanDuration=zdo_t.NwkUpdate.CHANNEL_CHANGE_REQ,
                ScanCount=0,
                NwkManagerAddr=0x0000,
                # `new_nwk_update_id` is ignored
            ),
            RspStatus=t.Status.SUCCESS,
        )

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

        try:
            zdo_t.ZDOCmd(msg.ClusterId)
        except ValueError:
            pass
        else:
            # Ignore loopback ZDO requests, only receive announcements and responses
            if zdo_t.ZDOCmd(msg.ClusterId).name.endswith(("_req", "_set")):
                LOGGER.debug("Ignoring loopback ZDO request")
                return

        if msg.IsBroadcast:
            dst = zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.Broadcast,
                address=zigpy.types.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
            )
        else:
            dst = zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.NWK,
                address=self.state.node_info.nwk,
            )

        packet = zigpy.types.ZigbeePacket(
            src=zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.NWK,
                address=msg.Src,
            ),
            src_ep=ZDO_ENDPOINT,
            dst=dst,
            dst_ep=ZDO_ENDPOINT,
            tsn=msg.TSN,
            profile_id=ZDO_PROFILE,
            cluster_id=msg.ClusterId,
            data=t.SerializableBytes(t.uint8_t(msg.TSN).serialize() + msg.Data),
            tx_options=(
                zigpy.types.TransmitOptions.APS_Encryption
                if msg.SecurityUse
                else zigpy.types.TransmitOptions.NONE
            ),
        )

        # Peek into the ZDO packet so that we can cancel our existing TC join timer when
        # a device actually sends an announcemement
        try:
            zdo_hdr, zdo_args = self._device.zdo.deserialize(
                cluster_id=packet.cluster_id, data=packet.data.serialize()
            )
        except Exception:
            LOGGER.warning("Failed to deserialize ZDO packet", exc_info=True)
        else:
            if zdo_hdr.command_id == zdo_t.ZDOCmd.Device_annce:
                _, ieee, _ = zdo_args

                # Cancel any existing TC join timers so we don't double announce
                if ieee in self._join_announce_tasks:
                    self._join_announce_tasks.pop(ieee).cancel()

        self.packet_received(packet)

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

        self.handle_relays(nwk=msg.DstAddr, relays=msg.Relays)

    def on_zdo_tc_device_join(self, msg: c.ZDO.TCDevInd.Callback) -> None:
        """
        ZDO trust center device join callback.
        """

        LOGGER.info("TC device join: %s", msg)

        # Perform route discovery (just in case) when a device joins the network so that
        # we can begin initialization as soon as possible.
        self.create_task(self._discover_route(msg.SrcNwk))

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

        # XXX: Is it possible to receive messages on non-assigned endpoints?
        if msg.DstEndpoint != 0 and msg.DstEndpoint in self._device.endpoints:
            profile = self._device.endpoints[msg.DstEndpoint].profile_id
        else:
            LOGGER.warning("Received a message on an unregistered endpoint: %s", msg)
            profile = zigpy.profiles.zha.PROFILE_ID

        if msg.WasBroadcast:
            dst = zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.Broadcast,
                address=zigpy.types.BroadcastAddress.ALL_ROUTERS_AND_COORDINATOR,
            )
        elif msg.GroupId != 0x0000:
            dst = zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.Group,
                address=msg.GroupId,
            )
        else:
            dst = zigpy.types.AddrModeAddress(
                addr_mode=zigpy.types.AddrMode.NWK,
                address=self.state.node_info.nwk,
            )

        self.packet_received(
            zigpy.types.ZigbeePacket(
                src=zigpy.types.AddrModeAddress(
                    addr_mode=zigpy.types.AddrMode.NWK, address=msg.SrcAddr
                ),
                src_ep=msg.SrcEndpoint,
                dst=dst,
                dst_ep=msg.DstEndpoint,
                tsn=msg.TSN,
                profile_id=profile,
                cluster_id=msg.ClusterId,
                data=t.SerializableBytes(bytes(msg.Data)),
                tx_options=(
                    zigpy.types.TransmitOptions.APS_Encryption
                    if msg.SecurityUse
                    else zigpy.types.TransmitOptions.NONE
                ),
                radius=msg.MsgResultRadius,
                lqi=msg.LQI,
                rssi=None,
            )
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

    async def _watchdog_feed(self):
        """
        Watchdog loop to periodically test if Z-Stack is still running.
        """

        await self._znp.request(c.SYS.Ping.Req())

    async def _set_led_mode(self, *, led: t.uint8_t, mode: c.util.LEDMode) -> None:
        """
        Attempts to set the provided LED's mode. A Z-Stack bug causes the underlying
        command to never receive a response if the board has no LEDs, requiring this
        wrapper function to prevent the command from taking many seconds to time out.
        """

        # XXX: If Z-Stack is not compiled with HAL_LED, it will just not respond at all
        try:
            async with asyncio_timeout(0.5):
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

    def _find_endpoint(self, dst_ep: int, profile: int, cluster: int) -> int:
        """
        Zigpy defaults to sending messages with src_ep == dst_ep. This does not work
        with all versions of Z-Stack, which requires endpoints to be registered
        explicitly on startup.
        """

        if dst_ep == ZDO_ENDPOINT:
            return ZDO_ENDPOINT

        if profile == zigpy.profiles.zgp.PROFILE_ID:
            return zigpy.profiles.zgp.GREENPOWER_ENDPOINT_ID

        # Newer Z-Stack releases ignore profiles and will work properly with endpoint 1
        if (
            self._zstack_build_id >= 20210708
            and self.znp_config[conf.CONF_PREFER_ENDPOINT_1]
        ):
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
        dst_addr: t.AddrModeAddress,
        dst_ep: int,
        src_ep: int,
        profile: int,
        cluster: int,
        sequence: int,
        options: c.af.TransmitOptions,
        radius: int,
        data: bytes,
        *,
        relays: list[int] | None = None,
        extended_timeout: bool = False,
    ) -> None:
        """
        Used by `request`/`mrequest`/`broadcast` to send a request.
        Picks the correct request sending mechanism and fixes endpoint information.
        """

        # Zigpy just sets src == dst, which doesn't work for devices with many endpoints
        # We pick ours based on the registered endpoints when using an older firmware
        src_ep = self._find_endpoint(dst_ep=dst_ep, profile=profile, cluster=cluster)

        if relays is None:
            request = c.AF.DataRequestExt.Req(
                DstAddrModeAddress=dst_addr,
                DstEndpoint=dst_ep or 0,
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
                DstEndpoint=dst_ep or 0,
                SrcEndpoint=src_ep,
                ClusterId=cluster,
                TSN=sequence,
                Options=options,
                Radius=radius,
                SourceRoute=relays,  # force the packet to go through specific parents
                Data=data,
            )

        if self._znp is None:
            raise DeliveryError("Coordinator is disconnected, cannot send request")

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
                self.packet_received(
                    zigpy.types.ZigbeePacket(
                        src=zigpy.types.AddrModeAddress(
                            addr_mode=zigpy.types.AddrMode.NWK,
                            address=self._device.nwk,
                        ),
                        src_ep=src_ep,
                        dst=zigpy.types.AddrModeAddress(
                            addr_mode=zigpy.types.AddrMode.NWK,
                            address=self._device.nwk,
                        ),
                        dst_ep=dst_ep,
                        tsn=sequence,
                        profile_id=profile,
                        cluster_id=cluster,
                        data=t.SerializableBytes(data),
                        radius=radius,
                    )
                )

        if dst_ep == ZDO_ENDPOINT or dst_addr.mode == t.AddrMode.Broadcast:
            # Broadcasts and ZDO requests will not receive a confirmation
            await self._znp.request(request=request, RspStatus=t.Status.SUCCESS)
        else:
            async with asyncio_timeout(
                EXTENDED_DATA_CONFIRM_TIMEOUT
                if extended_timeout
                else DATA_CONFIRM_TIMEOUT
            ):
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

    async def send_packet(self, packet: zigpy.types.ZigbeePacket) -> None:
        """
        Fault-tolerant wrapper around `_send_request_raw` that transparently attempts to
        repair routes and contact the device through other methods when Z-Stack errors
        are encountered.
        """

        LOGGER.debug("Sending packet %r", packet)

        options = c.af.TransmitOptions.SUPPRESS_ROUTE_DISC_NETWORK

        if zigpy.types.TransmitOptions.ACK in packet.tx_options:
            options |= c.af.TransmitOptions.ACK_REQUEST

        if zigpy.types.TransmitOptions.APS_Encryption in packet.tx_options:
            options |= c.af.TransmitOptions.ENABLE_SECURITY

        try:
            device = self.get_device_with_address(packet.dst)
        except (KeyError, ValueError):
            # Sometimes a request is sent to a device not in the database. This should
            # work, the device object is only for recovery.
            device = None

        dst_addr = t.AddrModeAddress.from_zigpy_type(packet.dst)

        succeeded = False
        child_association = None
        tried_assoc_remove = False

        try:
            # We retry sending twice but the only devices that will use the second retry
            # attempt are sleeping end devices that silently switched parents from the
            # coordinator, all others will fail immediately
            for _retry_attempt in range(2):
                async with self._limit_concurrency(priority=packet.priority):
                    try:
                        # ZDO requests do not generate `AF.DataConfirm` messages
                        # indicating that a route is missing so we need to explicitly
                        # check for one.
                        if (
                            packet.dst_ep == ZDO_ENDPOINT
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

                        await self._send_request_raw(
                            dst_addr=dst_addr,
                            dst_ep=packet.dst_ep,
                            src_ep=packet.src_ep,
                            profile=packet.profile_id,
                            cluster=packet.cluster_id,
                            sequence=packet.tsn,
                            options=options,
                            radius=packet.radius or 0,
                            data=packet.data.serialize(),
                            relays=packet.source_route,
                            extended_timeout=packet.extended_timeout,
                        )
                        succeeded = True
                        break
                    except InvalidCommandResponse as e:
                        # Child aging is disabled so if a child switches parents from
                        # the coordinator to another router, we will not be able to
                        # re-discover a route to it. We have to manually drop the child
                        # to do this.
                        if (
                            e.response.Status == t.Status.MAC_TRANSACTION_EXPIRED
                            and device is not None
                            and child_association is None
                            and self._znp.version >= 3.30
                        ):
                            child_association = await self._znp.request(
                                c.UTIL.AssocGetWithAddress.Req(
                                    IEEE=device.ieee,
                                    NWK=0x0000,  # IEEE takes priority
                                )
                            )

                            if (
                                child_association.Device.nodeRelation
                                == c.util.NodeRelation.NOTUSED
                            ):
                                raise

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
                                raise e from None
                            else:
                                continue

                        # Perform route discovery explicitly if the stack fails
                        if e.response.Status == t.Status.NWK_NO_ROUTE:
                            await self._discover_route(device.nwk)

                        raise
        except InvalidCommandResponse as e:
            status = e.response.Status
            raise DeliveryError(f"Failed to send request: {status!r}", status=status)
        finally:
            # We *must* re-add the device association if we previously removed it but
            # the request still failed. Otherwise, it may be a direct child and we will
            # not be able to find it again.
            if not succeeded and tried_assoc_remove:
                assert child_association is not None
                await self._znp.request(
                    c.UTIL.AssocAdd.Req(
                        NWK=child_association.Device.shortAddr,
                        IEEE=device.ieee,
                        NodeRelation=child_association.Device.nodeRelation,
                    )
                )
