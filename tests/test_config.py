import enum

from zigpy_znp.config import EnumValue


def test_EnumValue():
    class TestEnum(enum.Enum):
        foo = 123
        BAR = 456

    assert EnumValue(TestEnum)("foo") == TestEnum.foo
    assert EnumValue(TestEnum)("BAR") == TestEnum.BAR

    assert (
        EnumValue(TestEnum, transformer=lambda s: str(s).lower())("FOO") == TestEnum.foo
    )
    assert (
        EnumValue(TestEnum, transformer=lambda s: str(s).upper())("bar") == TestEnum.BAR
    )

    assert EnumValue(TestEnum)(TestEnum.foo) == TestEnum.foo
    assert EnumValue(TestEnum)(TestEnum.BAR) == TestEnum.BAR
