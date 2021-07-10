import dataclasses

import zigpy_znp.types as t
from zigpy_znp.exceptions import CommandNotRecognized
from zigpy_znp.types.nvids import ExNvIds, OsalNvIds


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


async def load_network_info(znp) -> NetworkInfo:
    """
    Loads low-level network information from NVRAM.
    """

    is_on_network = None
    nib = None

    try:
        nib = await znp.nvram.osal_read(OsalNvIds.NIB, item_type=t.NIB)
        is_on_network = nib.nwkLogicalChannel != 0 and nib.nwkKeyLoaded
    except KeyError:
        is_on_network = False
    else:
        if is_on_network and znp.version >= 3.0:
            # This NVRAM item is the very first thing initialized in `zgInit`, it exists
            is_on_network = (
                await znp.nvram.osal_read(
                    OsalNvIds.BDBNODEISONANETWORK, item_type=t.uint8_t
                )
                == 1
            )

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
