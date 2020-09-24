import os
import logging
import importlib

from homeassistant.core import HomeAssistant
from homeassistant.config import YAML_CONFIG_FILE, load_yaml_config_file
from homeassistant.__main__ import get_arguments
from homeassistant.util.package import install_package

LOGGER = logging.getLogger(__name__)
DOMAIN = "zha_custom_radios"


def setup(hass, config):
    """
    No-op. This code runs way too late to do anything useful.
    """
    return True


def inject_enum_member(target_enum, name, value):
    """
    Hack to inject a new member into an enum.
    """

    member = target_enum._member_type_.__new__(target_enum)
    member._name_ = name
    member._value_ = value

    if not isinstance(value, tuple):
        args = (value,)
    else:
        args = value

    target_enum.__init__(member, *args)

    target_enum._member_names_.append(name)
    target_enum._member_map_[name] = member
    target_enum._value2member_map_[value] = member
    type.__setattr__(target_enum, name, member)


def get_ha_config():
    """
    Duplicate enough of the HA startup sequence to extract the config *really* early.
    """

    args = get_arguments()

    hass = HomeAssistant()
    hass.config.config_dir = os.path.abspath(os.path.join(os.getcwd(), args.config))

    return load_yaml_config_file(hass.config.path(YAML_CONFIG_FILE))


def inject(config):
    """
    Injects new ZHA radio modules specified in the YAML config.
    """

    try:
        from homeassistant.components.zha.core.const import RadioType
    except ImportError:
        LOGGER.error(
            "It looks like HA has not finished setting up its dependencies yet "
            "on first launch. Restart Home Assistant once it finishes."
        )
        return

    custom_names = list(config[DOMAIN].keys())
    original_names = list(RadioType._member_names_)

    for name, obj in config[DOMAIN].items():
        module = importlib.import_module(obj["module"])
        app = module.ControllerApplication
        description = obj["description"]

        if obj.get("package"):
            install_package(obj["package"])

        LOGGER.warning("Injecting %s (%s) as a new radio type", name, obj)
        inject_enum_member(RadioType, name, (description, app))

    # New keys are moved up top
    RadioType._member_names_ = custom_names + original_names


# We are a purposefully a legacy integration so we can run this when we're imported.
# This allows us to run way before anything else has even had a chance to load.
inject(get_ha_config())
