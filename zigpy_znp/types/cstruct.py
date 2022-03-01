from __future__ import annotations

import typing
import inspect
import dataclasses

import zigpy.types as zigpy_t

import zigpy_znp.types as t


class ListSubclass(list):
    # So we can call `setattr()` on it
    pass


@dataclasses.dataclass(frozen=True)
class CStructField:
    name: str
    type: type

    def __post_init__(self) -> None:
        # Throw an error early
        self.get_size_and_alignment()

    def get_size_and_alignment(self, align=False) -> tuple[int, int]:
        if issubclass(self.type, (zigpy_t.FixedIntType, t.FixedIntType)):
            return self.type._size, (self.type._size if align else 1)
        elif issubclass(self.type, zigpy_t.EUI64):
            return 8, 1
        elif issubclass(self.type, zigpy_t.KeyData):
            return 16, 1
        elif issubclass(self.type, CStruct):
            return self.type.get_size(align=align), self.type.get_alignment(align=align)
        elif issubclass(self.type, t.AddrModeAddress):
            return 1 + 8, 1
        else:
            raise TypeError(f"Cannot get size of unknown type: {self.type!r}")


class CStruct:
    _padding_byte = b"\xFF"

    def __init_subclass__(cls):
        super().__init_subclass__()

        fields = ListSubclass()

        for name, annotation in typing.get_type_hints(cls).items():
            try:
                field = CStructField(name=name, type=annotation)
            except Exception as e:
                raise TypeError(f"Invalid field {name}={annotation!r}") from e

            fields.append(field)
            setattr(fields, field.name, field)

        cls.fields = fields

    def __new__(cls, *args, **kwargs) -> CStruct:
        # Like a copy constructor
        if len(args) == 1 and isinstance(args[0], cls):
            if kwargs:
                raise ValueError(f"Cannot use copy constructor with kwargs: {kwargs!r}")

            kwargs = args[0].as_dict()
            args = ()

        # Pretend our signature is `__new__(cls, p1: t1, p2: t2, ...)`
        signature = inspect.Signature(
            parameters=[
                inspect.Parameter(
                    name=f.name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=None,
                    annotation=f.type,
                )
                for f in cls.fields
            ]
        )

        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        instance = super().__new__(cls)

        # Set and convert the attributes to their respective types
        for name, value in bound.arguments.items():
            field = getattr(cls.fields, name)

            if value is not None:
                try:
                    value = field.type(value)
                except Exception as e:
                    raise ValueError(
                        f"Failed to convert {name}={value!r} from type"
                        f" {type(value)} to {field.type}"
                    ) from e

            setattr(instance, name, value)

        return instance

    def as_dict(self) -> dict[str, typing.Any]:
        return {f.name: getattr(self, f.name) for f in self.fields}

    @classmethod
    def get_padded_fields(
        cls, *, align=False
    ) -> typing.Iterable[tuple[int, int, CStructField]]:
        offset = 0

        for field in cls.fields:
            size, alignment = field.get_size_and_alignment(align=align)
            padding = (-offset) % alignment
            offset += padding + size

            yield padding, size, field

    @classmethod
    def get_alignment(cls, *, align=False) -> int:
        alignments = []

        for field in cls.fields:
            size, alignment = field.get_size_and_alignment(align=align)
            alignments.append(alignment)

        return max(alignments)

    @classmethod
    def get_size(cls, *, align=False) -> int:
        total_size = 0

        for padding, size, _field in cls.get_padded_fields(align=align):
            total_size += padding + size

        final_padding = (-total_size) % cls.get_alignment(align=align)

        return total_size + final_padding

    def serialize(self, *, align=False) -> bytes:
        result = b""

        for padding, _, field in self.get_padded_fields(align=align):
            value = getattr(self, field.name)

            if value is None:
                raise ValueError(f"Field {field} cannot be empty")

            try:
                value = field.type(value)
            except Exception as e:
                raise ValueError(
                    f"Failed to convert {field.name}={value!r} from type"
                    f" {type(value)} to {field.type}"
                ) from e

            result += self._padding_byte * padding

            if isinstance(value, CStruct):
                result += value.serialize(align=align)
            else:
                result += value.serialize()

        # Pad the result to our final length
        return result.ljust(self.get_size(align=align), self._padding_byte)

    @classmethod
    def deserialize(cls, data: bytes, *, align=False) -> tuple[CStruct, bytes]:
        instance = cls()

        orig_length = len(data)
        expected_size = cls.get_size(align=align)

        if orig_length < expected_size:
            raise ValueError(
                f"Data is too short, must be at least {expected_size} bytes: {data!r}"
            )

        for padding, _, field in cls.get_padded_fields(align=align):
            data = data[padding:]

            if issubclass(field.type, CStruct):
                value, data = field.type.deserialize(data, align=align)
            else:
                value, data = field.type.deserialize(data)

            setattr(instance, field.name, value)

        # Strip off the final padding
        data = data[expected_size - (orig_length - len(data)) :]

        return instance, data

    def replace(self, **kwargs) -> CStruct:
        d = self.as_dict().copy()
        d.update(kwargs)

        return type(self)(**d)

    def __eq__(self, other: object) -> bool:
        if not isinstance(self, type(other)) and not isinstance(other, type(self)):
            return NotImplemented

        return self.as_dict() == other.as_dict()

    def __repr__(self) -> str:
        kwargs = ", ".join([f"{k}={v!r}" for k, v in self.as_dict().items()])
        return f"{type(self).__name__}({kwargs})"
