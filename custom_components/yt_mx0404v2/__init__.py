"""Support for MX0404V2 HDMI Matrix."""
import logging
import typing
import asyncio

from .tcpprotocol import create_mx0404_client_connection
import voluptuous as vol

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.helpers.service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, HomeAssistantType, ServiceCallType
from homeassistant.helpers.dispatcher import (
    async_dispatcher_send,
    async_dispatcher_connect,
)

from .const import (
    CONNECTION_TIMEOUT,
    CONF_INPUTS1,
    CONF_INPUTS2,
    CONF_INPUTS3,
    CONF_INPUTS4,
    DEFAULT_INPUTS1,
    DEFAULT_INPUTS2,
    DEFAULT_INPUTS3,
    DEFAULT_INPUTS4,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_NAME,
    DEFAULT_RECONNECT_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DATA_DEVICE_REGISTER = "yt_mx0404v2_device_register"
DATA_DEVICE_OPTIONS = "yt_mx0404v2_device_options"

# CONFIG_SCHEMA = vol.Schema(
#     {
#         DOMAIN: vol.Schema(
#             {
#                 vol.All(
#                     {   
#                         vol.Optional(CONF_NAME): cv.string,
#                         vol.Required(CONF_HOST): cv.string,
#                         vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
#                         vol.Required(CONF_INPUTS1, default=DEFAULT_INPUTS1): cv.string,
#                         vol.Required(CONF_INPUTS2, default=DEFAULT_INPUTS2): cv.string,
#                         vol.Required(CONF_INPUTS3, default=DEFAULT_INPUTS3): cv.string,
#                         vol.Required(CONF_INPUTS4, default=DEFAULT_INPUTS4): cv.string,
#                         vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_POLLING_INTERVAL): cv.positive_int,
#                     }
#                 )
#             }
#         )
#     },
#     extra=vol.ALLOW_EXTRA,
# )

async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    """Component setup, do nothing."""
    # if DOMAIN not in config:
    #     return True

    # for device_id in config[DOMAIN]:
    #     conf = config[DOMAIN][device_id]
    #     hass.async_create_task(
    #         hass.config_entries.flow.async_init(
    #             DOMAIN,
    #             context={"source": SOURCE_IMPORT},
    #             data={CONF_NAME: conf[CONF_NAME], CONF_HOST: conf[CONF_HOST], CONF_PORT: conf[CONF_PORT], \
    #                   CONF_INPUTS1: conf[CONF_INPUTS1], CONF_INPUTS2: conf[CONF_INPUTS2], \
    #                   CONF_INPUTS3: conf[CONF_INPUTS3], CONF_INPUTS4: conf[CONF_INPUTS4],
    #                   CONF_SCAN_INTERVAL: conf[CONF_SCAN_INTERVAL]},
    #         )
    #     )
    return True
    
async def async_setup_entry(hass, entry):
    """Set up the YT-MX0404V2 switch."""
    hass.data.setdefault(DOMAIN, {})
    name = entry.data[CONF_NAME]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    inputs = [entry.data[CONF_INPUTS1], entry.data[CONF_INPUTS2], entry.data[CONF_INPUTS3], entry.data[CONF_INPUTS4]]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]
    address = f"{host}:{port}"

    hass.data[DOMAIN][entry.entry_id] = {}
    hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_OPTIONS] = inputs

    @callback
    def disconnected():
        """Schedule reconnect after connection has been lost."""
        _LOGGER.warning("YT-MX0404V2 %s disconnected", address)
        async_dispatcher_send(hass, f'yt_mx0404v2_device_available_{entry.entry_id}', False)

    @callback
    def reconnected():
        """Schedule reconnect after connection has been lost."""
        _LOGGER.warning("YT-MX0404V2 %s connected", address)
        async_dispatcher_send(hass, f'yt_mx0404v2_device_available_{entry.entry_id}', True)

    async def connect():
        """Set up connection and hook it into HA for reconnect/shutdown."""
        _LOGGER.info("Initiating YT-MX0404V2 connection to %s", address)

        client = await create_mx0404_client_connection(
            host=host,
            port=port,
            disconnect_callback=disconnected,
            reconnect_callback=reconnected,
            loop=hass.loop,
            timeout=CONNECTION_TIMEOUT,
            polling_interval=scan_interval,
            reconnect_interval=DEFAULT_RECONNECT_INTERVAL,
        )

        hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_REGISTER] = client

        # Load entites
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "input_select")
        )

        _LOGGER.info("Connected to YT-MX0404V2 device: %s", address)

    hass.loop.create_task(connect())

    return True

async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    client = hass.data[DOMAIN][entry.entry_id].pop(DATA_DEVICE_REGISTER)
    client.stop()
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "input_select")

    if unload_ok:
        if hass.data[DOMAIN][entry.entry_id]:
            hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok

class MX0404V2Device(Entity):
    """Representation of a YT-MX0404V2 device.
    Contains the common logic for YT-MX0404V2 entities.
    """

    def __init__(self, device_output_port, entry_id, client, options):
        """Initialize the device."""
        # YT-MX0404V2 specific attributes for every component type
        self._entry_id = entry_id
        self._device_output_port = device_output_port
        self._current_option = None
        self._client = client
        self._select_options = options
        self._name = f'{DOMAIN}_output_{device_output_port}'

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._entry_id}_{self._device_output_port}"

    @callback
    def handle_event_callback(self, event):
        """Propagate changes through ha."""
        _LOGGER.info("Input_select %s new state callback: %r", self.unique_id, event)
        if self._current_option != self._select_options[event-1]:
            self._current_option = self._select_options[event-1]
            _LOGGER.info(f"current_option: {self._current_option}")
            self.async_write_ha_state()

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def name(self):
        """Return a name for the device."""
        return self._name

    @property
    def available(self):
        """Return True if entity is available."""
        return bool(self._client.is_connected)

    @callback
    def _availability_callback(self, availability):
        """Update availability state."""
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Register update callback."""
        self._client.register_status_callback(
            self.handle_event_callback, self._device_output_port
        )
        _LOGGER.info(f'callback is {self._client.status_callbacks.get(self._device_output_port, [])}')
        loop = asyncio.get_event_loop()
        asyncio.ensure_future(self._client.status(), loop=loop)
        self._current_option = self._select_options[self._client.states[f'o{self._device_output_port}']-1]
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"yt_mx0404v2_device_available_{self._entry_id}",
                self._availability_callback,
            )
        )