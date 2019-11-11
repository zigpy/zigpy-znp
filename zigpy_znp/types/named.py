from . import basic


class GroupId(basic.HexRepr, basic.uint16_t):
    """"Group ID class"""

    pass


class Command(basic.uint16_t):
    """Command class."""

    pass
