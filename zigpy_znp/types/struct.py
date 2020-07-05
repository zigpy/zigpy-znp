import attr
import typing


class Struct:
    """Structure based on attr."""

    @classmethod
    def deserialize(cls, data: bytes):
        """Deserialize structure."""

        args = []

        for field_type in cls.schema():
            arg, data = field_type.deserialize(data)
            args.append(arg)

        return cls(*args), data

    @classmethod
    def fields(cls):
        return attr.fields(cls)

    @classmethod
    def schema(cls):
        """Return schema of the class."""
        return (a.type for a in cls.fields())

    def serialize(self):
        """Serialize Structure."""
        values = self.as_tuple()
        return b"".join(v.serialize() for v in values)

    def as_tuple(self):
        """Return tuple of fields values."""
        names = (f.name for f in self.fields())
        return (getattr(self, n) for n in names)

    @staticmethod
    def converter(_type) -> typing.Callable:
        """Pass through converter."""

        def converter(input):
            if isinstance(input, _type):
                return input

            return _type(input)

        return converter
