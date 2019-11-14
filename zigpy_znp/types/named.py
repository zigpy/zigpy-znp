import attr
import enum

from . import basic


class _EnumEq:
    def __eq__(self, other):
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)


def FakeEnum(class_name: str):
    return attr.make_class(
        class_name,
        {"name": attr.ib(converter=str), "value": attr.ib()},
        bases=(_EnumEq,),
        eq=False,
    )


class GroupId(basic.HexRepr, basic.uint16_t):
    """"Group ID class"""

    pass


@attr.s
class Schema:
    """List of Parameters."""

    parameters = attr.ib()


class Status(basic.uint8_t, enum.Enum):
    Success = 0x00
    Failure = 0x01

    @classmethod
    def deserialize(cls, data, byteorder="little"):
        try:
            return super().deserialize(data, byteorder)
        except ValueError:
            fenum = FakeEnum(cls.__name__)
            status, data = basic.uint8_t.deserialize(data, byteorder)
            return fenum(f"unknown_0x{status:02x}", status), data


@attr.s
class Parameter:
    """Parameter."""

    name = attr.ib(converter=str)
    type = attr.ib()
    description = attr.ib(default="")
