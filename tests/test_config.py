import enum

import pytest
from voluptuous import Invalid

import zigpy_znp.config as conf


def test_EnumValue():
    class TestEnum(enum.Enum):
        foo = 123
        BAR = 456

    assert conf.EnumValue(TestEnum)("foo") == TestEnum.foo
    assert conf.EnumValue(TestEnum)("BAR") == TestEnum.BAR

    assert conf.EnumValue(TestEnum, transformer=str.lower)("FOO") == TestEnum.foo
    assert conf.EnumValue(TestEnum, transformer=str.upper)("bar") == TestEnum.BAR

    assert conf.EnumValue(TestEnum)(TestEnum.foo) == TestEnum.foo
    assert conf.EnumValue(TestEnum)(TestEnum.BAR) == TestEnum.BAR


def test_pin_states_same_lengths():
    # Bare schema works
    conf.CONFIG_SCHEMA(
        {
            conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: "/dev/null"},
            conf.CONF_ZNP_CONFIG: {},
        }
    )

    # So does one with explicitly specified pin states
    config = conf.CONFIG_SCHEMA(
        {
            conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: "/dev/null"},
            conf.CONF_ZNP_CONFIG: {
                conf.CONF_CONNECT_RTS_STATES: ["on", True, 0, 0, 0, 1, 1],
                conf.CONF_CONNECT_DTR_STATES: ["off", False, 1, 0, 0, 1, 1],
            },
        }
    )

    assert config[conf.CONF_ZNP_CONFIG][conf.CONF_CONNECT_RTS_STATES] == [
        True,
        True,
        False,
        False,
        False,
        True,
        True,
    ]
    assert config[conf.CONF_ZNP_CONFIG][conf.CONF_CONNECT_DTR_STATES] == [
        False,
        False,
        True,
        False,
        False,
        True,
        True,
    ]


def test_pin_states_different_lengths():
    # They must be the same length
    with pytest.raises(Invalid):
        conf.CONFIG_SCHEMA(
            {
                conf.CONF_DEVICE: {conf.CONF_DEVICE_PATH: "/dev/null"},
                conf.CONF_ZNP_CONFIG: {
                    conf.CONF_CONNECT_RTS_STATES: [1, 1, 0],
                    conf.CONF_CONNECT_DTR_STATES: [1, 1],
                },
            }
        )
