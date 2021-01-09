import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.types import nvids
from zigpy_znp.exceptions import SecurityError, InvalidCommandResponse

# Some NVIDs don't really exist and Z-Stack doesn't behave consistently when operations
# are performed on them.
PROXIED_NVIDS = {nvids.OsalNvIds.POLL_RATE_OLD16}


def serialize(value) -> bytes:
    if hasattr(value, "serialize"):
        value = value.serialize()
    elif not isinstance(value, (bytes, bytearray)):
        raise TypeError(
            f"Only bytes or serializable types can be written to NVRAM."
            f" Got {value!r} (type {type(value)})"
        )

    if not value:
        raise ValueError("NVRAM value cannot be empty")

    return value


class NVRAMHelper:
    def __init__(self, znp):
        self.znp = znp

    async def osal_delete(self, nv_id: t.uint16_t) -> bool:
        """
        Deletes an item from NVRAM. Returns whether or not the item existed.
        """

        length = (await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))).ItemLen

        if length == 0:
            return False

        delete_rsp = await self.znp.request(
            c.SYS.OSALNVDelete.Req(Id=nv_id, ItemLen=length)
        )

        return delete_rsp.Status == t.Status.SUCCESS

    async def osal_write(self, nv_id: t.uint16_t, value, *, create: bool = False):
        """
        Writes a complete value to NVRAM, optionally resizing and creating the item if
        necessary.

        Serializes all serializable values and passes bytes directly.
        """

        value = serialize(value)
        length = (await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))).ItemLen

        # Recreate the item if the length is not correct
        if length != len(value) and nv_id not in PROXIED_NVIDS:
            if not create:
                if length == 0:
                    raise KeyError(f"NV item does not exist: {nv_id!r}")
                else:
                    raise ValueError(
                        f"Stored length and actual length differ:"
                        f" {length} != {len(value)}"
                    )

            if length != 0:
                await self.znp.request(
                    c.SYS.OSALNVDelete.Req(Id=nv_id, ItemLen=length),
                    RspStatus=t.Status.SUCCESS,
                )

            await self.znp.request(
                c.SYS.OSALNVItemInit.Req(
                    Id=nv_id,
                    ItemLen=len(value),
                    Value=t.ShortBytes(value[:244]),
                ),
                RspStatus=t.Status.NV_ITEM_UNINIT,
            )

        # 244 bytes is the most you can fit in a single `SYS.OSALNVWriteExt` command
        for offset in range(0, len(value), 244):
            await self.znp.request(
                c.SYS.OSALNVWriteExt.Req(
                    Id=nv_id,
                    Offset=offset,
                    Value=t.ShortBytes(value[offset : offset + 244]),
                ),
                RspStatus=t.Status.SUCCESS,
            )

    async def osal_read(self, nv_id: t.uint16_t) -> bytes:
        """
        Reads a complete value from NVRAM.

        Raises an `KeyError` error if the NVID doesn't exist.
        """

        # XXX: Some NVIDs don't really exist and Z-Stack behaves strangely with them
        if nv_id in PROXIED_NVIDS:
            read_rsp = await self.znp.request(
                c.SYS.OSALNVRead.Req(Id=nv_id, Offset=0),
                RspStatus=t.Status.SUCCESS,
            )

            return read_rsp.Value

        # Every item has a length, even missing ones
        length = (await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))).ItemLen

        if length == 0:
            raise KeyError(f"NV item does not exist: {nv_id!r}")

        data = b""

        try:
            while len(data) < length:
                read_rsp = await self.znp.request(
                    c.SYS.OSALNVReadExt.Req(Id=nv_id, Offset=len(data)),
                    RspStatus=t.Status.SUCCESS,
                )

                data += read_rsp.Value
        except InvalidCommandResponse as e:
            # Only expected status code is INVALID_PARAMETER
            assert e.response.Status == t.Status.INVALID_PARAMETER

            # Not all items can be read out due to security policies, though this can
            # easily be bypassed for some. The SAPI "ConfigId" is only 8 bits which
            # means some nvids are not able to read this way.
            if not self.znp.capabilities & t.MTCapabilities.CAP_SAPI or nv_id > 0xFF:
                raise SecurityError(
                    f"NV item cannot be read due to security constraints: {nv_id!r}"
                )

            read_rsp = await self.znp.request(
                c.SAPI.ZBReadConfiguration.Req(ConfigId=nv_id),
                RspStatus=t.Status.SUCCESS,
                RspConfigId=nv_id,
            )

            data = read_rsp.Value

        assert len(data) == length

        return data

    async def delete(
        self, sys_id: t.uint8_t, item_id: t.uint16_t, sub_id: t.uint16_t
    ) -> bool:
        """
        Deletes a subitem from NVRAM. Returns whether or not the item existed.
        """

        delete_rsp = await self.znp.request(
            c.SYS.NVDelete.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
        )

        return delete_rsp.Status == t.Status.SUCCESS

    async def write(
        self,
        sys_id: t.uint8_t,
        item_id: t.uint16_t,
        sub_id: t.uint16_t,
        value,
        *,
        create: bool = True,
    ):
        """
        Writes a value to NVRAM for the specified subsystem, item, and subitem.

        Calls to OSALNVWrite(sub_id=1) in newer Z-Stack releases are really calls to
        NVWrite(sys_id=ZSTACK, item_id=LEGACY, sub_id=1) in the background.
        """

        value = serialize(value)
        length = (
            await self.znp.request(
                c.SYS.NVLength.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
            )
        ).Length

        if length != len(value) and not (
            sys_id == nvids.NvSysIds.ZSTACK
            and item_id in PROXIED_NVIDS
            and sub_id == 0x0000
        ):
            if not create:
                if length == 0:
                    raise KeyError(
                        f"NV item does not exist:"
                        f" sys_id={sys_id!r} item_id={item_id!r} sub_id={sub_id!r}"
                    )
                else:
                    raise ValueError(
                        f"Stored length and actual length differ:"
                        f" {length} != {len(value)}"
                    )

            if length != 0:
                await self.znp.request(
                    c.SYS.NVDelete.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id),
                    RspStatus=t.Status.SUCCESS,
                )

            create_rsp = await self.znp.request(
                c.SYS.NVCreate.Req(
                    SysId=sys_id,
                    ItemId=item_id,
                    SubId=sub_id,
                    Length=len(value),
                )
            )

            if create_rsp.Status not in (t.Status.SUCCESS, t.Status.NV_ITEM_UNINIT):
                raise InvalidCommandResponse("Bad create status", create_rsp)

        # 244 bytes is the most you can fit in a single `SYS.NVWrite` command
        for offset in range(0, len(value), 244):
            await self.znp.request(
                c.SYS.NVWrite.Req(
                    SysId=sys_id,
                    ItemId=item_id,
                    SubId=sub_id,
                    Value=t.ShortBytes(value[offset : offset + 244]),
                    Offset=0,
                ),
                RspStatus=t.Status.SUCCESS,
            )

    async def read(
        self, sys_id: t.uint8_t, item_id: t.uint16_t, sub_id: t.uint16_t
    ) -> bytes:
        """
        Reads a value from NVRAM for the specified subsystem, item, and subitem.

        Calls to OSALNVRead(sub_id=1) in newer Z-Stack releases are really calls to
        NVRead(sys_id=ZSTACK, item_id=LEGACY, sub_id=1) in the background.

        Raises an `KeyError` error if the NVID doesn't exist.
        """

        length_rsp = await self.znp.request(
            c.SYS.NVLength.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
        )
        length = length_rsp.Length

        if length == 0:
            raise KeyError(
                f"NV item does not exist:"
                f" sys_id={sys_id!r} item_id={item_id!r} sub_id={sub_id!r}"
            )

        data = b""

        while len(data) < length:
            read_rsp = await self.znp.request(
                c.SYS.NVRead.Req(
                    SysId=sys_id,
                    ItemId=item_id,
                    SubId=sub_id,
                    Offset=len(data),
                    Length=length,
                ),
                RspStatus=t.Status.SUCCESS,
            )

            data += read_rsp.Value

        assert len(data) == length

        return data
