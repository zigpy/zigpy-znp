import typing
import functools
import dataclasses

import zigpy_znp.types as t
from zigpy_znp.exceptions import InvalidFrame


@dataclasses.dataclass(frozen=True)
class GeneralFrame:
    header: t.CommandHeader
    data: t.Bytes

    def __post_init__(self) -> None:
        # We're frozen so `self.header = ...` is disallowed
        if not isinstance(self.header, t.CommandHeader):
            object.__setattr__(self, "header", t.CommandHeader(self.header))

        if not isinstance(self.data, t.Bytes):
            object.__setattr__(self, "data", t.Bytes(self.data))

        if self.length > 250:
            raise InvalidFrame(
                f"Frame length cannot exceed 250 bytes. Got: {self.length}"
            )

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

        header, data = t.CommandHeader.deserialize(data)
        payload, data = data[:length], data[length:]
        return cls(header, payload), data

    def serialize(self) -> bytes:
        return self.length.serialize() + self.header.serialize() + self.data.serialize()


@dataclasses.dataclass
class TransportFrame:
    """Transport frame."""

    SOF = t.uint8_t(0xFE)  # Start of frame marker

    payload: GeneralFrame

    @classmethod
    def deserialize(cls, data: bytes) -> typing.Tuple["TransportFrame", bytes]:
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
        """
        Calculates the FCS of the payload.
        """

        checksum = functools.reduce(lambda a, b: a ^ b, self.payload.serialize())
        return t.uint8_t(checksum)

    def serialize(self) -> bytes:
        return (
            self.SOF.serialize()
            + self.payload.serialize()
            + self.checksum().serialize()
        )
