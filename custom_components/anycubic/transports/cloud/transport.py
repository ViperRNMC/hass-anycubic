"""Cloud transport using Anycubic cloud API + MQTT callbacks."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .sdk import AnycubicAuthMode, AnycubicMQTTAPI
from ...const import CONF_PRINTER_ID, CONF_USER_AUTH_MODE, CONF_USER_DEVICE_ID, CONF_USER_TOKEN, DOMAIN
from ...const import CLOUD_AUTH_MODE_ANDROID, CLOUD_AUTH_MODE_SLICER, CLOUD_AUTH_MODE_WEB
from ..base import AnycubicTransport

_LOGGER = logging.getLogger(__name__)

AUTH_MODE_LABELS: dict[AnycubicAuthMode, str] = {
    AnycubicAuthMode.WEB: "web",
    AnycubicAuthMode.SLICER: "slicer",
    AnycubicAuthMode.ANDROID: "android",
}


class CloudTransport(AnycubicTransport):
    """Cloud transport that normalizes cloud printer state to coordinator format."""

    _PERIODIC_REAUTH_FAILURE_THRESHOLD = 3

    _SPEED_OPTION_ALIASES: dict[str, str] = {
        "silent": "silent",
        "quiet": "silent",
        "standard": "standard",
        "normal": "standard",
        "sport": "sport",
    }

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._api: AnycubicMQTTAPI | None = None
        self._on_data: Callable[[dict], None] | None = None
        self._mqtt_task: asyncio.Task | None = None
        self._auth_check_task: asyncio.Task | None = None
        self._selected_printer = None
        self._printers: list[Any] = []
        self._reauth_started = False
        self._mqtt_auth_fingerprint: tuple[Any, ...] | None = None
        self._consecutive_periodic_auth_failures = 0

    async def async_setup(self, on_data: Callable[[dict], None]) -> None:
        self._on_data = on_data
        await self._setup_api()
        await self._load_printers()
        await self._start_mqtt()
        await self.async_query_topic("initial")

    async def _setup_api(self) -> None:
        token = self._entry.data.get(CONF_USER_TOKEN)
        if not token:
            raise ValueError("Cloud mode requires user_token")

        cookie_jar = CookieJar(unsafe=True)
        websession = async_create_clientsession(self._hass, cookie_jar=cookie_jar)
        self._api = AnycubicMQTTAPI(
            session=websession,
            cookie_jar=cookie_jar,
            debug_logger=_LOGGER,
            mqtt_callback_printer_update=self._mqtt_callback_printer_update,
            mqtt_callback_disconnected=self._mqtt_callback_disconnected,
            mqtt_callback_connect_failed=self._mqtt_callback_connect_failed,
        )

        auth_mode_raw = self._entry.data.get(CONF_USER_AUTH_MODE)
        configured_mode: AnycubicAuthMode | None = None
        if isinstance(auth_mode_raw, str):
            mode_name = auth_mode_raw.strip().lower()
            if mode_name == CLOUD_AUTH_MODE_WEB:
                configured_mode = AnycubicAuthMode.WEB
            elif mode_name == CLOUD_AUTH_MODE_SLICER:
                configured_mode = AnycubicAuthMode.SLICER
            elif mode_name == CLOUD_AUTH_MODE_ANDROID:
                configured_mode = AnycubicAuthMode.ANDROID
        elif auth_mode_raw is not None:
            try:
                configured_mode = AnycubicAuthMode(int(auth_mode_raw))
            except Exception:
                configured_mode = None

        mode_candidates: list[AnycubicAuthMode] = []
        if configured_mode is not None:
            mode_candidates.append(configured_mode)
        for mode in (AnycubicAuthMode.SLICER, AnycubicAuthMode.WEB, AnycubicAuthMode.ANDROID):
            if mode not in mode_candidates:
                mode_candidates.append(mode)

        success = False
        selected_mode: AnycubicAuthMode | None = None
        for mode in mode_candidates:
            self._api.set_authentication(
                auth_token=token,
                auth_mode=mode,
                device_id=self._entry.data.get(CONF_USER_DEVICE_ID),
            )
            try:
                if await self._api.check_api_tokens():
                    success = True
                    selected_mode = mode
                    break
            except Exception as err:
                _LOGGER.debug("Cloud auth attempt failed for mode %s: %s", mode, err)

        if not success:
            raise ValueError("Cloud auth failed")

        if selected_mode is not None and self._entry.data.get(CONF_USER_AUTH_MODE) != selected_mode.name.lower():
            self._update_entry_data({CONF_USER_AUTH_MODE: selected_mode.name.lower()})

        mode_label = AUTH_MODE_LABELS.get(selected_mode, str(selected_mode).lower() if selected_mode is not None else "unknown")
        mode_value = int(selected_mode) if selected_mode is not None else "unknown"
        _LOGGER.info("Cloud auth successful using mode %s (%s)", mode_value, mode_label)

    async def _load_printers(self) -> None:
        if not self._api:
            return
        printers = await self._api.list_my_printers(ignore_init_errors=True)
        self._printers = [p for p in printers if p is not None]
        if not self._printers:
            raise ValueError("No cloud printers found for this account")

        configured_printer_id = self._entry.data.get(CONF_PRINTER_ID)
        self._selected_printer = None
        if configured_printer_id is not None:
            for printer in self._printers:
                if str(getattr(printer, "id", "")) == str(configured_printer_id):
                    self._selected_printer = printer
                    break

        if self._selected_printer is None:
            self._selected_printer = self._printers[0]

        selected_printer_id = getattr(self._selected_printer, "id", None)
        if selected_printer_id is not None and str(self._entry.data.get(CONF_PRINTER_ID, "")) != str(selected_printer_id):
            self._update_entry_data({CONF_PRINTER_ID: selected_printer_id})

        self._api.mqtt_add_subscribed_printer(self._selected_printer)
        try:
            await self._selected_printer.update_info_from_api(with_project=True)
        except Exception as err:
            _LOGGER.debug("Initial cloud printer refresh failed: %s", err)

    async def _start_mqtt(self) -> None:
        if not self._api:
            return

        async def _run_mqtt_forever() -> None:
            await self._hass.async_add_executor_job(self._api.connect_mqtt)

        self._mqtt_task = self._hass.async_create_background_task(
            _run_mqtt_forever(), name="anycubic_mqtt_forever"
        )
        connected = await self._api.mqtt_wait_for_connect()
        if not connected:
            if self._mqtt_task:
                self._mqtt_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._mqtt_task
                self._mqtt_task = None
            raise ValueError("Cloud MQTT connect timed out")
        self._mqtt_auth_fingerprint = self._get_mqtt_auth_fingerprint()

    def _mqtt_callback_printer_update(self) -> None:
        self._hass.loop.call_soon_threadsafe(self._emit_normalized_snapshot)

    def _mqtt_callback_disconnected(self, rc: int) -> None:
        self._hass.loop.call_soon_threadsafe(self._schedule_auth_check, f"mqtt_disconnect:{rc}")

    def _mqtt_callback_connect_failed(self, rc: int) -> None:
        self._hass.loop.call_soon_threadsafe(self._schedule_auth_check, f"mqtt_connect_failed:{rc}")

    def _emit_normalized_snapshot(self) -> None:
        if not self._selected_printer or not self._on_data:
            return

        p = self._selected_printer

        firmware = None
        firmware_available = None
        if p.fw_version is not None:
            firmware = getattr(p.fw_version, "firmware_version", None)
            firmware_available = getattr(p.fw_version, "available_version", None)

        dynamic_speed_map = self._build_print_speed_mode_map(
            p.latest_project_available_print_speed_modes_data_object
        )

        print_data = {
            "state": p.latest_project_print_status,
            "progress": p.latest_project_progress_percentage,
            "curr_layer": p.latest_project_print_current_layer,
            "z_thickness": p.latest_project_print_z_up_height,
            "filename": p.latest_project_name,
            "image_url": p.latest_project_image_url,
            "print_time": p.latest_project_print_time_elapsed_minutes,
            "remain_time": p.latest_project_print_time_remaining_minutes,
            "supplies_usage": p.latest_project_print_supplies_usage,
            "total_layers": p.latest_project_print_total_layers,
            "target_nozzle_temp": p.latest_project_target_nozzle_temp,
            "target_hotbed_temp": p.latest_project_target_hotbed_temp,
            "print_speed_mode": p.latest_project_print_speed_mode,
            "fan_speed_pct": p.latest_project_fan_speed_pct,
            "source_info": {
                "models": [{"name": p.latest_project_name}] if p.latest_project_name else []
            },
        }

        multi_color_box: list[dict[str, Any]] = []
        primary_slots = p.primary_multi_color_box_spool_info_object or []
        secondary_slots = p.secondary_multi_color_box_spool_info_object or []

        if p.connected_ace_units >= 1:
            multi_color_box.append(
                {
                    "id": 1,
                    "temp": p.primary_multi_color_box_current_temperature,
                    "auto_feed": p.primary_multi_color_box_auto_feed,
                    "drying_status": {
                        "status": 1 if p.primary_drying_status_is_drying else 0,
                        "target_temp": p.primary_drying_status_target_temperature,
                        "duration": p.primary_drying_status_total_duration,
                        "remain_time": p.primary_drying_status_remaining_time,
                    },
                    "slots": primary_slots,
                    "loaded_slot": p.primary_multi_color_box_loaded_slot,
                    "firmware": p.primary_multi_color_box_fw_firmware_version,
                }
            )

        if p.connected_ace_units >= 2:
            multi_color_box.append(
                {
                    "id": 2,
                    "temp": p.secondary_multi_color_box_current_temperature,
                    "auto_feed": p.secondary_multi_color_box_auto_feed,
                    "drying_status": {
                        "status": 1 if p.secondary_drying_status_is_drying else 0,
                        "target_temp": p.secondary_drying_status_target_temperature,
                        "duration": p.secondary_drying_status_total_duration,
                        "remain_time": p.secondary_drying_status_remaining_time,
                    },
                    "slots": secondary_slots,
                    "loaded_slot": p.secondary_multi_color_box_loaded_slot,
                    "firmware": p.secondary_multi_color_box_fw_firmware_version,
                }
            )

        printer_ip = (
            getattr(p, "ip", None)
            or getattr(p, "ip_address", None)
            or getattr(p, "local_ip", None)
        )

        normalized = {
            "info": {
                "type": "info",
                "data": {
                    "state": p.current_status,
                    "printer_online": p.printer_online,
                    "model": p.machine_name,
                    "ip": printer_ip,
                    "mac": p.machine_mac,
                    "version": firmware,
                    "available_version": firmware_available,
                    "project": {
                        "state": p.latest_project_print_status,
                        "progress": p.latest_project_progress_percentage,
                    },
                    "print_speed_mode": p.latest_project_print_speed_mode,
                    "print_speed_mode_map": dynamic_speed_map,
                },
            },
            "print": {"type": "print", "data": print_data},
            "tempature": {
                "type": "tempature",
                "data": {
                    "curr_nozzle_temp": p.curr_nozzle_temp,
                    "curr_hotbed_temp": p.curr_hotbed_temp,
                },
            },
            "fan": {
                "type": "fan",
                "data": {
                    "fan_speed_pct": p.latest_project_fan_speed_pct,
                    "aux_fan_speed_pct": p.aux_fan_speed_pct,
                    "box_fan_level": p.box_fan_level,
                },
            },
            "multiColorBox": {
                "type": "multiColorBox",
                "data": {"multi_color_box": multi_color_box},
            },
        }
        self._on_data(normalized)

    @classmethod
    def _build_print_speed_mode_map(cls, mode_data: Any) -> dict[str, int]:
        """Build a stable option->mode map from cloud-provided speed mode metadata."""
        result: dict[str, int] = {}
        if not isinstance(mode_data, list):
            return result

        for item in mode_data:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description", "")).strip().lower()
            if not description:
                continue
            mode_value = item.get("mode")
            if mode_value is None:
                continue
            try:
                mode_int = int(mode_value)
            except (TypeError, ValueError):
                continue

            canonical = cls._SPEED_OPTION_ALIASES.get(description)
            if canonical is None:
                continue
            result[canonical] = mode_int

        return result

    async def async_send_command(self, msg_type: str, action: str, data: Any = None) -> None:
        if not self._selected_printer:
            return
        printer = self._selected_printer

        if msg_type == "print":
            if action == "pause":
                await printer.pause_print()
                return
            if action == "resume":
                await printer.resume_print()
                return
            if action in ("stop", "cancel"):
                await printer.cancel_print()
                return
            if action == "setPrintSpeedMode" and isinstance(data, dict):
                await printer.change_print_setting_speed_mode(int(data.get("print_speed_mode", 0)))
                return
            if action == "setNozzleTemp" and isinstance(data, dict):
                await printer.change_print_setting_target_nozzle_temp(int(data.get("target_nozzle_temp", 0)))
                return
            if action == "setHotbedTemp" and isinstance(data, dict):
                await printer.change_print_setting_target_hotbed_temp(int(data.get("target_hotbed_temp", 0)))
                return
            if action == "setFanSpeed" and isinstance(data, dict):
                await printer.change_print_setting_fan_speed_pct(int(data.get("fan_speed_pct", 0)))
                return
            if action == "setAuxFanSpeed" and isinstance(data, dict):
                await printer.change_print_setting_aux_fan_speed_pct(int(data.get("aux_fan_speed_pct", 0)))
                return

        if msg_type == "fan" and action == "auto" and isinstance(data, dict):
            if "fan_speed_pct" in data:
                await printer.change_print_setting_fan_speed_pct(int(data.get("fan_speed_pct", 0)))
            if "aux_fan_speed_pct" in data:
                await printer.change_print_setting_aux_fan_speed_pct(int(data.get("aux_fan_speed_pct", 0)))
            return

        if msg_type == "light" and action == "control" and isinstance(data, dict):
            if self._api is not None:
                light_on = bool(int(data.get("status", 0)))
                light_type = int(data.get("type", 1))
                project = getattr(printer, "latest_project", None)
                if project is None:
                    try:
                        await printer.update_info_from_api(with_project=True)
                        project = getattr(printer, "latest_project", None)
                    except Exception as err:
                        _LOGGER.debug("Cloud light: failed to refresh project before command: %s", err)
                if project is None:
                    _LOGGER.debug("Cloud light: skipping command because project context is unavailable")
                    return
                await self._api._send_order_set_light_status(
                    printer=printer,
                    project=project,
                    light_on=light_on,
                    light_type=light_type,
                )
            return

        if msg_type == "multiColorBox" and isinstance(data, dict):
            boxes = data.get("multi_color_box") or []
            if boxes:
                box = boxes[0]
                box_id = int(box.get("id", 1)) - 1
                if action == "setAutoFeed":
                    enabled = bool(int(box.get("auto_feed", 0)))
                    await printer.multi_color_box_set_auto_feed(enabled=enabled, box_id=box_id)
                    return
                if action == "setDry":
                    ds = box.get("drying_status") or {}
                    status = int(ds.get("status", 0))
                    if status == 1:
                        await printer.multi_color_box_drying_start(
                            duration=int(ds.get("duration", 0)),
                            target_temp=int(ds.get("target_temp", 0)),
                            box_id=box_id,
                        )
                    else:
                        await printer.multi_color_box_drying_stop(box_id=box_id)
                    return

        _LOGGER.debug("Cloud command not mapped yet: %s/%s (%s)", msg_type, action, data)

    async def async_query_topic(self, topic: str, action: str = "query") -> None:
        if not self._selected_printer:
            return
        try:
            await self._selected_printer.update_info_from_api(with_project=True)
        except Exception as err:
            _LOGGER.debug("Cloud query refresh failed: %s", err)
        self._emit_normalized_snapshot()

    async def async_refresh_credentials(self) -> None:
        await self._async_auth_health_check("periodic_refresh")

    async def async_teardown(self) -> None:
        if self._auth_check_task:
            self._auth_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._auth_check_task
            self._auth_check_task = None
        if self._api and self._api.mqtt_is_started:
            await self._hass.async_add_executor_job(self._api.disconnect_mqtt)
            await self._api.mqtt_wait_for_disconnect()
        if self._mqtt_task:
            self._mqtt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._mqtt_task
            self._mqtt_task = None

    def _schedule_auth_check(self, reason: str) -> None:
        if self._auth_check_task and not self._auth_check_task.done():
            return
        self._auth_check_task = self._hass.async_create_background_task(
            self._async_auth_health_check(reason), name=f"anycubic_auth_check_{reason}"
        )

    async def _async_auth_health_check(self, reason: str) -> None:
        if not self._api:
            return

        is_periodic_refresh = reason == "periodic_refresh"

        try:
            authenticated = await self._api.check_api_tokens()
        except Exception as err:
            _LOGGER.debug("Cloud auth health check failed during %s: %s", reason, err)
            if is_periodic_refresh:
                self._consecutive_periodic_auth_failures += 1
                _LOGGER.warning(
                    "Cloud auth check error during periodic refresh (%d/%d); postponing reauth",
                    self._consecutive_periodic_auth_failures,
                    self._PERIODIC_REAUTH_FAILURE_THRESHOLD,
                )
                if self._consecutive_periodic_auth_failures < self._PERIODIC_REAUTH_FAILURE_THRESHOLD:
                    return
            await self._start_reauth(reason)
            return

        if not authenticated:
            if is_periodic_refresh:
                self._consecutive_periodic_auth_failures += 1
                _LOGGER.warning(
                    "Cloud auth check returned unauthenticated during periodic refresh (%d/%d)",
                    self._consecutive_periodic_auth_failures,
                    self._PERIODIC_REAUTH_FAILURE_THRESHOLD,
                )
                if self._consecutive_periodic_auth_failures < self._PERIODIC_REAUTH_FAILURE_THRESHOLD:
                    return
            await self._start_reauth(reason)
            return

        self._consecutive_periodic_auth_failures = 0

        new_fingerprint = self._get_mqtt_auth_fingerprint()
        if new_fingerprint != self._mqtt_auth_fingerprint:
            _LOGGER.info("Cloud auth changed during %s; restarting MQTT session", reason)
            self._mqtt_auth_fingerprint = new_fingerprint
            if self._api.mqtt_is_started:
                await self._restart_mqtt()

    async def _restart_mqtt(self) -> None:
        if not self._api:
            return
        if self._api.mqtt_is_started:
            await self._hass.async_add_executor_job(self._api.disconnect_mqtt)
            await self._api.mqtt_wait_for_disconnect()
        if self._mqtt_task:
            self._mqtt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._mqtt_task
            self._mqtt_task = None
        await self._start_mqtt()

    async def _start_reauth(self, reason: str) -> None:
        if self._reauth_started:
            return
        self._reauth_started = True
        _LOGGER.warning("Cloud authentication requires reauth (%s)", reason)
        await self._hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": self._entry.entry_id},
            data=self._entry.data,
        )

    def _get_mqtt_auth_fingerprint(self) -> tuple[Any, ...] | None:
        if not self._api:
            return None
        auth = self._api.anycubic_auth
        auth_config = auth.get_auth_config_dict()
        return (
            getattr(auth, "api_user_email", None),
            getattr(auth, "api_user_id", None),
            auth_config.get("auth_token"),
            auth_config.get("auth_access_token"),
            auth_config.get("device_id"),
            auth_config.get("auth_mode"),
        )

    def _update_entry_data(self, updates: dict[str, Any]) -> None:
        new_data = {**self._entry.data, **updates}
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)
