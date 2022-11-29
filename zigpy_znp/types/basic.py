from __future__ import annotations

import enum
import typing

import zigpy.types as zigpy_t

from zigpy_znp.types.cstruct import CStruct


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


class FixedIntType(int):
    _signed: bool
    _size: int

    def __new__(cls, *args, **kwargs):
        if getattr(cls, "_signed", None) is None or getattr(cls, "_size", None) is None:
            raise TypeError(f"{cls} is abstract and cannot be created")

        instance = super().__new__(cls, *args, **kwargs)
        instance.serialize()

        return instance

    def __init_subclass__(cls, signed=None, size=None, hex_repr=None) -> None:
        super().__init_subclass__()

        if signed is not None:
            cls._signed = signed

        if size is not None:
            cls._size = size

        if hex_repr:
            fmt = f"0x{{:0{cls._size * 2}X}}"  # type:ignore[operator]
            cls.__str__ = cls.__repr__ = lambda self: fmt.format(self)
        elif hex_repr is not None and not hex_repr:
            cls.__str__ = super().__str__
            cls.__repr__ = super().__repr__

        # XXX: The enum module uses the first class with __new__ in its __dict__ as the
        #      member type. We have to ensure this is true for every subclass.
        if "__new__" not in cls.__dict__:
            cls.__new__ = cls.__new__

    def serialize(self) -> bytes:
        try:
            return self.to_bytes(self._size, "little", signed=self._signed)
        except OverflowError as e:
            # OverflowError is not a subclass of ValueError, making it annoying to catch
            raise ValueError(str(e)) from e

    @classmethod
    def deserialize(cls, data: bytes) -> tuple[FixedIntType, bytes]:
        if len(data) < cls._size:
            raise ValueError(f"Data is too short to contain {cls._size} bytes")

        r = cls.from_bytes(data[: cls._size], "little", signed=cls._signed)
        data = data[cls._size :]
        return typing.cast(FixedIntType, r), data


class uint_t(FixedIntType, signed=False):
    pass


class int_t(FixedIntType, signed=True):
    pass


class int8s(int_t, size=1):
    pass


class int16s(int_t, size=2):
    pass


class int24s(int_t, size=3):
    pass


class int32s(int_t, size=4):
    pass


class int40s(int_t, size=5):
    pass


class int48s(int_t, size=6):
    pass


class int56s(int_t, size=7):
    pass


class int64s(int_t, size=8):
    pass


class uint8_t(uint_t, size=1):
    pass


class uint16_t(uint_t, size=2):
    pass


class uint24_t(uint_t, size=3):
    pass


class uint32_t(uint_t, size=4):
    pass


class uint40_t(uint_t, size=5):
    pass


class uint48_t(uint_t, size=6):
    pass


class uint56_t(uint_t, size=7):
    pass


class uint64_t(uint_t, size=8):
    pass


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


class enum_uint8(uint8_t, enum.Enum):
    pass


class enum_uint16(uint16_t, enum.Enum):
    pass


class enum_uint24(uint24_t, enum.Enum):
    pass


class enum_uint32(uint32_t, enum.Enum):
    pass


class enum_uint40(uint40_t, enum.Enum):
    pass


class enum_uint48(uint48_t, enum.Enum):
    pass


class enum_uint56(uint56_t, enum.Enum):
    pass


class enum_uint64(uint64_t, enum.Enum):
    pass


class enum_flag_uint8(zigpy_t.bitmap_factory(uint8_t)):  # type:ignore[misc]
    pass


class enum_flag_uint16(zigpy_t.bitmap_factory(uint16_t)):  # type:ignore[misc]
    pass


class enum_flag_uint24(zigpy_t.bitmap_factory(uint24_t)):  # type:ignore[misc]
    pass


class enum_flag_uint32(zigpy_t.bitmap_factory(uint32_t)):  # type:ignore[misc]
    pass


class enum_flag_uint40(zigpy_t.bitmap_factory(uint40_t)):  # type:ignore[misc]
    pass


class enum_flag_uint48(zigpy_t.bitmap_factory(uint48_t)):  # type:ignore[misc]
    pass


class enum_flag_uint56(zigpy_t.bitmap_factory(uint56_t)):  # type:ignore[misc]
    pass


class enum_flag_uint64(zigpy_t.bitmap_factory(uint64_t)):  # type:ignore[misc]
    pass
