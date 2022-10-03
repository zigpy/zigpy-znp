import typing
import numbers

import voluptuous as vol
from zigpy.config import (  # noqa: F401
    CONF_NWK,
    CONF_DEVICE,
    CONF_NWK_KEY,
    CONFIG_SCHEMA,
    SCHEMA_DEVICE,
    CONF_NWK_PAN_ID,
    CONF_DEVICE_PATH,
    CONF_NWK_CHANNEL,
    CONF_NWK_CHANNELS,
    CONF_NWK_UPDATE_ID,
    CONF_NWK_TC_ADDRESS,
    CONF_NWK_TC_LINK_KEY,
    CONF_NWK_EXTENDED_PAN_ID,
    CONF_MAX_CONCURRENT_REQUESTS,
    cv_boolean,
)

from zigpy_znp.commands.util import LEDMode

ConfigType = typing.Dict[str, typing.Any]

VolPositiveNumber = vol.All(numbers.Real, vol.Range(min=0))

CONF_DEVICE_BAUDRATE = "baudrate"
CONF_DEVICE_FLOW_CONTROL = "flow_control"

SCHEMA_DEVICE = SCHEMA_DEVICE.extend(
    {
        vol.Optional(CONF_DEVICE_BAUDRATE, default=115_200): int,
        vol.Optional(CONF_DEVICE_FLOW_CONTROL, default=None): vol.In(
            ("hardware", "software", None)
        ),
    }
)


def EnumValue(enum, transformer=str):
    def validator(v):
        if isinstance(v, enum):
            return v

        return enum[transformer(v)]

    return validator


def keys_have_same_length(*keys):
    def validator(config):
        lengths = [len(config[k]) for k in keys]

        if len(set(lengths)) != 1:
            raise vol.Invalid(
                f"Values for {keys} must all have the same length: {lengths}"
            )

        return config

    return validator


def bool_to_upper_str(value: typing.Any) -> str:
    """
    Converts the value into an uppercase string, including unquoted YAML booleans.
    """

    if value is True:
        return "ON"
    elif value is False:
        return "OFF"
    else:
        return str(value).upper()


def cv_deprecated(message: str) -> typing.Callable[[typing.Any], None]:
    """
    Raises a deprecation exception when a value is passed in.
    """

    def validator(value: typing.Any) -> None:
        if value is not None:
            raise vol.Invalid(message)

    return validator


CONF_ZNP_CONFIG = "znp_config"
CONF_TX_POWER = "tx_power"
CONF_LED_MODE = "led_mode"
CONF_SKIP_BOOTLOADER = "skip_bootloader"
CONF_SREQ_TIMEOUT = "sync_request_timeout"
CONF_ARSP_TIMEOUT = "async_response_timeout"
CONF_PREFER_ENDPOINT_1 = "prefer_endpoint_1"
CONF_AUTO_RECONNECT_RETRY_DELAY = "auto_reconnect_retry_delay"
CONF_CONNECT_RTS_STATES = "connect_rts_pin_states"
CONF_CONNECT_DTR_STATES = "connect_dtr_pin_states"

CONFIG_SCHEMA = CONFIG_SCHEMA.extend(
    {
        vol.Required(CONF_DEVICE): SCHEMA_DEVICE,
        vol.Optional(CONF_ZNP_CONFIG, default={}): vol.Schema(
            vol.All(
                {
                    vol.Optional(CONF_TX_POWER, default=None): vol.Any(
                        None, vol.All(int, vol.Range(min=-22, max=22))
                    ),
                    vol.Optional(CONF_SREQ_TIMEOUT, default=15): VolPositiveNumber,
                    vol.Optional(CONF_ARSP_TIMEOUT, default=30): VolPositiveNumber,
                    vol.Optional(
                        CONF_AUTO_RECONNECT_RETRY_DELAY, default=5
                    ): VolPositiveNumber,
                    vol.Optional(CONF_SKIP_BOOTLOADER, default=True): cv_boolean,
                    vol.Optional(CONF_PREFER_ENDPOINT_1, default=True): cv_boolean,
                    vol.Optional(CONF_LED_MODE, default=LEDMode.OFF): vol.Any(
                        None, EnumValue(LEDMode, transformer=bool_to_upper_str)
                    ),
                    vol.Optional(CONF_MAX_CONCURRENT_REQUESTS, default=None): (
                        cv_deprecated(
                            "`zigpy_config: znp_config: max_concurrent_requests` has"
                            " been renamed to `zigpy_config: max_concurrent_requests`."
                        )
                    ),
                    vol.Optional(
                        CONF_CONNECT_RTS_STATES, default=[False, True, False]
                    ): vol.Schema([cv_boolean]),
                    vol.Optional(
                        CONF_CONNECT_DTR_STATES, default=[False, False, False]
                    ): vol.Schema([cv_boolean]),
                },
                keys_have_same_length(CONF_CONNECT_RTS_STATES, CONF_CONNECT_DTR_STATES),
            )
        ),
    }
)
