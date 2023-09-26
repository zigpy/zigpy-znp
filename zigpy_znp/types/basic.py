from __future__ import annotations

import typing

from zigpy.types import int8s, uint8_t, enum_factory  # noqa: F401

from zigpy_znp.types.cstruct import CStruct

if typing.TYPE_CHECKING:
    import enum

    class enum8(int, enum.Enum):
        pass

    class enum16(int, enum.Enum):
        pass

    class enum24(int, enum.Enum):
        pass

    class enum40(int, enum.Enum):
        pass

    class enum64(int, enum.Enum):
        pass

    class bitmap8(enum.IntFlag):
        pass

    class bitmap16(enum.IntFlag):
        pass

else:
    from zigpy.types import (  # noqa: F401
        enum8,
        enum16,
        bitmap8,
        bitmap16,
        uint16_t,
        uint24_t,
        uint32_t,
        uint40_t,
        uint64_t,
    )

    class enum24(enum_factory(uint24_t)):  # type: ignore[misc]
        pass

    class enum40(enum_factory(uint40_t)):  # type: ignore[misc]
        pass

    class enum64(enum_factory(uint64_t)):  # type: ignore[misc]
        pass


class Bytes(bytes):
    def serialize(self) -> Bytes:
        return self

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[Bytes, bytes]:
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


def serialize_list(objects) -> Bytes:
    return Bytes(b"".join([o.serialize() for o in objects]))


class ShortBytes(Bytes):
    _header = uint8_t

    def serialize(self) -> Bytes:
        return self._header(len(self)).serialize() + self  # type:ignore[return-value]

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[Bytes, bytes]:
        length, data = cls._header.deserialize(data)
        if length > len(data):
            raise ValueError(f"Data is too short to contain {length} bytes of data")
        return cls(data[:length]), data[length:]


class LongBytes(ShortBytes):
    _header = uint16_t


class BaseListType(list):
    _item_type = None

    @classmethod
    def _serialize_item(cls, item, *, align):
        if not isinstance(item, cls._item_type):
            item = cls._item_type(item)  # type:ignore[misc]

        if issubclass(cls._item_type, CStruct):
            return item.serialize(align=align)
        else:
            return item.serialize()

    @classmethod
    def _deserialize_item(cls, data, *, align):
        if issubclass(cls._item_type, CStruct):
            return cls._item_type.deserialize(data, align=align)
        else:
            return cls._item_type.deserialize(data)


class LVList(BaseListType):
    _header = None

    def __init_subclass__(cls, *, item_type, length_type) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._header = length_type

    def serialize(self, *, align=False) -> bytes:
        assert self._item_type is not None
        return self._header(len(self)).serialize() + b"".join(
            [self._serialize_item(i, align=align) for i in self]
        )

    @classmethod
    def deserialize(cls, data: bytes, *, align=False) -> tuple[LVList, bytes]:
        length, data = cls._header.deserialize(data)
        r = cls()
        for _i in range(length):
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data


class FixedList(BaseListType):
    _length = None

    def __init_subclass__(cls, *, item_type, length) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._length = length

    def serialize(self, *, align=False) -> bytes:
        assert self._length is not None

        if len(self) != self._length:
            raise ValueError(
                f"Invalid length for {self!r}: expected {self._length}, got {len(self)}"
            )

        return b"".join([self._serialize_item(i, align=align) for i in self])

    @classmethod
    def deserialize(cls, data: bytes, *, align=False) -> tuple[FixedList, bytes]:
        r = cls()
        for _i in range(cls._length):
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data


class CompleteList(BaseListType):
    def __init_subclass__(cls, *, item_type) -> None:
        super().__init_subclass__()
        cls._item_type = item_type

    def serialize(self, *, align=False) -> bytes:
        return b"".join([self._serialize_item(i, align=align) for i in self])

    @classmethod
    def deserialize(cls, data: bytes, *, align=False) -> tuple[CompleteList, bytes]:
        r = cls()
        while data:
            item, data = cls._deserialize_item(data, align=align)
            r.append(item)
        return r, data
