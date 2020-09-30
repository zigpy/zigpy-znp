import enum
import typing


class Bytes(bytes):
    def serialize(self) -> "Bytes":
        return self

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple["Bytes", bytes]:
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

    pass


def serialize_list(objects) -> Bytes:
    return Bytes(b"".join([o.serialize() for o in objects]))


class FixedIntType(int):
    _signed = None
    _size = None

    def __new__(cls, *args, **kwargs):
        if cls._signed is None or cls._size is None:
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
            fmt = f"0x{{:0{cls._size * 2}X}}"
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
    def deserialize(cls, data: bytes) -> typing.Tuple["FixedIntType", bytes]:
        if len(data) < cls._size:
            raise ValueError(f"Data is too short to contain {cls._size} bytes")

        r = cls.from_bytes(data[: cls._size], "little", signed=cls._signed)
        data = data[cls._size :]
        return r, data


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

    def serialize(self) -> "Bytes":
        return self._header(len(self)).serialize() + self

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple[Bytes, bytes]:
        length, data = cls._header.deserialize(data)
        if length > len(data):
            raise ValueError(f"Data is too short to contain {length} bytes of data")
        return cls(data[:length]), data[length:]


class LongBytes(ShortBytes):
    _header = uint16_t


class LVList(list):
    _item_type = None
    _header = None

    def __init_subclass__(cls, *, item_type, length_type) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._header = length_type

    def serialize(self) -> bytes:
        assert self._item_type is not None
        return self._header(len(self)).serialize() + serialize_list(
            [self._item_type(i) for i in self]
        )

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple["LVList", bytes]:
        assert cls._item_type is not None
        length, data = cls._header.deserialize(data)
        r = cls()
        for i in range(length):
            item, data = cls._item_type.deserialize(data)
            r.append(item)
        return r, data


class FixedList(list):
    _item_type = None
    _length = None

    def __init_subclass__(cls, *, item_type, length) -> None:
        super().__init_subclass__()
        cls._item_type = item_type
        cls._length = length

    def serialize(self) -> bytes:
        assert self._length is not None

        if len(self) != self._length:
            raise ValueError(
                f"Invalid length for {self!r}: expected {self._length}, got {len(self)}"
            )

        return serialize_list([self._item_type(i) for i in self])

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple["FixedList", bytes]:
        assert cls._item_type is not None
        r = cls()
        for i in range(cls._length):
            item, data = cls._item_type.deserialize(data)
            r.append(item)
        return r, data


def enum_flag_factory(int_type: FixedIntType) -> enum.Flag:
    """
    Mixins are broken by Python 3.8.6 so we must dynamically create the enum with the
    appropriate methods but with only one non-Enum parent class.
    """

    class _NewEnum(int_type, enum.Flag):
        # Rebind classmethods to our own class
        _missing_ = classmethod(enum.IntFlag._missing_.__func__)
        _create_pseudo_member_ = classmethod(
            enum.IntFlag._create_pseudo_member_.__func__
        )

        __or__ = enum.IntFlag.__or__
        __and__ = enum.IntFlag.__and__
        __xor__ = enum.IntFlag.__xor__
        __ror__ = enum.IntFlag.__ror__
        __rand__ = enum.IntFlag.__rand__
        __rxor__ = enum.IntFlag.__rxor__
        __invert__ = enum.IntFlag.__invert__

    return _NewEnum


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


class enum_flag_uint8(enum_flag_factory(uint8_t)):
    pass


class enum_flag_uint16(enum_flag_factory(uint16_t)):
    pass


class enum_flag_uint24(enum_flag_factory(uint24_t)):
    pass


class enum_flag_uint32(enum_flag_factory(uint32_t)):
    pass


class enum_flag_uint40(enum_flag_factory(uint40_t)):
    pass


class enum_flag_uint48(enum_flag_factory(uint48_t)):
    pass


class enum_flag_uint56(enum_flag_factory(uint56_t)):
    pass


class enum_flag_uint64(enum_flag_factory(uint64_t)):
    pass
