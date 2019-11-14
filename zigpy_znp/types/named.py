import attr

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


@attr.s
class Parameter:
    """Parameter."""

    name = attr.ib(converter=str)
    type = attr.ib()
    description = attr.ib(default="")
