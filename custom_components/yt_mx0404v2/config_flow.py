"""Config flow for MX0404V2 HDMI Matrix."""
import asyncio

from .tcpprotocol import create_mx0404_client_connection
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

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
from .errors import AlreadyConfigured, CannotConnect

DATA_SCHEMA = vol.Schema(
    {   
        vol.Optional(CONF_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_INPUTS1, default=DEFAULT_INPUTS1): cv.string,
        vol.Required(CONF_INPUTS2, default=DEFAULT_INPUTS2): cv.string,
        vol.Required(CONF_INPUTS3, default=DEFAULT_INPUTS3): cv.string,
        vol.Required(CONF_INPUTS4, default=DEFAULT_INPUTS4): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_POLLING_INTERVAL): cv.positive_int,
    }
)

async def connect_client(hass, user_input):
    """Connect the MX0404V2 client."""
    client_aw = create_mx0404_client_connection(
        host=user_input[CONF_HOST],
        port=user_input[CONF_PORT],
        loop=hass.loop,
        timeout=CONNECTION_TIMEOUT,
        polling_interval=user_input[CONF_SCAN_INTERVAL],
        reconnect_interval=DEFAULT_RECONNECT_INTERVAL,
    )
    return await asyncio.wait_for(client_aw, timeout=CONNECTION_TIMEOUT)

async def validate_input(hass: HomeAssistant, user_input):
    """Validate the user input allows us to connect."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (
            entry.data[CONF_HOST] == user_input[CONF_HOST]
            and entry.data[CONF_PORT] == user_input[CONF_PORT]
        ):
            raise AlreadyConfigured

    try:
        client = await connect_client(hass, user_input)
    except asyncio.TimeoutError:
        raise CannotConnect
    try:

        def disconnect_callback():
            if client.in_transaction:
                client.active_transaction.set_exception(CannotConnect)

        client.disconnect_callback = disconnect_callback
        await client.status()
    except CannotConnect:
        client.disconnect_callback = None
        client.stop()
        raise CannotConnect
    else:
        client.disconnect_callback = None
        client.stop()


class MX0404FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a YT-MX0404V2 config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_import(self, user_input):
        """Handle import."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
                address = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                return self.async_create_entry(title=address, data=user_input)
            except AlreadyConfigured:
                errors["base"] = "already_configured"
            except CannotConnect:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )