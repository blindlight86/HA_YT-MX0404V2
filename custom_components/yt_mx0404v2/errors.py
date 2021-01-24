  
"""Errors for the YT-MX0404V2 component."""
from homeassistant.exceptions import HomeAssistantError


class MX0404V2Exception(HomeAssistantError):
    """Base class for YT-MX0404V2 exceptions."""


class AlreadyConfigured(MX0404V2Exception):
    """YT-MX0404V2 is already configured."""


class CannotConnect(MX0404V2Exception):
    """Unable to connect to the YT-MX0404V2."""