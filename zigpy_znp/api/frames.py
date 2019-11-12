import functools

import attr

from zigpy_znp.commands import Command
from zigpy_znp.types import basic as t
from zigpy_znp.types import struct as struct_t


@attr.s
class GeneralFrame(struct_t.Struct):
    length = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)
    command = attr.ib(factory=Command, type=Command, converter=Command)
    data = attr.ib(factory=t.Bytes, type=t.Bytes, converter=t.Bytes)

    @classmethod
    def deserialize(cls, payload):
        """Deserialize frame and sanity checks."""
        length, payload = t.uint8_t.deserialize(payload)
        if length > 250 or len(payload) < length + 2:
            raise ValueError(f"Invalid data: {payload}")
        cmd, payload = Command.deserialize(payload)
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


@attr.s
class TransportFrame(struct_t.Struct):
    """Transport frame."""
    SOF = t.uint8_t(0xFE)

    sof = attr.ib(default=SOF, type=t.uint8_t, converter=t.uint8_t)
    frame = attr.ib(factory=GeneralFrame, type=GeneralFrame, converter=GeneralFrame)
    fcs = attr.ib(factory=t.uint8_t, type=t.uint8_t, converter=t.uint8_t)

    def get_fcs(self):
        """Calculate FCS on the payload."""
        fcs = functools.reduce(lambda a, b: a ^ b, self.frame)
        return t.uint8_t(fcs)

    @property
    def is_valid(self):
        """Return True if frames passes sanity check."""
        return self.sof == self.SOF and self.fcs == self.get_fcs()

    def serialize(self):
        """Serialize data."""
        return self.SOF.serialize() + self.frame.serialize() + self.get_fcs().serialize()


