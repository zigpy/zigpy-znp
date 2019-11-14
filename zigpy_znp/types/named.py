import attr

from . import basic


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
