"""Config flow for the unified Anycubic integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_CONNECTION_MODE,
    CONF_USER_AUTH_MODE,
    CONF_USER_DEVICE_ID,
    CONF_USER_TOKEN,
    CLOUD_AUTH_MODE_ANDROID,
    CLOUD_AUTH_MODE_SLICER,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    DOMAIN,
)
from .helper.lan.api import AnycubicAPI
from .helper.cloud import AnycubicAuthMode, AnycubicMQTTAPI

_LOGGER = logging.getLogger(__name__)

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
            [CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]
        ),
        vol.Required(CONF_USER_TOKEN): str,
        vol.Optional(CONF_USER_DEVICE_ID): str,
    }
)


def _normalize_credential(value: Any) -> str:
    """Normalize copied credentials from external tools."""
    normalized = str(value).strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"\"", "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def _resolve_auth_mode(auth_mode_raw: Any) -> AnycubicAuthMode | None:
    if isinstance(auth_mode_raw, str):
        mode_name = auth_mode_raw.strip().lower()
        if mode_name == CLOUD_AUTH_MODE_SLICER:
            return AnycubicAuthMode.SLICER
        if mode_name == CLOUD_AUTH_MODE_ANDROID:
            return AnycubicAuthMode.ANDROID
        return None

    if auth_mode_raw is not None:
        try:
            parsed_mode = AnycubicAuthMode(int(auth_mode_raw))
            if parsed_mode in (AnycubicAuthMode.SLICER, AnycubicAuthMode.ANDROID):
                return parsed_mode
            return None
        except Exception:
            return None

    return None


def _build_auth_mode_candidates(auth_mode_raw: Any) -> list[AnycubicAuthMode]:
    configured_mode = _resolve_auth_mode(auth_mode_raw)
    mode_candidates: list[AnycubicAuthMode] = []
    if configured_mode is not None:
        mode_candidates.append(configured_mode)
    for mode in (AnycubicAuthMode.SLICER, AnycubicAuthMode.ANDROID):
        if mode not in mode_candidates:
            mode_candidates.append(mode)
    return mode_candidates



# --- Main branch style: robust multi-step config flow ---
class AnycubicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anycubic (LAN or Cloud)."""

    VERSION = 1

    def __init__(self) -> None:
        # Cloud state
        self._user_token: str | None = None
        self._user_auth_mode: AnycubicAuthMode | int | None = None
        self._user_device_id: str | None = None
        self._cloud_api: Any = None
        self._is_reauth: bool = False
        self._is_reconfigure: bool = False
        self.entry = None

    @staticmethod
    def async_get_options_flow(config_entry):
        return AnycubicOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the connection mode menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["lan", "cloud_auth_mode_pick"],
        )

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

    async def async_step_cloud_auth_mode_pick(
        self, _: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud: choose authentication method."""
        return self.async_show_menu(
            step_id="cloud_auth_mode_pick",
            menu_options=["cloud_auth_slicer"],
        )

    async def async_step_cloud_auth_slicer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._handle_cloud_auth_step(
            step_id="cloud_auth_slicer",
            auth_mode=AnycubicAuthMode.SLICER,
            auth_schema=vol.Schema({vol.Required(CONF_USER_TOKEN): str}),
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
            self._user_token = str(user_input[CONF_USER_TOKEN]).strip()
        except TypeError:
            self._user_token = user_input[CONF_USER_TOKEN]

        self._user_auth_mode = auth_mode
        self._user_device_id = user_input.get(CONF_USER_DEVICE_ID)

        try:
            cookie_jar = CookieJar(unsafe=True)
            websession = async_create_clientsession(self.hass, cookie_jar=cookie_jar, verify_ssl=False)
            from .helper.cloud.api import AnycubicAPIBase
            self._cloud_api = AnycubicAPIBase(session=websession, cookie_jar=cookie_jar)
            self._cloud_api.set_authentication(
                auth_token=self._user_token,
                auth_mode=self._user_auth_mode,
                device_id=self._user_device_id,
            )
            success = await self._cloud_api.check_api_tokens()
            if not success:
                return {"base": "invalid_auth"}
        except Exception as error:
            _LOGGER.debug("Cloud auth error: %s", error)
            return {"base": "cannot_connect"}
        return {}

    async def _async_validate_cloud_credentials(
        self,
        auth_mode: AnycubicAuthMode | int | str | None,
        token: str,
        device_id: str | None = None,
    ) -> AnycubicAuthMode | None:
        """Validate cloud credentials and return the selected auth mode or None.

        This is a compatibility wrapper used by flows that pass token/device_id
        as separate arguments.
        """
        resolved_mode = _resolve_auth_mode(auth_mode)
        # Build a user_input dict compatible with _validate_cloud_credentials
        ui: dict[str, Any] = {CONF_USER_TOKEN: token}
        if device_id:
            ui[CONF_USER_DEVICE_ID] = device_id

        errors = await self._validate_cloud_credentials(resolved_mode or auth_mode, ui)
        if errors:
            return None
        return resolved_mode or auth_mode

    async def async_step_cloud_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cloud: select printer(s)."""
        errors: dict[str, str] = {}
        printer_id_map: dict[str, str] = {}

        try:
            assert self._cloud_api
            printers = await self._cloud_api.get_printers()
            if not printers:
                errors = {"base": "no_printers"}
            else:
                printer_id_map = {str(p["id"]): p.get("name") or p.get("machine_name") or f"Printer {p['id']}" for p in printers}
        except Exception as error:
            _LOGGER.debug("Error listing printers: %s", error)
            errors = {"base": "cannot_connect"}

        if user_input and not errors:
            printer_id_list = [int(x) for x in user_input[CONF_PRINTER_ID_LIST]]
            selected_names = [printer_id_map.get(str(pid), str(pid)) for pid in printer_id_list]
            if len(selected_names) == 1:
                entry_title = f"Anycubic Cloud - {selected_names[0]}"
            else:
                entry_title = f"Anycubic Cloud ({len(selected_names)} printers)"
            assert self._cloud_api
            await self.async_set_unique_id(f"cloud_{self._cloud_api.anycubic_auth.api_user_id}")
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
                vol.Required(CONF_PRINTER_ID_LIST): vol.In(printer_id_map)
            }),
            errors=errors,
        )

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



    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        Step 1: Authenticate and fetch printers, then go to printer selection.
        """
        errors = {}
        if user_input is None:
            return self.async_show_form(step_id="cloud", data_schema=STEP_CLOUD_SCHEMA)

        token = _normalize_credential(user_input[CONF_USER_TOKEN])
        device_id = _normalize_credential(user_input.get(CONF_USER_DEVICE_ID, ""))
        auth_mode = user_input.get(CONF_USER_AUTH_MODE, CLOUD_AUTH_MODE_SLICER)

        if not token:
            return self.async_show_form(
                step_id="cloud",
                data_schema=STEP_CLOUD_SCHEMA,
                errors={"base": "invalid_auth"},
            )

        selected_mode = await self._async_validate_cloud_credentials(
            auth_mode=auth_mode,
            token=token,
            device_id=device_id,
        )
        if selected_mode is None:
            return self.async_show_form(
                step_id="cloud",
                data_schema=STEP_CLOUD_SCHEMA,
                errors={"base": "invalid_auth"},
            )

        # Save credentials for next step
        self._cloud_creds = {
            CONF_USER_TOKEN: token,
            CONF_USER_DEVICE_ID: device_id,
            CONF_USER_AUTH_MODE: selected_mode,
        }

        # Fetch printers using the authenticated API. Reuse the API instance
        # created during validation when possible to avoid duplicate token
        # exchanges (which trigger server rate-limits).
        from .helper.cloud.api import AnycubicAPIBase
        if hasattr(self, "_cloud_api") and self._cloud_api is not None:
            api: AnycubicAPIBase = self._cloud_api
        else:
            cookie_jar = CookieJar(unsafe=True)
            websession = async_create_clientsession(self.hass, cookie_jar=cookie_jar, verify_ssl=False)
            api = AnycubicAPIBase(session=websession, cookie_jar=cookie_jar)
            api.set_authentication(auth_token=token, auth_mode=_resolve_auth_mode(selected_mode), device_id=device_id)
        try:
            printers = await api.get_printers()
        except Exception as err:
            _LOGGER.error("Failed to fetch printers: %s", err, exc_info=True)
            return self.async_show_form(
                step_id="cloud",
                data_schema=STEP_CLOUD_SCHEMA,
                errors={"base": "cannot_connect"},
            )

        if not printers:
            return self.async_show_form(
                step_id="cloud",
                data_schema=STEP_CLOUD_SCHEMA,
                errors={"base": "no_printers_found"},
            )

        # Store printers for next step
        self._cloud_printers = printers

        # Build selection schema
        printer_choices = {str(p["id"]): p.get("name") or p.get("machine_name") or f"Printer {p['id']}" for p in printers}
        import voluptuous as vol
        PRINTER_SELECT_SCHEMA = vol.Schema({vol.Required("printer_id"): vol.In(printer_choices)})

        return self.async_show_form(
            step_id="cloud_printer",
            data_schema=PRINTER_SELECT_SCHEMA,
            description_placeholders={"printer_list": ", ".join(printer_choices.values())},
        )

    async def async_step_cloud_printer(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        Step 2: User selects a printer from the fetched list.
        """
        if not hasattr(self, "_cloud_creds") or not hasattr(self, "_cloud_printers"):
            return self.async_abort(reason="missing_context")

        if user_input is None:
            # Defensive: re-show selection if somehow called without input
            printer_choices = {str(p["id"]): p.get("name") or p.get("machine_name") or f"Printer {p['id']}" for p in self._cloud_printers}
            import voluptuous as vol
            PRINTER_SELECT_SCHEMA = vol.Schema({vol.Required("printer_id"): vol.In(printer_choices)})
            return self.async_show_form(
                step_id="cloud_printer",
                data_schema=PRINTER_SELECT_SCHEMA,
                description_placeholders={"printer_list": ", ".join(printer_choices.values())},
            )

        printer_id = user_input["printer_id"]
        printer = next((p for p in self._cloud_printers if str(p["id"]) == printer_id), None)
        if not printer:
            return self.async_abort(reason="printer_not_found")

        await self.async_set_unique_id(f"cloud_{self._cloud_creds[CONF_USER_TOKEN][:16]}_{printer_id}")
        self._abort_if_unique_id_configured()

        entry_data = {
            CONF_CONNECTION_MODE: CONNECTION_MODE_CLOUD,
            CONF_USER_AUTH_MODE: self._cloud_creds[CONF_USER_AUTH_MODE],
            CONF_USER_TOKEN: self._cloud_creds[CONF_USER_TOKEN],
            CONF_USER_DEVICE_ID: self._cloud_creds[CONF_USER_DEVICE_ID],
            "printer_id": printer_id,
            "printer_name": printer.get("name") or printer.get("machine_name"),
        }

        return self.async_create_entry(
            title=printer.get("name") or printer.get("machine_name") or f"Anycubic Cloud Printer {printer_id}",
            data=entry_data,
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
            token = _normalize_credential(user_input[CONF_USER_TOKEN])
            device_id = _normalize_credential(user_input.get(CONF_USER_DEVICE_ID, ""))
            if not token:
                reauth_schema = vol.Schema(
                    {
                        vol.Required(
                            CONF_USER_AUTH_MODE,
                            default=self._reauth_auth_mode_default(self._reauth_entry.data),
                        ): vol.In([CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]),
                        vol.Required(CONF_USER_TOKEN): str,
                        vol.Optional(
                            CONF_USER_DEVICE_ID,
                            default=self._reauth_entry.data.get(CONF_USER_DEVICE_ID, ""),
                        ): str,
                    }
                )
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=reauth_schema,
                    errors={"base": "invalid_auth"},
                )

            selected_mode = await self._async_validate_cloud_credentials(
                auth_mode=user_input.get(CONF_USER_AUTH_MODE, CLOUD_AUTH_MODE_SLICER),
                token=token,
                device_id=device_id,
            )
            if selected_mode is None:
                reauth_schema = vol.Schema(
                    {
                        vol.Required(
                            CONF_USER_AUTH_MODE,
                            default=self._reauth_auth_mode_default(self._reauth_entry.data),
                        ): vol.In([CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]),
                        vol.Required(CONF_USER_TOKEN): str,
                        vol.Optional(
                            CONF_USER_DEVICE_ID,
                            default=self._reauth_entry.data.get(CONF_USER_DEVICE_ID, ""),
                        ): str,
                    }
                )
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=reauth_schema,
                    errors={"base": "invalid_auth"},
                )

            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates={
                    CONF_USER_AUTH_MODE: selected_mode,
                    CONF_USER_TOKEN: token,
                    CONF_USER_DEVICE_ID: device_id,
                },
            )

        reauth_schema = vol.Schema(
            {
                vol.Required(
                    CONF_USER_AUTH_MODE,
                    default=self._reauth_auth_mode_default(self._reauth_entry.data),
                ): vol.In([CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_ANDROID]),
                vol.Required(CONF_USER_TOKEN): str,
                vol.Optional(
                    CONF_USER_DEVICE_ID,
                    default=self._reauth_entry.data.get(CONF_USER_DEVICE_ID, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=reauth_schema)
