"""Cloud transport using Anycubic cloud API + MQTT callbacks."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .auth import AnycubicAuthMode
from .mqtt_api import AnycubicMQTTAPI
from .. import ErrorsSystem
from ...const import DOMAIN
from ..tbase import AnycubicTransport

_LOGGER = logging.getLogger(__name__)

AUTH_MODE_LABELS: dict[AnycubicAuthMode, str] = {
    AnycubicAuthMode.SLICER: "slicer",
    AnycubicAuthMode.ANDROID: "android",
}


def _normalize_credential(value: Any) -> str:
    """Normalize user-supplied credential text from config flow inputs."""
    if value is None:
        return ""
    normalized = str(value).strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"\"", "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


class CloudTransport(AnycubicTransport):
    """Cloud transport that normalizes cloud printer state to coordinator format."""

    _PERIODIC_REAUTH_FAILURE_THRESHOLD = 3

    _SPEED_OPTION_ALIASES: dict[str, tuple[str, ...]] = {
        "silent": (
            "silent",
            "quiet",
            "still",
            "stil",
            "stille",
            "stumm",
            "静音",
        ),
        "standard": (
            "standard",
            "normal",
            "default",
            "std",
            "standaard",
            "标准",
        ),
        "sport": (
            "sport",
            "fast",
            "speed",
            "performance",
            "high",
            "turbo",
            "运动",
        ),
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
        self._camera_stream_blocked_reason: str | None = None
        self._forced_temperature_off: set[str] = set()
        self._forced_temperature_off_last_publish: dict[str, float] = {}

    async def async_setup(self, on_data: Callable[[dict], None]) -> None:
        self._on_data = on_data
        await self._setup_api()
        await self._load_printers()
        await self._start_mqtt()
        await self.async_query_topic("initial")

    async def _setup_api(self) -> None:
        token = _normalize_credential(self._entry.data.get("cloud_token"))
        if not token:
            raise ValueError(ErrorsSystem.cloud_requires_token)

        normalized_device_id = _normalize_credential(self._entry.data.get("cloud_device_id"))

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
        # Troubleshooting mode: when this integration logger is on DEBUG,
        # also emit raw MQTT publish/receive payloads.
        self._api.set_mqtt_log_all_messages(_LOGGER.isEnabledFor(logging.DEBUG))

        auth_mode_raw = self._entry.data.get("cloud_auth_mode")
        configured_mode: AnycubicAuthMode | None = None
        if isinstance(auth_mode_raw, str):
            mode_name = auth_mode_raw.strip().lower()
            if mode_name == "option_slicer":
                configured_mode = AnycubicAuthMode.SLICER
            elif mode_name == "option_android":
                configured_mode = AnycubicAuthMode.ANDROID
        elif auth_mode_raw is not None:
            try:
                parsed_mode = AnycubicAuthMode(int(auth_mode_raw))
                if parsed_mode in (AnycubicAuthMode.SLICER, AnycubicAuthMode.ANDROID):
                    configured_mode = parsed_mode
            except Exception:
                configured_mode = None

        mode_candidates: list[AnycubicAuthMode] = []
        if configured_mode is not None:
            mode_candidates.append(configured_mode)
        for mode in (AnycubicAuthMode.SLICER, AnycubicAuthMode.ANDROID):
            if mode not in mode_candidates:
                mode_candidates.append(mode)

        success = False
        selected_mode: AnycubicAuthMode | None = None

        for mode in mode_candidates:
            self._api.set_authentication(
                auth_token=token,
                auth_mode=mode,
                device_id=normalized_device_id,
            )
            try:
                if await self._api.check_api_tokens():
                    success = True
                    selected_mode = mode
                    break
            except Exception as err:
                _LOGGER.error("Cloud auth attempt failed for mode %s: %s", mode, err, exc_info=True)

            if success:
                break

        if not success:
            _LOGGER.error("Cloud authentication failed for all modes. Token: %s, Device ID: %s", token, normalized_device_id)
            raise ValueError(ErrorsSystem.cloud_auth_failed)

        updates: dict[str, Any] = {}
        if selected_mode is not None and self._entry.data.get("cloud_auth_mode") != selected_mode.name.lower():
            updates["cloud_auth_mode"] = selected_mode.name.lower()
        if token != self._entry.data.get("cloud_token"):
            updates["cloud_token"] = token
        if normalized_device_id != self._entry.data.get("cloud_device_id", ""):
            updates["cloud_device_id"] = normalized_device_id
        if updates:
            self._update_entry_data(updates)

        mode_label = AUTH_MODE_LABELS.get(selected_mode, str(selected_mode).lower() if selected_mode is not None else "unknown")
        mode_value = int(selected_mode) if selected_mode is not None else "unknown"
        _LOGGER.info("Cloud auth successful using mode %s (%s)", mode_value, mode_label)

    async def _load_printers(self) -> None:
        if not self._api:
            return
        printers = await self._api.list_my_printers(ignore_init_errors=True)
        self._printers = [p for p in printers if p is not None]
        if not self._printers:
            raise ValueError(ErrorsSystem.no_cloud_printers)

        configured_printer_id = self._entry.data.get("printer_id")
        self._selected_printer = None
        if configured_printer_id is not None:
            for printer in self._printers:
                if str(getattr(printer, "id", "")) == str(configured_printer_id):
                    self._selected_printer = printer
                    break

        if self._selected_printer is None:
            self._selected_printer = self._printers[0]

        selected_printer_id = getattr(self._selected_printer, "id", None)
        if selected_printer_id is not None and str(self._entry.data.get("printer_id", "")) != str(selected_printer_id):
            self._update_entry_data({"printer_id": selected_printer_id})

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
            raise ValueError(ErrorsSystem.cloud_mqtt_timeout)
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
        resolved_speed_mode = self._resolve_print_speed_mode(p)
        resolved_fan_speed = self._resolve_fan_speed_pct(p)
        target_nozzle_temp = self._apply_forced_temperature_off(
            "target_nozzle_temp", p.latest_project_target_nozzle_temp
        )
        target_hotbed_temp = self._apply_forced_temperature_off(
            "target_hotbed_temp", p.latest_project_target_hotbed_temp
        )

        print_data = {
            "state": p.latest_project_print_status,
            "progress": p.latest_project_progress_percentage,
            "curr_layer": p.latest_project_print_current_layer,
            # Prefer explicit print z-up height, fall back to project z_thick or model height
            "z_thickness": (
                p.latest_project_print_z_up_height
                or p.latest_project_z_thick
                or p.latest_project_print_model_height
            ),
            "filename": p.latest_project_name,
            "image_url": p.latest_project_image_url,
            "print_time": p.latest_project_print_time_elapsed_minutes,
            "remain_time": p.latest_project_print_time_remaining_minutes,
            "supplies_usage": p.latest_project_print_supplies_usage,
            "total_layers": p.latest_project_print_total_layers,
            "target_nozzle_temp": target_nozzle_temp,
            "target_hotbed_temp": target_hotbed_temp,
            "print_speed_mode": resolved_speed_mode,
            "fan_speed_pct": resolved_fan_speed,
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
                    "print_speed_mode": resolved_speed_mode,
                    "print_speed_mode_map": dynamic_speed_map,
                },
            },
            "print": {"type": "print", "data": print_data},
            "tempature": {
                "type": "tempature",
                "data": {
                    "curr_nozzle_temp": p.curr_nozzle_temp,
                    "curr_hotbed_temp": p.curr_hotbed_temp,
                    "target_nozzle_temp": target_nozzle_temp,
                    "target_hotbed_temp": target_hotbed_temp,
                },
            },
            "fan": {
                "type": "fan",
                "data": {
                    "fan_speed_pct": resolved_fan_speed,
                    "aux_fan_speed_pct": int(p.aux_fan_speed_pct or 0),
                    "box_fan_level": int(p.box_fan_level or 0),
                },
            },
            "light": {
                "type": "light",
                "data": {
                    "lights": p.light_states_data_object,
                },
            },
            "video": {
                "type": "video",
                "data": {
                    "stream_available": bool(printer_ip) and not self._camera_stream_blocked_reason,
                    "stream_reason": self._camera_stream_blocked_reason,
                    "ip": printer_ip,
                },
            },
            "multiColorBox": {
                "type": "multiColorBox",
                "data": {"multi_color_box": multi_color_box},
            },
        }
        self._on_data(normalized)

    def _apply_forced_temperature_off(self, key: str, reported_target: Any) -> int:
        """Keep heater target off even if cloud auto updates restore stale targets."""
        try:
            target = int(reported_target or 0)
        except (TypeError, ValueError):
            target = 0

        if key not in self._forced_temperature_off:
            return target

        # Bed reports 1 as effective-off on some firmware variants.
        off_threshold = 1 if key == "target_hotbed_temp" else 0
        if target <= off_threshold:
            return 0

        now = time.monotonic()
        last_publish = self._forced_temperature_off_last_publish.get(key, 0.0)
        # Guard against tight resend loops while still correcting stale auto restores.
        if now - last_publish >= 2.0:
            if self._publish_cloud_mqtt_command(
                "tempature",
                "set",
                {key: 0},
                publish_to_slicer=True,
            ):
                self._forced_temperature_off_last_publish[key] = now
                _LOGGER.debug(
                    "Cloud heater-off override reapplied for %s (reported target=%s)",
                    key,
                    target,
                )

        # Keep HA state consistent with user's explicit off command.
        return 0

    @staticmethod
    def _resolve_print_speed_mode(printer: Any) -> int | None:
        """Resolve speed mode with preference for live printer setting when idle.

        `latest_project_print_speed_mode` can reflect the last job profile and may be
        stale at startup. When not actively printing, prefer the printer-level speed
        setting updated by print settings events.
        """
        live_mode_raw = getattr(printer, "_print_speed_mode", None)
        live_mode: int | None = None
        if live_mode_raw is not None:
            try:
                live_mode = int(live_mode_raw)
            except (TypeError, ValueError):
                live_mode = None

        project_mode_raw = getattr(printer, "latest_project_print_speed_mode", None)
        project_mode: int | None = None
        if project_mode_raw is not None:
            try:
                project_mode = int(project_mode_raw)
            except (TypeError, ValueError):
                project_mode = None

        project_state = str(getattr(printer, "latest_project_print_status", "") or "").strip().lower()
        is_actively_printing = project_state in {
            "printing",
            "paused",
            "pausing",
            "resuming",
        }

        if is_actively_printing and project_mode is not None:
            return project_mode

        if live_mode is not None:
            return live_mode

        return project_mode

    @staticmethod
    def _resolve_fan_speed_pct(printer: Any) -> int | None:
        """Resolve fan speed with preference for live fan telemetry when idle."""
        live_fan_raw = getattr(printer, "fan_speed_pct", None)
        live_fan: int | None = None
        if live_fan_raw is not None:
            try:
                live_fan = int(live_fan_raw)
            except (TypeError, ValueError):
                live_fan = None

        project_fan_raw = getattr(printer, "latest_project_fan_speed_pct", None)
        project_fan: int | None = None
        if project_fan_raw is not None:
            try:
                project_fan = int(project_fan_raw)
            except (TypeError, ValueError):
                project_fan = None

        project_state = str(getattr(printer, "latest_project_print_status", "") or "").strip().lower()
        is_actively_printing = project_state in {
            "printing",
            "paused",
            "pausing",
            "resuming",
        }

        if is_actively_printing and project_fan is not None:
            return project_fan

        if live_fan is not None:
            return live_fan

        return project_fan

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

            canonical = cls._canonical_speed_option(description)
            if canonical is None:
                continue
            result[canonical] = mode_int

        return result

    @classmethod
    def _canonical_speed_option(cls, description: str) -> str | None:
        """Map a descriptive speed label to one of silent/standard/sport."""
        normalized = " ".join(description.replace("_", " ").replace("-", " ").split())
        if not normalized:
            return None

        for canonical, keywords in cls._SPEED_OPTION_ALIASES.items():
            if any(keyword in normalized for keyword in keywords):
                return canonical

        return None

    async def async_send_command(self, msg_type: str, action: str, data: Any = None) -> None:
        if not self._selected_printer:
            return
        printer = self._selected_printer

        if msg_type == "axis" and isinstance(data, dict):
            self._publish_cloud_mqtt_command("axis", action, data, publish_to_slicer=True)
            return

        if msg_type == "video":
            if action in ("startCapture", "query"):
                await self.async_open_camera_stream()
                return
            if action == "stopCapture":
                self._publish_cloud_mqtt_command("video", "stopCapture")
                return

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
                await self._send_cloud_temperature_command(
                    "target_nozzle_temp",
                    int(data.get("target_nozzle_temp", 0)),
                )
                return
            if action == "setHotbedTemp" and isinstance(data, dict):
                await self._send_cloud_temperature_command(
                    "target_hotbed_temp",
                    int(data.get("target_hotbed_temp", 0)),
                )
                return
            if action == "setFanSpeed" and isinstance(data, dict):
                await self._send_cloud_fan_command({"fan_speed_pct": int(data.get("fan_speed_pct", 0))})
                return
            if action == "setAuxFanSpeed" and isinstance(data, dict):
                await self._send_cloud_fan_command({"aux_fan_speed_pct": int(data.get("aux_fan_speed_pct", 0))})
                return

        if msg_type == "fan" and action == "auto" and isinstance(data, dict):
            fan_data: dict[str, int] = {}
            if "fan_speed_pct" in data:
                fan_data["fan_speed_pct"] = int(data.get("fan_speed_pct", 0))
            if "aux_fan_speed_pct" in data:
                fan_data["aux_fan_speed_pct"] = int(data.get("aux_fan_speed_pct", 0))
            if "box_fan_level" in data:
                fan_data["box_fan_level"] = int(data.get("box_fan_level", 0))
            if fan_data:
                await self._send_cloud_fan_command(fan_data)
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

    def _publish_cloud_mqtt_command(
        self,
        endpoint: str,
        action: str,
        data: Any = None,
        *,
        publish_to_slicer: bool = False,
    ) -> bool:
        if not self._selected_printer or self._api is None or not self._api.mqtt_is_started:
            return False

        payload: dict[str, Any] = {
            "type": endpoint,
            "action": action,
            "timestamp": int(time.time() * 1000),
            "msgid": str(uuid.uuid4()),
            "data": data,
        }
        try:
            self._api._mqtt_publish_to_printer(self._selected_printer, endpoint, payload)
            if publish_to_slicer:
                self._api._mqtt_publish_to_printer_slicer(self._selected_printer, endpoint, payload)
            return True
        except Exception as err:
            _LOGGER.debug("Cloud MQTT publish failed for %s/%s: %s", endpoint, action, err)
            return False

    async def _send_cloud_fan_command(self, fan_data: dict[str, int]) -> None:
        """Send fan changes over cloud MQTT."""
        if not self._selected_printer or self._api is None or not self._api.mqtt_is_started:
            return

        printer = self._selected_printer
        project_id = getattr(getattr(printer, "latest_project", None), "id", None)
        taskid = str(project_id) if project_id is not None else "-1"

        def _publish(endpoint: str, payload: dict[str, Any]) -> None:
            # Both topics required; firmware ignores commands on printer/public alone.
            self._api._mqtt_publish_to_printer(printer, endpoint, payload)
            self._api._mqtt_publish_to_printer_slicer(printer, endpoint, payload)

        # box_fan_level and aux_fan_speed_pct are print settings: they need a
        # print/update command to physically activate, plus fan/auto for state report.
        _keys = set(fan_data.keys())
        if _keys in ({"box_fan_level"}, {"aux_fan_speed_pct"}):
            fan_key, fan_val = next(iter(fan_data.items()))
            _publish("print", {
                "type": "print",
                "action": "update",
                "timestamp": int(time.time() * 1000),
                "msgid": str(uuid.uuid4()),
                "data": {"taskid": taskid, "settings": {fan_key: int(fan_val)}},
            })
            _publish("fan", {
                "type": "fan",
                "action": "auto",
                "timestamp": int(time.time() * 1000),
                "msgid": str(uuid.uuid4()),
                "data": {fan_key: int(fan_val)},
            })
            return

        # fan_speed_pct (and multi-key): merge requested keys into current printer state.
        fan_payload: dict[str, Any] = {
            "fan_speed_pct": int(getattr(printer, "fan_speed_pct", 0) or 0),
            "aux_fan_speed_pct": int(getattr(printer, "aux_fan_speed_pct", 0) or 0),
            "box_fan_level": int(getattr(printer, "box_fan_level", 0) or 0),
            "taskid": taskid,
        }
        for key, value in fan_data.items():
            if key in fan_payload:
                fan_payload[key] = int(value)

        for action in ("setSpeed", "auto"):
            _publish("fan", {
                "type": "fan",
                "action": action,
                "timestamp": int(time.time() * 1000),
                "msgid": str(uuid.uuid4()),
                "data": fan_payload,
            })

    async def _send_cloud_print_settings_command(
        self,
        settings: dict[str, int],
        query_topics: tuple[str, ...] = (),
    ) -> None:
        """Send print setting updates over MQTT so idle printers still accept them."""
        if not self._selected_printer or self._api is None or not self._api.mqtt_is_started:
            return

        printer = self._selected_printer
        project_id = getattr(getattr(printer, "latest_project", None), "id", None)
        taskid = str(project_id) if project_id is not None else "-1"

        payload = {
            "type": "print",
            "action": "update",
            "timestamp": int(time.time() * 1000),
            "msgid": str(uuid.uuid4()),
            "data": {
                "taskid": taskid,
                "settings": {key: int(value) for key, value in settings.items()},
            },
        }

        self._api._mqtt_publish_to_printer(printer, "print", payload)
        self._api._mqtt_publish_to_printer_slicer(printer, "print", payload)

        for topic in query_topics:
            query_payload = {
                "type": topic,
                "action": "query",
                "timestamp": int(time.time() * 1000),
                "msgid": str(uuid.uuid4()),
                "data": None,
            }
            self._api._mqtt_publish_to_printer(printer, topic, query_payload)
            self._api._mqtt_publish_to_printer_slicer(printer, topic, query_payload)

    async def _send_cloud_temperature_command(self, key: str, value: int) -> None:
        """Send temperature target changes with an off-compatible fallback path."""
        if key not in {"target_nozzle_temp", "target_hotbed_temp"}:
            return

        requested = int(value)
        if requested != 0:
            if not self._selected_printer:
                return

            self._forced_temperature_off.discard(key)
            self._forced_temperature_off_last_publish.pop(key, None)

            printer = self._selected_printer
            current_nozzle = int(getattr(printer, "latest_project_target_nozzle_temp", 0) or 0)
            current_hotbed = int(getattr(printer, "latest_project_target_hotbed_temp", 0) or 0)

            # Keep explicit off-lock values pinned while adjusting the other heater.
            if "target_nozzle_temp" in self._forced_temperature_off:
                current_nozzle = 0
            if "target_hotbed_temp" in self._forced_temperature_off:
                current_hotbed = 0

            payload_data = {
                "target_nozzle_temp": current_nozzle,
                "target_hotbed_temp": current_hotbed,
            }
            payload_data[key] = requested

            # Non-zero targets are more stable through tempature/set than
            # print/update (which can emit transient stepped values).
            self._publish_cloud_mqtt_command(
                "tempature",
                "set",
                payload_data,
                publish_to_slicer=True,
            )
            return

        # Heater off: do not send print/update because some firmware clamps
        # this path back to its minimum (e.g. 185 for nozzle).
        if not self._selected_printer:
            return

        self._forced_temperature_off.add(key)
        self._forced_temperature_off_last_publish.pop(key, None)

        self._publish_cloud_mqtt_command(
            "tempature",
            "set",
            {key: 0},
            publish_to_slicer=True,
        )

    async def async_query_topic(self, topic: str, action: str = "query") -> None:
        if not self._selected_printer:
            return
        if topic == "video" and action in ("startCapture", "query"):
            await self.async_open_camera_stream()
            return
        if topic == "video" and action == "stopCapture":
            self._publish_cloud_mqtt_command("video", "stopCapture")
            self._emit_normalized_snapshot()
            return

        if self._api is not None and action == "query":
            query_topics = ("fan", "light", "tempature") if topic == "initial" else (topic,)
            for query_topic in query_topics:
                if query_topic not in {"fan", "light", "tempature", "print", "info"}:
                    continue
                payload = {
                    "type": query_topic,
                    "action": "query",
                    "timestamp": int(time.time() * 1000),
                    "msgid": str(uuid.uuid4()),
                    "data": None,
                }
                try:
                    self._api._mqtt_publish_to_printer(self._selected_printer, query_topic, payload)
                    if query_topic in {"fan", "light", "tempature"}:
                        self._api._mqtt_publish_to_printer_slicer(self._selected_printer, query_topic, payload)
                except Exception as err:
                    _LOGGER.debug("Cloud MQTT query publish failed for %s: %s", query_topic, err)

        try:
            await self._selected_printer.update_info_from_api(with_project=True)
        except Exception as err:
            _LOGGER.debug("Cloud query refresh failed: %s", err)
        self._emit_normalized_snapshot()

    async def async_open_camera_stream(self) -> str | None:
        """Request cloud camera start (MQTT) and return an HTTP-FLV URL when possible."""
        if not self._selected_printer or self._api is None:
            return None

        # Slicer controls camera via MQTT startCapture/stopCapture, so prefer
        # that path over cloud API open-order responses.
        self._camera_stream_blocked_reason = None
        self._publish_cloud_mqtt_command("video", "startCapture")

        try:
            # Keep project context intact; commands like light/fan rely on it.
            await self._selected_printer.update_info_from_api(with_project=True)
        except Exception as err:
            _LOGGER.debug("Cloud camera open refresh failed: %s", err)

        printer_ip = (
            getattr(self._selected_printer, "ip", None)
            or getattr(self._selected_printer, "ip_address", None)
            or getattr(self._selected_printer, "local_ip", None)
        )
        if not printer_ip:
            if not self._camera_stream_blocked_reason:
                self._camera_stream_blocked_reason = "No local stream IP available from cloud"
            return None
        if not self._camera_stream_blocked_reason:
            self._camera_stream_blocked_reason = None
        return f"http://{printer_ip}:18088/flv"

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
            auth_config.get("device_id"),
            auth_config.get("auth_mode"),
        )

    def _update_entry_data(self, updates: dict[str, Any]) -> None:
        new_data = {**self._entry.data, **updates}
        self._hass.config_entries.async_update_entry(self._entry, data=new_data)
