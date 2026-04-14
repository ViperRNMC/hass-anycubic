"""Config flow for the unified Anycubic integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import (
    CONF_CONNECTION_MODE,
    CONF_USER_AUTH_MODE,
    CONF_USER_DEVICE_ID,
    CONF_USER_TOKEN,
    CLOUD_AUTH_MODE_ANDROID,
    CLOUD_AUTH_MODE_SLICER,
    CLOUD_AUTH_MODE_WEB,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    DOMAIN,
)
from .helper.api import AnycubicAPI

STEP_CHOOSE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_MODE, default=CONNECTION_MODE_LAN): vol.In(
            [CONNECTION_MODE_LAN, CONNECTION_MODE_CLOUD]
        ),
    }
)

STEP_LAN_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})

STEP_CLOUD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_AUTH_MODE, default=CLOUD_AUTH_MODE_SLICER): vol.In(
            [CLOUD_AUTH_MODE_WEB, CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]
        ),
        vol.Required(CONF_USER_TOKEN): str,
        vol.Optional(CONF_USER_DEVICE_ID): str,
    }
)


class AnycubicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for selecting LAN or Cloud mode."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_CHOOSE_SCHEMA)

        mode = user_input[CONF_CONNECTION_MODE]
        if mode == CONNECTION_MODE_CLOUD:
            return await self.async_step_cloud()
        return await self.async_step_lan()

    async def async_step_lan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                api = AnycubicAPI(host)
                printer_data = await self.hass.async_add_executor_job(api.discover)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                unique_id = printer_data.get("deviceId", host)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=printer_data.get("modelName", f"Anycubic @ {host}"),
                    data={
                        CONF_CONNECTION_MODE: CONNECTION_MODE_LAN,
                        CONF_HOST: host,
                        **printer_data,
                    },
                )

        return self.async_show_form(step_id="lan", data_schema=STEP_LAN_SCHEMA, errors=errors)

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="cloud", data_schema=STEP_CLOUD_SCHEMA)

        token = user_input[CONF_USER_TOKEN]
        await self.async_set_unique_id(f"cloud_{token[:16]}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Anycubic Cloud",
            data={
                CONF_CONNECTION_MODE: CONNECTION_MODE_CLOUD,
                CONF_USER_AUTH_MODE: user_input.get(CONF_USER_AUTH_MODE, CLOUD_AUTH_MODE_SLICER),
                CONF_USER_TOKEN: token,
                CONF_USER_DEVICE_ID: user_input.get(CONF_USER_DEVICE_ID, ""),
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates={
                    CONF_USER_AUTH_MODE: user_input.get(CONF_USER_AUTH_MODE, CLOUD_AUTH_MODE_SLICER),
                    CONF_USER_TOKEN: user_input[CONF_USER_TOKEN],
                    CONF_USER_DEVICE_ID: user_input.get(CONF_USER_DEVICE_ID, ""),
                },
            )

        reauth_schema = vol.Schema(
            {
                vol.Required(
                    CONF_USER_AUTH_MODE,
                    default=self._reauth_entry.data.get(CONF_USER_AUTH_MODE, CLOUD_AUTH_MODE_SLICER),
                ): vol.In([CLOUD_AUTH_MODE_WEB, CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]),
                vol.Required(CONF_USER_TOKEN): str,
                vol.Optional(
                    CONF_USER_DEVICE_ID,
                    default=self._reauth_entry.data.get(CONF_USER_DEVICE_ID, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=reauth_schema)
