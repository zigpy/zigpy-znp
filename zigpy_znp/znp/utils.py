import logging
import dataclasses

import zigpy_znp.types as t
from zigpy_znp.exceptions import CommandNotRecognized
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class NetworkInfo:
    ieee: t.EUI64
    nwk: t.NWK
    channel: t.uint8_t
    channels: t.Channels
    pan_id: t.NWK
    extended_pan_id: t.EUI64
    nwk_update_id: t.uint8_t
    security_level: t.uint8_t
    network_key: t.KeyData
    network_key_seq: t.uint8_t

    def replace(self, **kwargs):
        return dataclasses.replace(self, **kwargs)


async def fix_misaligned_coordinator_nvram(znp) -> None:
    """
    Some users have coordinators with broken alignment in NVRAM:

        "TCLK_TABLE": {
            "0x0000": "21000000000000000000000000000000ff0000",  <-- missing a byte??
            "0x0001": "00000000000000000000000000000000ff000000",

    These issues need to be corrected before zigpy-znp can continue working with NVRAM.
    """

    if znp.version < 3.30:
        return

    try:
        nib_data = await znp.nvram.osal_read(OsalNvIds.NIB, item_type=t.Bytes)
        znp.nvram.deserialize(nib_data, item_type=t.NIB)
    except KeyError:
        pass
    except ValueError:
        LOGGER.warning("Correcting invalid NIB alignment: %s", nib_data)

        nib = znp.nvram.deserialize(nib_data + b"\xFF" * 6, item_type=t.NIB)

        if nib.nwkUpdateId == 0xFF:
            nib.nwkUpdateId = 0

        await znp.nvram.osal_write(OsalNvIds.NIB, nib, create=True)

    offset = 0

    async for data in znp.nvram.read_table(
        item_id=ExNvIds.TCLK_TABLE,
        item_type=t.Bytes,
    ):
        try:
            znp.nvram.deserialize(data, item_type=t.TCLKDevEntry)
        except ValueError:
            LOGGER.warning(
                "Correcting invalid TCLK_TABLE[0x%04X] entry: %s", offset, data
            )

            entry = znp.nvram.deserialize(data + b"\x00", item_type=t.TCLKDevEntry)

            await znp.nvram.write(
                item_id=ExNvIds.TCLK_TABLE, sub_id=offset, value=entry, create=True
            )

        offset += 1


async def load_network_info(znp) -> NetworkInfo:
    """
    Loads low-level network information from NVRAM.
    """

    is_on_network = None
    nib = None

    if znp.version >= 3.0:
        try:
            is_on_network = (
                await znp.nvram.osal_read(
                    OsalNvIds.BDBNODEISONANETWORK, item_type=t.uint8_t
                )
                == 1
            )
        except KeyError:
            is_on_network = False

    try:
        nib = await znp.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)
        is_on_network = nib.nwkLogicalChannel != 0 and nib.nwkKeyLoaded
    except KeyError:
        is_on_network = False

    if not is_on_network:
        raise ValueError("Device is not a part of a network")

    ieee = await znp.nvram.osal_read(OsalNvIds.EXTADDR, item_type=t.EUI64)
    key_desc = await znp.nvram.osal_read(
        OsalNvIds.NWK_ACTIVE_KEY_INFO, item_type=t.NwkKeyDesc
    )

    return NetworkInfo(
        ieee=ieee,
        nwk=nib.nwkDevAddress,
        channel=nib.nwkLogicalChannel,
        channels=nib.channelList,
        pan_id=nib.nwkPanId,
        extended_pan_id=nib.extendedPANID,
        nwk_update_id=nib.nwkUpdateId,
        security_level=nib.SecurityLevel,
        network_key=key_desc.Key,
        network_key_seq=key_desc.KeySeqNum,
    )


async def detect_zstack_version(znp) -> float:
    """
    Feature detects the major version of Z-Stack running on the device.
    """

    # Z-Stack 1.2 does not have the AppConfig subsystem
    if not znp.capabilities & t.MTCapabilities.APP_CNF:
        return 1.2

    try:
        # Only Z-Stack 3.30+ has the new NVRAM system
        await znp.nvram.read(
            item_id=ExNvIds.TCLK_TABLE,
            sub_id=0x0000,
            item_type=t.Bytes,
        )
        return 3.30
    except KeyError:
        return 3.30
    except CommandNotRecognized:
        return 3.0
