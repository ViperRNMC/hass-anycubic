"""Config flow for the Anycubic integration (LAN + Cloud)."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from aiohttp import CookieJar

from .const import (
    DOMAIN,
    FILAMENT_DIAMETER_MM,
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_LAN,
    CONNECTION_MODE_CLOUD,
    CONF_USER_TOKEN,
    CONF_USER_AUTH_MODE,
    CONF_USER_DEVICE_ID,
    CONF_PRINTER_ID_LIST,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .lan.api import AnycubicAPI as AnycubicLANAPI
from .cloud.anycubic_api import AnycubicMQTTAPI as AnycubicCloudAPI
from .cloud.models.auth import AnycubicAuthMode
from .helper.mapper import AnycubicMQTTConnectMode, remove_quotes_from_string

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LAN schemas
# ---------------------------------------------------------------------------
STEP_LAN_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
})

# ---------------------------------------------------------------------------
# Cloud schemas
# ---------------------------------------------------------------------------
DATA_SCHEMA_AUTH_WEB = vol.Schema({vol.Required(CONF_USER_TOKEN): cv.string})
DATA_SCHEMA_AUTH_SLICER = vol.Schema({vol.Required(CONF_USER_TOKEN): cv.string})
DATA_SCHEMA_AUTH_ANDROID = vol.Schema({
    vol.Required(CONF_USER_TOKEN): cv.string,
    vol.Required(CONF_USER_DEVICE_ID): cv.string,
})

MQTT_CONNECT_MODES = {
    AnycubicMQTTConnectMode.Printing_Only: "Printing Only",
    AnycubicMQTTConnectMode.Printing_Drying: "Printing & Drying",
    AnycubicMQTTConnectMode.Device_Online: "Device Online",
    AnycubicMQTTConnectMode.Always: "Always",
    AnycubicMQTTConnectMode.Never_Connect: "Never Connect",
}

# ---------------------------------------------------------------------------
# LAN helpers
# ---------------------------------------------------------------------------

async def _validate_lan_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate LAN host input."""
    host = data[CONF_HOST]
    api = AnycubicLANAPI(host)
    try:
        printer_data = await hass.async_add_executor_job(api.discover)
    except Exception as exc:
        raise CannotConnect from exc
    return {
        "title": printer_data.get("modelName", f"Anycubic @ {host}"),
        "device_data": printer_data,
    }


# ---------------------------------------------------------------------------
# Cloud helpers
# ---------------------------------------------------------------------------

def _create_cloud_api(
    hass: HomeAssistant,
    auth_token: str | None,
    auth_mode: AnycubicAuthMode | int | None = None,
    device_id: str | None = None,
) -> AnycubicCloudAPI:
    if not auth_token:
        raise Exception("Missing auth token.")
    cookie_jar = CookieJar(unsafe=True)
    websession = async_create_clientsession(hass, cookie_jar=cookie_jar)
    api = AnycubicCloudAPI(session=websession, cookie_jar=cookie_jar, debug_logger=_LOGGER)
    api.set_authentication(auth_token=auth_token, auth_mode=auth_mode, device_id=device_id)
    return api


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class AnycubicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anycubic (LAN or Cloud)."""

    VERSION = 1

    def __init__(self) -> None:
        # Cloud state
        self._user_token: str | None = None
        self._user_auth_mode: AnycubicAuthMode | int | None = None
        self._user_device_id: str | None = None
        self._cloud_api: AnycubicCloudAPI | None = None
        self._is_reauth: bool = False
        self._is_reconfigure: bool = False
        self.entry = None

    @staticmethod
    def async_get_options_flow(config_entry):
        return AnycubicOptionsFlowHandler(config_entry)

    # ------------------------------------------------------------------
    # Entry point — show connection mode menu
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the connection mode menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["lan_setup", "cloud_auth_mode_pick"],
        )

    # ------------------------------------------------------------------
    # LAN steps
    # ------------------------------------------------------------------

    async def async_step_lan_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """LAN: enter printer host/IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _validate_lan_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during LAN setup")
                errors["base"] = "unknown"
            else:
                host = user_input[CONF_HOST]
                unique_id = info["device_data"].get("deviceId", host)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_CONNECTION_MODE: CONNECTION_MODE_LAN,
                        CONF_HOST: host,
                        **info["device_data"],
                    },
                )

        return self.async_show_form(
            step_id="lan_setup",
            data_schema=STEP_LAN_DATA_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Cloud steps
    # ------------------------------------------------------------------

    async def async_step_cloud_auth_mode_pick(
        self, _: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud: choose authentication method."""
        return self.async_show_menu(
            step_id="cloud_auth_mode_pick",
            menu_options=["cloud_auth_web", "cloud_auth_slicer", "cloud_auth_android"],
        )

    async def async_step_cloud_auth_web(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_web",
            auth_mode=AnycubicAuthMode.WEB,
            auth_schema=DATA_SCHEMA_AUTH_WEB,
            user_input=user_input,
        )

    async def async_step_cloud_auth_slicer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_slicer",
            auth_mode=AnycubicAuthMode.SLICER,
            auth_schema=DATA_SCHEMA_AUTH_SLICER,
            user_input=user_input,
        )

    async def async_step_cloud_auth_android(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_android",
            auth_mode=AnycubicAuthMode.ANDROID,
            auth_schema=DATA_SCHEMA_AUTH_ANDROID,
            user_input=user_input,
        )

    async def _handle_cloud_auth_step(
        self,
        step_id: str,
        auth_mode: AnycubicAuthMode,
        auth_schema: vol.Schema,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_cloud_credentials(auth_mode, user_input)
            if not errors:
                if self._is_reauth and self.entry:
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={
                            **self.entry.data,
                            CONF_USER_TOKEN: self._user_token,
                            CONF_USER_AUTH_MODE: self._user_auth_mode,
                            CONF_USER_DEVICE_ID: self._user_device_id,
                        },
                    )
                    return self.async_abort(reason="reauth_successful")
                return await self.async_step_cloud_printer()

        return self.async_show_form(
            step_id=step_id,
            data_schema=auth_schema,
            errors=errors,
        )

    async def _validate_cloud_credentials(
        self,
        auth_mode: AnycubicAuthMode,
        user_input: dict[str, Any],
    ) -> dict[str, str]:
        try:
            self._user_token = remove_quotes_from_string(user_input[CONF_USER_TOKEN])
        except TypeError:
            self._user_token = user_input[CONF_USER_TOKEN]

        self._user_auth_mode = auth_mode
        self._user_device_id = user_input.get(CONF_USER_DEVICE_ID)

        try:
            self._cloud_api = _create_cloud_api(
                self.hass, self._user_token, self._user_auth_mode, self._user_device_id
            )
            success = await self._cloud_api.check_api_tokens()
            if not success:
                return {"base": "invalid_auth"}
        except Exception as error:
            tb = traceback.format_exc()
            _LOGGER.debug("Cloud auth error: %s\n%s", error, tb)
            return {"base": "cannot_connect"}

        return {}

    async def async_step_cloud_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud: select printer(s)."""
        errors: dict[str, str] = {}
        printer_id_map: dict[str, str] = {}

        try:
            assert self._cloud_api
            printer_list = await self._cloud_api.list_my_printers(ignore_init_errors=True)
            if not printer_list:
                errors = {"base": "no_printers"}
            else:
                printer_id_map = {f"{p.id}": p.name for p in printer_list}
        except Exception as error:
            tb = traceback.format_exc()
            _LOGGER.debug("Error listing printers: %s\n%s", error, tb)
            errors = {"base": "cannot_connect"}

        if user_input and not errors:
            printer_id_list = [int(x) for x in user_input[CONF_PRINTER_ID_LIST]]
            selected_names = [
                printer_id_map.get(str(pid), str(pid))
                for pid in printer_id_list
            ]
            if len(selected_names) == 1:
                entry_title = f"Anycubic Cloud - {selected_names[0]}"
            else:
                entry_title = f"Anycubic Cloud ({len(selected_names)} printers)"
            assert self._cloud_api
            await self.async_set_unique_id(
                f"cloud_{self._cloud_api.anycubic_auth.api_user_id}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=entry_title,
                data={
                    CONF_CONNECTION_MODE: CONNECTION_MODE_CLOUD,
                    CONF_USER_TOKEN: self._user_token,
                    CONF_USER_AUTH_MODE: self._user_auth_mode,
                    CONF_USER_DEVICE_ID: self._user_device_id,
                    CONF_PRINTER_ID_LIST: printer_id_list,
                },
            )

        return self.async_show_form(
            step_id="cloud_printer",
            data_schema=vol.Schema({
                vol.Required(CONF_PRINTER_ID_LIST): cv.multi_select(printer_id_map),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Re-auth / reconfigure
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._is_reauth = True
        self.entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        mode = (entry_data or {}).get(CONF_CONNECTION_MODE, CONNECTION_MODE_LAN)
        if mode == CONNECTION_MODE_CLOUD:
            return await self.async_step_cloud_auth_mode_pick()
        return await self.async_step_lan_setup()

    async def async_step_reconfigure(self, _: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._is_reconfigure = True
        self.entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        mode = (self.entry.data if self.entry else {}).get(CONF_CONNECTION_MODE, CONNECTION_MODE_LAN)
        if mode == CONNECTION_MODE_CLOUD:
            return await self.async_step_cloud_reauth_or_printer()
        return await self.async_step_lan_setup()

    async def async_step_cloud_reauth_or_printer(self, _: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu: choose to re-auth or pick different printer."""
        return self.async_show_menu(
            step_id="cloud_reauth_or_printer",
            menu_options=["cloud_auth_mode_pick", "cloud_printer"],
        )


# ---------------------------------------------------------------------------
# Options flow — supports in-place mode switching
# ---------------------------------------------------------------------------

class AnycubicOptionsFlowHandler(OptionsFlow):
    """Handle options for Anycubic integration (supports switching between LAN and Cloud)."""

    def __init__(self, config_entry):
        # config_entry is handled by base OptionsFlow class, don't set it directly
        self._new_mode: str | None = None
        self._user_token: str | None = None
        self._user_auth_mode: AnycubicAuthMode | int | None = None
        self._user_device_id: str | None = None
        self._printer_id_list: list[int] | None = None
        self._cloud_api: AnycubicCloudAPI | None = None

    def _current_mode(self) -> str:
        return (
            self.config_entry.options.get(CONF_CONNECTION_MODE)
            or self.config_entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_LAN)
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "switch_mode"],
        )

    # ------------------------------------------------------------------
    # Settings (filament diameter etc.)
    # ------------------------------------------------------------------

    async def async_step_settings(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        current = self.config_entry.options
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Optional(
                    "filament_diameter_mm",
                    default=current.get("filament_diameter_mm", FILAMENT_DIAMETER_MM),
                ): vol.Coerce(float)
            }),
        )

    # ------------------------------------------------------------------
    # Mode switch
    # ------------------------------------------------------------------

    async def async_step_switch_mode(self, user_input: dict[str, Any] | None = None):
        """Let the user pick a new connection mode."""
        if user_input is not None:
            self._new_mode = user_input[CONF_CONNECTION_MODE]
            if self._new_mode == self._current_mode():
                # No actual change — just go back to settings
                return await self.async_step_settings()

            if self._new_mode == CONNECTION_MODE_CLOUD:
                # If we already stored cloud credentials, switch immediately
                if self.config_entry.data.get(CONF_USER_TOKEN):
                    return await self._save_mode_switch()
                return await self.async_step_cloud_auth_mode_pick()
            else:
                # Switching to LAN — if host already known, switch immediately
                if self.config_entry.data.get(CONF_HOST):
                    return await self._save_mode_switch()
                return await self.async_step_lan_setup()

        return self.async_show_form(
            step_id="switch_mode",
            data_schema=vol.Schema({
                vol.Required(CONF_CONNECTION_MODE, default=self._current_mode()): vol.In({
                    CONNECTION_MODE_LAN: "LAN / Wi-Fi (direct connection)",
                    CONNECTION_MODE_CLOUD: "Cloud (Anycubic account)",
                })
            }),
            description_placeholders={"current_mode": self._current_mode()},
        )

    # ------------------------------------------------------------------
    # LAN credential step (when switching to LAN without a stored host)
    # ------------------------------------------------------------------

    async def async_step_lan_setup(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate_lan_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                # Persist new LAN credentials into entry.data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_HOST: user_input[CONF_HOST],
                        **info["device_data"],
                    },
                )
                self._new_mode = CONNECTION_MODE_LAN
                return await self._save_mode_switch()

        return self.async_show_form(
            step_id="lan_setup",
            data_schema=STEP_LAN_DATA_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Cloud credential steps (when switching to Cloud)
    # ------------------------------------------------------------------

    async def async_step_cloud_auth_mode_pick(self, _: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="cloud_auth_mode_pick",
            menu_options=["cloud_auth_web", "cloud_auth_slicer", "cloud_auth_android"],
        )

    async def async_step_cloud_auth_web(self, user_input: dict[str, Any] | None = None):
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_web",
            auth_mode=AnycubicAuthMode.WEB,
            auth_schema=DATA_SCHEMA_AUTH_WEB,
            user_input=user_input,
        )

    async def async_step_cloud_auth_slicer(self, user_input: dict[str, Any] | None = None):
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_slicer",
            auth_mode=AnycubicAuthMode.SLICER,
            auth_schema=DATA_SCHEMA_AUTH_SLICER,
            user_input=user_input,
        )

    async def async_step_cloud_auth_android(self, user_input: dict[str, Any] | None = None):
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_android",
            auth_mode=AnycubicAuthMode.ANDROID,
            auth_schema=DATA_SCHEMA_AUTH_ANDROID,
            user_input=user_input,
        )

    async def _handle_cloud_auth_step(
        self,
        step_id: str,
        auth_mode: AnycubicAuthMode,
        auth_schema: vol.Schema,
        user_input: dict[str, Any] | None = None,
    ):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._validate_cloud_credentials(auth_mode, user_input)
            if not errors:
                return await self.async_step_cloud_printer()

        return self.async_show_form(step_id=step_id, data_schema=auth_schema, errors=errors)

    async def _validate_cloud_credentials(
        self, auth_mode: AnycubicAuthMode, user_input: dict[str, Any]
    ) -> dict[str, str]:
        try:
            self._user_token = remove_quotes_from_string(user_input[CONF_USER_TOKEN])
        except TypeError:
            self._user_token = user_input[CONF_USER_TOKEN]
        self._user_auth_mode = auth_mode
        self._user_device_id = user_input.get(CONF_USER_DEVICE_ID)
        try:
            self._cloud_api = _create_cloud_api(
                self.hass, self._user_token, self._user_auth_mode, self._user_device_id
            )
            if not await self._cloud_api.check_api_tokens():
                return {"base": "invalid_auth"}
        except Exception as error:
            _LOGGER.debug("Options cloud auth error: %s", error)
            return {"base": "cannot_connect"}
        return {}

    async def async_step_cloud_printer(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        printer_id_map: dict[str, str] = {}
        try:
            assert self._cloud_api
            printer_list = await self._cloud_api.list_my_printers(ignore_init_errors=True)
            if not printer_list:
                errors = {"base": "no_printers"}
            else:
                printer_id_map = {f"{p.id}": p.name for p in printer_list}
        except Exception as error:
            _LOGGER.debug("Options printer list error: %s", error)
            errors = {"base": "cannot_connect"}

        if user_input and not errors:
            self._printer_id_list = [int(x) for x in user_input[CONF_PRINTER_ID_LIST]]
            # Persist cloud credentials into entry.data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_USER_TOKEN: self._user_token,
                    CONF_USER_AUTH_MODE: self._user_auth_mode,
                    CONF_USER_DEVICE_ID: self._user_device_id,
                    CONF_PRINTER_ID_LIST: self._printer_id_list,
                },
            )
            self._new_mode = CONNECTION_MODE_CLOUD
            return await self._save_mode_switch()

        return self.async_show_form(
            step_id="cloud_printer",
            data_schema=vol.Schema({
                vol.Required(CONF_PRINTER_ID_LIST): cv.multi_select(printer_id_map),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Finalise mode switch
    # ------------------------------------------------------------------

    async def _save_mode_switch(self):
        """Save the new connection_mode to options and trigger a reload."""
        return self.async_create_entry(data={
            **self.config_entry.options,
            CONF_CONNECTION_MODE: self._new_mode,
        })


# ---------------------------------------------------------------------------
# Legacy alias (kept for backwards compatibility)
# ---------------------------------------------------------------------------

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
