"""Support for MX0404V2 HDMI Matrix."""

from homeassistant.components.input_select import InputSelect, CONF_INITIAL, CONF_OPTIONS, CONF_ID
from homeassistant.core import callback
from . import DATA_DEVICE_OPTIONS, DATA_DEVICE_REGISTER, MX0404V2Device
from .const import DOMAIN
import asyncio

def devices_from_entities(hass, entry):
    """Parse configuration and add MX0404V2 HDMI Matrix."""
    device_client = hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_REGISTER]
    options = hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_OPTIONS]
    devices = []
    for i in range(1,5):
        device_output_port = i
        device = MX0404V2InputSelect(device_output_port, entry.entry_id, device_client, options)
        devices.append(device)
    return devices

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the YT-MX0404V2 platform."""
    async_add_entities(devices_from_entities(hass, entry))


class MX0404V2InputSelect(MX0404V2Device, InputSelect):
    """Representation of a MX0404V2 HDMI Matrix."""

    def __init__(self, device_output_port, entry_id, client, options):
        MX0404V2Device.__init__(self, device_output_port, entry_id, client, options)
        try:
            options = self._select_options
        except AttributeError:
            options = ()

        config = {
            CONF_OPTIONS: options,
            CONF_ID: self._name
        }
        InputSelect.__init__(self, config)

    @callback
    def async_select_option(self, option):
        '''Select a new option.'''
        if option not in self._options:
            _LOGGER.warning(
                "Invalid option: %s (possible options: %s)",
                option,
                ", ".join(self._options),
            )
            return
        loop = asyncio.get_event_loop()
        asyncio.ensure_future(self._client.select_output(self._device_output_port, self._options.index(option)+1), loop=loop)

    @property
    def state(self):
        """Return the state of the component."""
        return self._current_option