import functools

import attr

from zigpy_znp.commands import CommandHeader
from zigpy_znp.exceptions import InvalidFrame
from zigpy_znp.types import basic as t


@attr.s
class GeneralFrame:
    header: CommandHeader = attr.ib(converter=CommandHeader)
    data: t.Bytes = attr.ib(factory=t.Bytes, converter=t.Bytes)

    @property
    def length(self) -> t.uint8_t:
        """Length of the frame."""
        return t.uint8_t(len(self.data))

    @classmethod
    def deserialize(cls, data):
        """Deserialize frame and sanity checks."""
        length, data = t.uint8_t.deserialize(data)

        if length > 250:
            raise InvalidFrame(f"Frame length cannot exceed 250 bytes. Got: {length}")

        if len(data) < length + 2:
            raise InvalidFrame(f"Data is too short for {cls.__name__}")

        header, data = CommandHeader.deserialize(data)
        payload, data = data[:length], data[length:]
        return cls(header, payload), data

    @data.validator
    def data_validator(self, attribute, value):
        """Len of data should not exceed 250 bytes."""
        if len(value) > 250:
            raise ValueError(f"data length: {len(value)} exceeds max 250")

    def serialize(self) -> bytes:
        """Serialize Frame."""
        return self.length.serialize() + self.header.serialize() + self.data.serialize()


@attr.s
class TransportFrame:
    """Transport frame."""

    SOF = t.uint8_t(0xFE)

    payload: GeneralFrame = attr.ib()

    @classmethod
    def deserialize(cls, data: bytes) -> "TransportFrame":
        """Deserialize frame."""
        sof, data = t.uint8_t.deserialize(data)

        if sof != cls.SOF:
            raise InvalidFrame(
                f"Expected frame to start with SOF 0x{cls.SOF:02X}, got 0x{sof:02X}"
            )

        gen_frame, data = GeneralFrame.deserialize(data)
        checksum, data = t.uint8_t.deserialize(data)

        frame = cls(gen_frame)

        if frame.checksum() != checksum:
            raise InvalidFrame(
                f"Invalid frame checksum for data {gen_frame}: "
                f"expected 0x{frame.checksum():02X}, got 0x{checksum:02X}"
            )

        return frame, data

    def checksum(self) -> t.uint8_t:
        """Calculate FCS on the payload."""
        checksum = functools.reduce(lambda a, b: a ^ b, self.payload.serialize())
        return t.uint8_t(checksum)

    def serialize(self) -> bytes:
        """Serialize data."""
        return (
            self.SOF.serialize()
            + self.payload.serialize()
            + self.checksum().serialize()
        )
