import typing
import inspect
import dataclasses

import zigpy.types as zigpy_t

import zigpy_znp.types as t


class ListSubclass(list):
    # So we can call `setattr()` on it
    pass


def get_type_size_and_alignment(obj, *, align=False):
    if issubclass(obj, (zigpy_t.FixedIntType, t.FixedIntType)):
        return obj._size, obj._size if align else 1
    elif issubclass(obj, zigpy_t.EUI64):
        return 8, 1
    elif issubclass(obj, zigpy_t.KeyData):
        return 16, 1
    elif issubclass(obj, t.AddrModeAddress):
        return 1 + 8, 1
    elif issubclass(obj, CStruct):
        return obj.get_size(align=align), obj.get_alignment(align=align)
    else:
        raise ValueError(f"Cannot get size of unknown object: {obj!r}")


class Union:
    def __init_subclass__(cls):
        super().__init_subclass__()

        def __new__(cls, *args, **kwargs) -> "Union":
            instance = super().__new__(cls)

            return instance

        cls.__new__ = __new__


class CStruct:
    def __init_subclass__(cls):
        super().__init_subclass__()

        # We generate fields up here to fail early (and cache it)
        fields = cls.fields()

        # We dynamically create our subclass's `__new__` method
        def __new__(cls, *args, **kwargs) -> "CStruct":
            # Like a copy constructor
            if len(args) == 1 and isinstance(args[0], cls):
                if kwargs:
                    raise ValueError(
                        f"Cannot use copy constructor with kwargs: " f"{kwargs!r}"
                    )

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
                    for f in cls.fields()
                ]
            )

            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()

            instance = super().__new__(cls)

            # Set and convert the attributes to their respective types
            for name, value in bound.arguments.items():
                field = getattr(fields, name)

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

        # Finally, attach the above __new__ classmethod to our subclass
        cls.__new__ = __new__

    @classmethod
    def fields(cls) -> typing.List["CStructField"]:
        fields = ListSubclass()

        # We need both to throw type errors in case a field is not annotated
        annotations = cls.__annotations__
        variables = vars(cls)

        # `set(annotations) | set(variables)` doesn't preserve order, which we need
        for name in list(annotations) + [v for v in variables if v not in annotations]:
            # It's a lot easier to debug when things break immediately instead of
            # fields being silently skipped
            if hasattr(cls, name):
                field = getattr(cls, name)

                if not isinstance(field, CStructField):
                    if name.startswith("_") or name.isupper():
                        # _foo and FOO are considered constants and ignored
                        continue
                    elif isinstance(field, property):
                        # Ignore properties
                        continue
                    elif inspect.isfunction(field) or inspect.ismethod(field):
                        # Ignore methods and overridden functions
                        continue

                    # Everything else is an error
                    raise TypeError(
                        f"Field {name!r}={field!r} is not a constant or a field"
                    )
            else:
                field = CStructField(name)

            field = field.replace(name=name)

            if name in annotations:
                annotation = annotations[name]

                if field.type is not None and field.type != annotation:
                    raise TypeError(
                        f"Field {name!r} type annotation conflicts with provided type:"
                        f" {annotation} != {field.type}"
                    )

                field = field.replace(type=annotation)

            fields.append(field)
            setattr(fields, field.name, field)

        return fields

    def assigned_fields(self, *, strict=False) -> typing.List["CStructField"]:
        assigned_fields = ListSubclass()

        for field in self.fields():
            value = getattr(self, field.name)

            # Missing non-optional required fields cause an error if strict
            if value is None and strict:
                raise ValueError(f"Value for field {field.name} is required")

            assigned_fields.append((field, value))
            setattr(assigned_fields, field.name, (field, value))

        return assigned_fields

    def as_dict(self) -> typing.Dict[str, typing.Any]:
        return {f.name: v for f, v in self.assigned_fields()}

    @classmethod
    def get_padded_fields(
        cls, *, align=False
    ) -> typing.Iterable[typing.Tuple[int, int, "CStructField"]]:
        offset = 0

        for field in cls.fields():
            size, alignment = get_type_size_and_alignment(field.type, align=align)
            padding = (-offset) % alignment
            offset += padding + size

            yield padding, size, field

    @classmethod
    def get_alignment(cls, *, align=False) -> int:
        alignments = []

        for field in cls.fields():
            size, alignment = get_type_size_and_alignment(field.type, align=align)
            alignments.append(alignment)

        return max(alignments)

    @classmethod
    def get_size(cls, *, align=False) -> int:
        total_size = 0

        for padding, size, field in cls.get_padded_fields(align=align):
            total_size += padding + size

        final_padding = (-total_size) % cls.get_alignment(align=align)

        return total_size + final_padding

    def serialize(self, *, align=False) -> bytes:
        result = b""

        for padding, size, field in self.get_padded_fields(align=align):
            value = field.type(getattr(self, field.name))

            result += b"\xFF" * padding

            if isinstance(value, CStruct):
                result += value.serialize(align=align)
            else:
                result += value.serialize()

        final_padding = b"\xFF" * (self.get_size(align=align) - len(result))

        return result + final_padding

    @classmethod
    def deserialize(cls, data: bytes, *, align=False) -> typing.Tuple["CStruct", bytes]:
        instance = cls()

        orig_length = len(data)
        expected_size = cls.get_size(align=align)

        if orig_length < expected_size:
            raise ValueError(
                f"Data is too short, must be at least {expected_size} bytes: {data!r}"
            )

        for padding, _, field in cls.get_padded_fields(align=align):
            if len(data) < padding:
                raise ValueError(
                    f"Data is too short to contain {padding} padding bytes"
                )

            data = data[padding:]

            if issubclass(field.type, CStruct):
                value, data = field.type.deserialize(data, align=align)
            else:
                value, data = field.type.deserialize(data)

            setattr(instance, field.name, value)

        # Strip off the final padding
        data = data[expected_size - (orig_length - len(data)) :]

        return instance, data

    def replace(self, **kwargs) -> "CStruct":
        d = self.as_dict().copy()
        d.update(kwargs)

        return type(self)(**d)

    def __eq__(self, other: "CStruct") -> bool:
        if not isinstance(self, type(other)) and not isinstance(other, type(self)):
            return False

        return self.as_dict() == other.as_dict()

    def __repr__(self) -> str:
        kwargs = ", ".join([f"{k}={v!r}" for k, v in self.as_dict().items()])
        return f"{type(self).__name__}({kwargs})"


@dataclasses.dataclass(frozen=True)
class CStructField:
    name: typing.Optional[str] = None
    type: typing.Optional[type] = None

    def replace(self, **kwargs) -> "CStructField":
        return dataclasses.replace(self, **kwargs)
