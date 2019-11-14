import attr

from . import basic as t


class Struct:
    """Structure based on attr."""

    @classmethod
    def deserialize(cls, data: bytes):
        """Deserialize structure."""
        args, data = t.deserialize(data, cls.schema())
        return cls(*args), data

    @classmethod
    def schema(cls):
        """Return schema of the class."""
        return (a.type for a in attr.fields(cls))

    def serialize(self):
        """Serialize Structure."""
        values = self.as_tuple()
        return b"".join(v.serialize() for v in values)

    def as_tuple(self):
        """Return tuple of fields values."""
        names = (f.name for f in attr.fields(self.__class__))
        return (getattr(self, n) for n in names)

    @staticmethod
    def converter(_type):
        """Pass through converter."""

        def converter(input):
            if isinstance(input, _type):
                return input
            try:
                return _type(*input)
            except TypeError:
                return _type(input)

        return converter
