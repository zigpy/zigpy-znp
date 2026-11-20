from __future__ import annotations

import itertools
import logging
import typing

import zigpy_znp.commands as c
from zigpy_znp.exceptions import InvalidCommandResponse, SecurityError
import zigpy_znp.types as t
from zigpy_znp.types import nvids

if typing.TYPE_CHECKING:
    from zigpy_znp.api import ZNP

LOGGER = logging.getLogger(__name__)

_T = typing.TypeVar("_T")


# Some NVIDs don't really exist and Z-Stack doesn't behave consistently when operations
# are performed on them.
PROXIED_NVIDS = {nvids.OsalNvIds.POLL_RATE_OLD16}


class NVRAMHelper:
    def __init__(self, znp: ZNP) -> None:
        self.znp = znp
        self.align_structs: bool | None = None

    async def determine_alignment(self) -> None:
        """
        Automatically determine struct memory alignment. Must be called before any
        structs are read/written.
        """

        # This is the only known MT command to respond with a struct's in-memory
        # representation over serial.
        LOGGER.debug("Detecting struct alignment")
        rsp = await self.znp.request(c.UTIL.AssocFindDevice.Req(Index=0))
        assert rsp is not None

        if len(rsp.Device) == 28:
            self.align_structs = False
        elif len(rsp.Device) == 36:
            # `AssociatedDevice` has an extra member at the end in Z-Stack 3.30 but
            # the struct does not change in size due to padding.
            self.align_structs = True
        else:
            raise ValueError(f"Cannot determine alignment from struct: {rsp!r}")

        LOGGER.debug("Detected struct alignment: %s", self.align_structs)

    def serialize(self, value: typing.Any) -> bytes | bytearray:
        """
        Serialize an object, automatically computing struct padding based on the target
        platform.
        """

        data: bytes | bytearray

        if hasattr(value, "serialize"):
            if isinstance(value, (t.CStruct, t.BaseListType)):
                assert self.align_structs is not None
                data = value.serialize(align=self.align_structs)
            else:
                data = value.serialize()
        elif not isinstance(value, (bytes, bytearray)):
            raise TypeError(
                f"Only bytes or serializable types can be written to NVRAM."
                f" Got {value!r} (type {type(value)})"
            )
        else:
            data = value

        if not data:
            raise ValueError("NVRAM value cannot be empty")

        return data

    def deserialize(
        self, data: bytes, item_type: type[_T], *, allow_trailing: bool = False
    ) -> _T:
        """
        Serialize raw bytes, automatically computing struct padding based on the target
        platform.
        """

        value: _T
        remaining: bytes

        if issubclass(item_type, (t.CStruct, t.BaseListType)):
            assert self.align_structs is not None
            value, remaining = item_type.deserialize(data, align=self.align_structs)
        else:
            # The item types share no base class, each one has a `deserialize`
            value, remaining = typing.cast(typing.Any, item_type).deserialize(data)

        if remaining and not allow_trailing:
            raise ValueError(f"Data left after deserialization: {remaining!r}")

        return value

    async def osal_delete(self, nv_id: int) -> bool:
        """
        Deletes an item from NVRAM. Returns whether or not the item existed.
        """

        length_rsp = await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))
        assert length_rsp is not None
        length = length_rsp.ItemLen

        if length == 0:
            return False

        delete_rsp = await self.znp.request(
            c.SYS.OSALNVDelete.Req(Id=nv_id, ItemLen=length)
        )
        assert delete_rsp is not None

        return bool(delete_rsp.Status == t.Status.SUCCESS)

    async def osal_write(
        self, nv_id: int, value: typing.Any, *, create: bool = False
    ) -> None:
        """
        Writes a complete value to NVRAM, optionally resizing and creating the item if
        necessary.

        Serializes all serializable values and passes bytes directly.
        """

        value = self.serialize(value)
        length_rsp = await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))
        assert length_rsp is not None
        length = length_rsp.ItemLen

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

    async def osal_read(self, nv_id: int, *, item_type: type[_T]) -> _T:
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
            assert read_rsp is not None

            value = self.deserialize(read_rsp.Value, item_type)
            LOGGER.debug('Read NVRAM["LEGACY"][0x%04x] = %r', nv_id, value)

            return value

        # Every item has a length, even missing ones
        length_rsp = await self.znp.request(c.SYS.OSALNVLength.Req(Id=nv_id))
        assert length_rsp is not None
        length = length_rsp.ItemLen

        if length == 0:
            raise KeyError(f"NV item does not exist: {nv_id!r}")

        data = b""

        try:
            while len(data) < length:
                read_rsp = await self.znp.request(
                    c.SYS.OSALNVReadExt.Req(Id=nv_id, Offset=len(data)),
                    RspStatus=t.Status.SUCCESS,
                )
                assert read_rsp is not None

                data += read_rsp.Value
        except InvalidCommandResponse as e:
            # Only expected status code is INVALID_PARAMETER
            assert e.response.Status == t.Status.INVALID_PARAMETER

            # Not all items can be read out due to security policies, though this can
            # easily be bypassed for some. The SAPI "ConfigId" is only 8 bits which
            # means some nvids are not able to read this way.
            if not self.znp.capabilities & t.MTCapabilities.SAPI or nv_id > 0xFF:
                raise SecurityError(
                    f"NV item cannot be read due to security constraints: {nv_id!r}"
                ) from e

            read_rsp = await self.znp.request(
                c.SAPI.ZBReadConfiguration.Req(ConfigId=nv_id),
                RspStatus=t.Status.SUCCESS,
                RspConfigId=nv_id,
            )
            assert read_rsp is not None

            data = read_rsp.Value

        assert len(data) == length

        value = self.deserialize(data, item_type)
        LOGGER.debug('Read NVRAM["LEGACY"][0x%04x] = %r', nv_id, value)

        return value

    async def delete(
        self,
        *,
        sys_id: int = nvids.NvSysIds.ZSTACK,
        item_id: int,
        sub_id: int,
    ) -> bool:
        """
        Deletes a subitem from NVRAM. Returns whether or not the item existed.
        """

        delete_rsp = await self.znp.request(
            c.SYS.NVDelete.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
        )
        assert delete_rsp is not None

        return bool(delete_rsp.Status == t.Status.SUCCESS)

    async def write(
        self,
        *,
        sys_id: int = nvids.NvSysIds.ZSTACK,
        item_id: int,
        sub_id: int,
        value: typing.Any,
        create: bool = True,
    ) -> None:
        """
        Writes a value to NVRAM for the specified subsystem, item, and subitem.

        Calls to OSALNVWrite(sub_id=1) in newer Z-Stack releases are really calls to
        NVWrite(sys_id=ZSTACK, item_id=LEGACY, sub_id=1) in the background.
        """

        value = self.serialize(value)
        length_rsp = await self.znp.request(
            c.SYS.NVLength.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
        )
        assert length_rsp is not None
        length = length_rsp.Length

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
            assert create_rsp is not None

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
        self,
        *,
        sys_id: int = nvids.NvSysIds.ZSTACK,
        item_id: int,
        sub_id: int,
        item_type: type[_T],
    ) -> _T:
        """
        Reads a value from NVRAM for the specified subsystem, item, and subitem.

        Calls to OSALNVRead(sub_id=1) in newer Z-Stack releases are really calls to
        NVRead(sys_id=ZSTACK, item_id=LEGACY, sub_id=1) in the background.

        Raises an `KeyError` error if the NVID doesn't exist.
        """

        length_rsp = await self.znp.request(
            c.SYS.NVLength.Req(SysId=sys_id, ItemId=item_id, SubId=sub_id)
        )
        assert length_rsp is not None
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
            assert read_rsp is not None

            data += read_rsp.Value

        assert len(data) == length

        value = self.deserialize(data, item_type)
        LOGGER.debug("Read NVRAM[%s][%s][0x%04x] = %r", sys_id, item_id, sub_id, value)

        return value

    async def write_table(
        self,
        *,
        sys_id: int = nvids.NvSysIds.ZSTACK,
        item_id: int,
        values: typing.Iterable[typing.Any],
        fill_value: typing.Any,
    ) -> None:
        for sub_id, value in itertools.zip_longest(
            range(0x0000, 0xFFFF + 1), values, fillvalue=fill_value
        ):
            value = self.serialize(value)

            try:
                await self.write(
                    sys_id=sys_id,
                    item_id=item_id,
                    sub_id=sub_id,
                    value=value,
                    create=False,
                )
            except KeyError:
                break

    async def osal_write_table(
        self,
        start_nvid: int,
        end_nvid: int,
        values: typing.Iterable[typing.Any],
        *,
        fill_value: typing.Any,
    ) -> None:
        values = list(values)

        for nvid, value in itertools.zip_longest(
            range(start_nvid, end_nvid + 1), values, fillvalue=fill_value
        ):
            value = self.serialize(value)

            try:
                await self.osal_write(
                    nv_id=nvid,
                    value=value,
                    create=False,
                )
            except KeyError:
                break

    async def read_table(
        self,
        *,
        sys_id: int = nvids.NvSysIds.ZSTACK,
        item_id: int,
        item_type: type[_T] = t.Bytes,  # type: ignore[assignment]
    ) -> typing.AsyncIterator[_T]:
        for sub_id in range(0x0000, 0xFFFF + 1):
            try:
                yield await self.read(
                    sys_id=sys_id,
                    item_id=item_id,
                    sub_id=sub_id,
                    item_type=item_type,
                )
            except KeyError:
                break

    async def osal_read_table(
        self,
        start_nvid: int,
        end_nvid: int,
        item_type: type[_T] = t.Bytes,  # type: ignore[assignment]
    ) -> typing.AsyncIterator[_T]:
        for nvid in range(start_nvid, end_nvid + 1):
            try:
                yield await self.osal_read(nvid, item_type=item_type)
            except KeyError:
                break
