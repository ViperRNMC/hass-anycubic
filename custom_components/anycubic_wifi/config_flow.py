"""Config flow for the Anycubic integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, FILAMENT_DIAMETER_MM
from .helper.api import AnycubicAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
})


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    host = data[CONF_HOST]
    api = AnycubicAPI(host)

    try:
        printer_data = await hass.async_add_executor_job(api.discover)
    except Exception as e:
        raise CannotConnect from e

    return {
        "title": printer_data.get("modelName", f"Anycubic @ {host}"),
        "device_data": printer_data,
    }


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anycubic."""

    VERSION = 1

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                host = user_input[CONF_HOST]
                printer_data = info["device_data"]
                unique_id = printer_data.get("deviceId", host)

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data={CONF_HOST: host, **printer_data},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle option flow for Anycubic integration."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options for the integration."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        vol_schema = vol.Schema(
            {
                vol.Optional(
                    "filament_diameter_mm",
                    default=current.get("filament_diameter_mm", FILAMENT_DIAMETER_MM),
                ): vol.Coerce(float)
            }
        )

        return self.async_show_form(step_id="init", data_schema=vol_schema)


def async_get_options_flow(config_entry):
    """Return the options flow for this integration."""
    return OptionsFlowHandler(config_entry)
