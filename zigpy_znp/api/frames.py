import functools

import attr

from zigpy_znp.commands import Command
from zigpy_znp.types import basic as t, struct as struct_t


@attr.s
class GeneralFrame(struct_t.Struct):
    command = attr.ib(type=Command, converter=struct_t.Struct.converter(Command))
    data = attr.ib(factory=t.Bytes, type=t.Bytes, converter=t.Bytes)

    @property
    def length(self) -> t.uint8_t:
        """Length of the frame."""
        return t.uint8_t(len(self.data))

    @classmethod
    def deserialize(cls, data):
        """Deserialize frame and sanity checks."""
        length, data = t.uint8_t.deserialize(data)
        if length > 250 or len(data) < length + 2:
            raise ValueError(f"Data is too short for {cls.__name__}")
        cmd, data = Command.deserialize(data)
        payload, data = data[:length], data[length:]
        return cls(cmd, payload), data

    @data.validator
    def data_validator(self, attribute, value):
        """Len of data should not exceed 250 bytes."""
        if len(value) > 250:
            raise ValueError(f"data length: {len(value)} exceeds max 250")

    def serialize(self):
        """Serialize Frame."""
        return self.length.serialize() + super().serialize()


@attr.s
class TransportFrame(struct_t.Struct):
    """Transport frame."""

    SOF = t.uint8_t(0xFE)

    frame = attr.ib(
        type=GeneralFrame, converter=struct_t.Struct.converter(GeneralFrame)
    )

    @classmethod
    def deserialize(cls, data: bytes):
        """Deserialize frame."""
        sof, data = t.uint8_t.deserialize(data)
        if sof != cls.SOF:
            raise ValueError("deserialization error: invalid sof")
        gen_frame, data = GeneralFrame.deserialize(data)
        t_frame = cls(gen_frame)
        fcs, data = t.uint8_t.deserialize(data)
        if fcs != t_frame.fcs:
            raise ValueError(
                (
                    f"deserialization error: frame 0x{fcs:02x},"
                    f" calculated fcs 0x{t_frame.fcs:02x}"
                )
            )
        return t_frame, data

    @property
    def fcs(self):
        """Calculate FCS on the payload."""
        fcs = functools.reduce(lambda a, b: a ^ b, self.frame.serialize())
        return t.uint8_t(fcs)

    def serialize(self):
        """Serialize data."""
        return self.SOF.serialize() + self.frame.serialize() + self.fcs.serialize()
