import pytest

import zigpy_znp.types as t


def test_struct_fields():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

    assert len(TestStruct.fields) == 2

    assert TestStruct.fields.a.name == "a"
    assert TestStruct.fields.a.type == t.uint8_t

    assert TestStruct.fields.b.name == "b"
    assert TestStruct.fields.b.type == t.uint16_t


def test_struct_field_values():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

    struct = TestStruct(a=1, b=2)
    assert struct.a == 1
    assert isinstance(struct.a, t.uint8_t)

    assert struct.b == 2
    assert isinstance(struct.b, t.uint16_t)

    # Invalid values can't be passed during construction
    with pytest.raises(ValueError):
        TestStruct(a=1, b=2 ** 32)

    struct2 = TestStruct()
    struct2.a = 1
    struct2.b = 2

    assert struct == struct2
    assert struct.serialize() == struct2.serialize()


def test_struct_methods_and_constants():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t

        def method(self):
            return self.a + self.b

        def annotated_method(self: "TestStruct") -> int:
            return self.method()

        CONSTANT1 = 1
        constant2 = "foo"
        _constant3 = "bar"

    assert len(TestStruct.fields) == 2
    assert TestStruct.fields.a == t.CStructField(name="a", type=t.uint8_t)
    assert TestStruct.fields.b == t.CStructField(name="b", type=t.uint16_t)

    assert TestStruct.CONSTANT1 == 1
    assert TestStruct.constant2 == "foo"
    assert TestStruct._constant3 == "bar"

    assert TestStruct(a=1, b=2).method() == 3


def test_struct_nesting():
    class Outer(t.CStruct):
        e: t.uint32_t

    class TestStruct(t.CStruct):
        class Inner(t.CStruct):
            c: t.uint16_t

        a: t.uint8_t
        b: Inner
        d: Outer

    assert len(TestStruct.fields) == 3
    assert TestStruct.fields.a == t.CStructField(name="a", type=t.uint8_t)
    assert TestStruct.fields.b == t.CStructField(name="b", type=TestStruct.Inner)
    assert TestStruct.fields.d == t.CStructField(name="d", type=Outer)

    assert len(TestStruct.Inner.fields) == 1
    assert TestStruct.Inner.fields.c == t.CStructField(name="c", type=t.uint16_t)

    struct = TestStruct(a=1, b=TestStruct.Inner(c=2), d=Outer(e=3))
    assert struct.a == 1
    assert struct.b.c == 2
    assert struct.d.e == 3


def test_struct_aligned_serialization_deserialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t
        c: t.uint32_t
        d: t.uint8_t
        e: t.uint32_t
        f: t.uint8_t

    expected = b""
    expected += t.uint8_t(1).serialize()
    expected += b"\xFF" + t.uint16_t(2).serialize()
    expected += t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += b"\xFF\xFF\xFF" + t.uint32_t(5).serialize()
    expected += t.uint8_t(6).serialize()
    expected += b"\xFF\xFF\xFF"

    struct = TestStruct(a=1, b=2, c=3, d=4, e=5, f=6)
    assert struct.serialize(align=True) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=True)
    assert remaining == b"test"
    assert struct == struct2

    with pytest.raises(ValueError):
        TestStruct.deserialize(expected[:-1], align=True)


def test_struct_aligned_nested_serialization_deserialization():
    class Inner(t.CStruct):
        c: t.uint8_t
        d: t.uint32_t
        e: t.uint8_t

    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: Inner
        f: t.uint16_t

    expected = b""
    expected += t.uint8_t(1).serialize()

    # Inner struct
    expected += b"\xFF\xFF\xFF" + t.uint8_t(2).serialize()
    expected += b"\xFF\xFF\xFF" + t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += b"\xFF\xFF\xFF"  # Aligned to 4 bytes

    expected += t.uint16_t(5).serialize()
    expected += b"\xFF\xFF"  # Also aligned to 4 bytes due to inner struct

    struct = TestStruct(a=1, b=Inner(c=2, d=3, e=4), f=5)
    assert struct.serialize(align=True) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=True)
    assert remaining == b"test"
    assert struct == struct2


def test_struct_unaligned_serialization_deserialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint16_t
        c: t.uint32_t
        d: t.uint8_t
        e: t.uint32_t
        f: t.uint8_t

    expected = b""
    expected += t.uint8_t(1).serialize()
    expected += t.uint16_t(2).serialize()
    expected += t.uint32_t(3).serialize()
    expected += t.uint8_t(4).serialize()
    expected += t.uint32_t(5).serialize()
    expected += t.uint8_t(6).serialize()

    struct = TestStruct(a=1, b=2, c=3, d=4, e=5, f=6)

    assert struct.serialize(align=False) == expected

    struct2, remaining = TestStruct.deserialize(expected + b"test", align=False)
    assert remaining == b"test"
    assert struct == struct2

    with pytest.raises(ValueError):
        TestStruct.deserialize(expected[:-1], align=False)


def test_struct_equality():
    class InnerStruct(t.CStruct):
        c: t.EUI64

    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: InnerStruct

    class TestStruct2(t.CStruct):
        a: t.uint8_t
        b: InnerStruct

    s1 = TestStruct(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))
    s2 = TestStruct(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))
    s3 = TestStruct2(a=2, b=InnerStruct(c=t.EUI64.convert("00:00:00:00:00:00:00:00")))

    assert s1 == s2
    assert s1.replace(a=3) != s1
    assert s1.replace(a=3).replace(a=2) == s1

    assert s1 != s3
    assert s1.serialize() == s3.serialize()

    assert TestStruct(s1) == s1
    assert TestStruct(a=s1.a, b=s1.b) == s1

    with pytest.raises(ValueError):
        TestStruct(s1, b=InnerStruct(s1.b))

    with pytest.raises(ValueError):
        TestStruct2(s1)


def test_struct_repr():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint32_t

    assert str(TestStruct(a=1, b=2)) == "TestStruct(a=1, b=2)"
    assert str([TestStruct(a=1, b=2)]) == "[TestStruct(a=1, b=2)]"


def test_struct_bad_fields():
    with pytest.raises(TypeError):

        class TestStruct(t.CStruct):
            a: t.uint8_t
            b: int


def test_struct_incomplete_serialization():
    class TestStruct(t.CStruct):
        a: t.uint8_t
        b: t.uint8_t

    TestStruct(a=1, b=2).serialize()

    with pytest.raises(ValueError):
        TestStruct(a=1, b=None).serialize()

    with pytest.raises(ValueError):
        TestStruct(a=1).serialize()

    struct = TestStruct(a=1, b=2)
    struct.b = object()

    with pytest.raises(ValueError):
        struct.serialize()
