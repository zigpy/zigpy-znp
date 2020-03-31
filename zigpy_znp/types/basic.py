def deserialize(data, schema):
    result = []
    for type_ in schema:
        value, data = type_.deserialize(data)
        result.append(value)
    return result, data


def serialize(data, schema):
    return b"".join(t(v).serialize() for t, v in zip(schema, data))


class Bytes(bytes):
    def serialize(self):
        return self

    @classmethod
    def deserialize(cls, data):
        return cls(data), b""

    def __repr__(self):
        # Reading byte sequences like \x200\x21 is extremely annoying
        # compared to \x20\x30\x21
        escaped = "".join(f"\\x{b:02X}" for b in self)

        return f"b'{escaped}'"

    __str__ = __repr__


class int_t(int):
    _signed = True
    _size = 0

    def serialize(self, byteorder="little"):
        return self.to_bytes(self._size, byteorder, signed=self._signed)

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        if len(data) < cls._size:
            raise ValueError(f"Data is too short to contain {cls._size} bytes")
        r = cls.from_bytes(data[: cls._size], byteorder, signed=cls._signed)
        data = data[cls._size :]
        return r, data


class int8s(int_t):
    _size = 1


class int16s(int_t):
    _size = 2


class int24s(int_t):
    _size = 3


class int32s(int_t):
    _size = 4


class int40s(int_t):
    _size = 5


class int48s(int_t):
    _size = 6


class int56s(int_t):
    _size = 7


class int64s(int_t):
    _size = 8


class uint_t(int_t):
    _signed = False


class uint8_t(uint_t):
    _size = 1


class uint16_t(uint_t):
    _size = 2


class uint24_t(uint_t):
    _size = 3


class uint32_t(uint_t):
    _size = 4


class uint40_t(uint_t):
    _size = 5


class uint48_t(uint_t):
    _size = 6


class uint56_t(uint_t):
    _size = 7


class uint64_t(uint_t):
    _size = 8


class ShortBytes(Bytes):
    _header = uint8_t

    def serialize(self):
        return self._header(len(self)).serialize() + self

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        length, data = cls._header.deserialize(data)
        if length > len(data):
            raise ValueError(f"Data is too short to contain {length} bytes of data")
        return cls(data[:length]), data[length:]


class LongBytes(ShortBytes):
    _header = uint16_t


class List(list):
    _length = None
    _itemtype = None

    def serialize(self):
        assert self._length is None or len(self) == self._length
        return b"".join([self._itemtype(i).serialize() for i in self])

    @classmethod
    def deserialize(cls, data):
        assert cls._itemtype is not None
        r = cls()
        while data:
            item, data = cls._itemtype.deserialize(data)
            r.append(item)
        return r, data


class _LVList(List):
    _header = uint8_t

    def serialize(self):
        assert self._itemtype is not None
        return self._header(len(self)).serialize() + super().serialize()

    @classmethod
    def deserialize(cls, data):
        assert cls._itemtype is not None
        length, data = cls._header.deserialize(data)
        r = cls()
        for i in range(length):
            item, data = cls._itemtype.deserialize(data)
            r.append(item)
        return r, data


# So that isinstance(LVList(uint8_t)([]), LVList(uint8_t)) is True
# XXX: This is not a "real" solution, it just passes unit tests.
#      Namely, it is not pickleable.
LVLIST_SINGLETON_CACHE = {}


def LVList(itemtype, headertype=uint8_t):
    if (itemtype, headertype) in LVLIST_SINGLETON_CACHE:
        return LVLIST_SINGLETON_CACHE[(itemtype, headertype)]

    class LVList(_LVList):
        _header = headertype
        _itemtype = itemtype

    LVLIST_SINGLETON_CACHE[(itemtype, headertype)] = LVList

    return LVList


class FixedList(List):
    _length = None
    _itemtype = None

    @classmethod
    def deserialize(cls, data):
        assert cls._itemtype is not None
        r = cls()
        for i in range(cls._length):
            item, data = cls._itemtype.deserialize(data)
            r.append(item)
        return r, data


class HexRepr:
    def __str__(self):
        return ("0x{:0" + str(self._size * 2) + "X}").format(self)

    __repr__ = __str__


class enum_uint8:
    _type = uint8_t

    def serialize(self):
        """Serialize enum."""
        return self._type(self.value).serialize()

    @classmethod
    def deserialize(cls, data: bytes, byteorder: str = "little") -> (bytes, bytes):
        """Deserialize data."""
        val, data = cls._type.deserialize(data, byteorder)
        return cls(val), data


class enum_uint16(enum_uint8):
    _type = uint16_t


class enum_uint24(enum_uint8):
    _type = uint24_t


class enum_uint32(enum_uint8):
    _type = uint32_t


class enum_uint40(enum_uint8):
    _type = uint40_t


class enum_uint48(enum_uint8):
    _type = uint48_t


class enum_uint56(enum_uint8):
    _type = uint56_t


class enum_uint64(enum_uint8):
    _type = uint64_t
