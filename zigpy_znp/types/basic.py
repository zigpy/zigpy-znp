from __future__ import annotations

import typing

from zigpy.types import (
    FixedIntType as _FixedIntType,
    bitmap8 as bitmap8,
    bitmap16 as bitmap16,
    enum8 as enum8,
    enum16 as enum16,
    enum24 as enum24,
    enum40 as enum40,
    enum64 as enum64,
    int8s as int8s,
    uint8_t as uint8_t,
    uint16_t as uint16_t,
    uint24_t as uint24_t,
    uint32_t as uint32_t,
    uint40_t as uint40_t,
    uint64_t as uint64_t,
)

from zigpy_znp.types.cstruct import CStruct


class Bytes(bytes):
    def serialize(self) -> bytes:
        return self

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[typing.Self, bytes]:
        return cls(data), b""

    def __repr__(self) -> str:
        # Reading byte sequences like \x200\x21 is extremely annoying
        # compared to \x20\x30\x21
        escaped = "".join(f"\\x{b:02X}" for b in self)

        return f"b'{escaped}'"

    __str__ = __repr__


class TrailingBytes(Bytes):
    """
    Bytes must occur at the very end of a parameter list for easy parsing.
    """


def serialize_list(objects: typing.Iterable[typing.Any]) -> Bytes:
    return Bytes(b"".join([o.serialize() for o in objects]))


class ShortBytes(Bytes):
    _header: type[_FixedIntType] = uint8_t

    def serialize(self) -> bytes:
        return self._header(len(self)).serialize() + self

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[typing.Self, bytes]:
        length, data = cls._header.deserialize(data)
        if length > len(data):
            raise ValueError(f"Data is too short to contain {length} bytes of data")
        return cls(data[:length]), data[length:]


class LongBytes(ShortBytes):
    _header = uint16_t


class BaseListType(list[typing.Any]):
    _item_type: type[typing.Any] | None = None

    if typing.TYPE_CHECKING:
        # Every concrete subclass implements these

        def serialize(self, *, align: bool = False) -> bytes: ...

        @classmethod
        def deserialize(
            cls, data: bytes, *, align: bool = False
        ) -> tuple[typing.Self, bytes]: ...

    @classmethod
    def _serialize_item(cls, item: typing.Any, *, align: bool) -> bytes:
        assert cls._item_type is not None

        if not isinstance(item, cls._item_type):
            item = cls._item_type(item)

        data: bytes

        if issubclass(cls._item_type, CStruct):
            data = item.serialize(align=align)
        else:
            data = item.serialize()

        return data

    @classmethod
    def _deserialize_item(cls, data: bytes, *, align: bool) -> tuple[typing.Any, bytes]:
        assert cls._item_type is not None

        result: tuple[typing.Any, bytes]

        if issubclass(cls._item_type, CStruct):
            result = cls._item_type.deserialize(data, align=align)
        else:
            result = cls._item_type.deserialize(data)

        return result


class LVList(BaseListType):
    _header: type[_FixedIntType] | None = None

    def __init_subclass__(
        cls, *, item_type: type[typing.Any], length_type: type[_FixedIntType]
    ) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._header = length_type

    def serialize(self, *, align: bool = False) -> bytes:
        assert self._item_type is not None
        assert self._header is not None
        return self._header(len(self)).serialize() + b"".join(
            [self._serialize_item(i, align=align) for i in self]
        )

    @classmethod
    def deserialize(
        cls, data: bytes, *, align: bool = False
    ) -> tuple[typing.Self, bytes]:
        assert cls._header is not None
        length, data = cls._header.deserialize(data)
        r = cls()
        for _i in range(length):
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data


class FixedList(BaseListType):
    _length: int | None = None

    def __init_subclass__(cls, *, item_type: type[typing.Any], length: int) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._length = length

    def serialize(self, *, align: bool = False) -> bytes:
        assert self._length is not None

        if len(self) != self._length:
            raise ValueError(
                f"Invalid length for {self!r}: expected {self._length}, got {len(self)}"
            )

        return b"".join([self._serialize_item(i, align=align) for i in self])

    @classmethod
    def deserialize(
        cls, data: bytes, *, align: bool = False
    ) -> tuple[typing.Self, bytes]:
        assert cls._length is not None
        r = cls()
        for _i in range(cls._length):
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data


class CompleteList(BaseListType):
    def __init_subclass__(cls, *, item_type: type[typing.Any]) -> None:
        super().__init_subclass__()
        cls._item_type = item_type

    def serialize(self, *, align: bool = False) -> bytes:
        return b"".join([self._serialize_item(i, align=align) for i in self])

    @classmethod
    def deserialize(
        cls, data: bytes, *, align: bool = False
    ) -> tuple[typing.Self, bytes]:
        r = cls()
        while data:
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data
