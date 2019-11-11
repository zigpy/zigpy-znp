import attr

from . import basic as t
from . import named as named_t
from . import struct as struct_t


@attr.s
class GeneralFrame(struct_t.Struct):
    length = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
    command = attr.ib(
        factory=named_t.Command, type=named_t.Command, converter=named_t.Command
    )
    data = attr.ib(factory=t.Bytes, type=t.Bytes, converter=t.Bytes)

    @classmethod
    def deserialize(cls, payload):
        """Deserialize frame and sanity checks."""
        length, payload = t.uint8_t.deserialize(payload)
        if length > 250 or len(payload) < length + 2:
            raise ValueError(f"Invalid data: {payload}")
        cmd, payload = named_t.Command.deserialize(payload)
        payload, data = payload[:length], payload[length:]
        return cls(length, cmd, payload), data

    @data.validator
    def data_validator(self, attribute, value):
        """Len of data should not exceed 250 bytes."""
        if len(value) > 250:
            raise ValueError(f"Invalid data length: {len(value)}")

    def serialize(self):
        """Serialize Frame."""
        self.length = t.uint8_t(len(self.data))
        return super().serialize()
