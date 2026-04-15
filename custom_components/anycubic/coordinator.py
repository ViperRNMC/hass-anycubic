"""Unified coordinator for Anycubic integration (LAN + Cloud)."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    DEVICE_TYPE_ACE_PRO,
    DOMAIN,
    EXT_FILBOX_KEY,
    MULTI_COLOR_BOX_KEY,
)
from .transports.base import AnycubicTransport

_LOGGER = logging.getLogger(__name__)


class AnycubicCoordinator(DataUpdateCoordinator):
    """Unified coordinator for both LAN and Cloud modes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, transport: AnycubicTransport) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self.config_entry = entry
        self._transport = transport
        self._boxes_logged = False
        self.mode: str = entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_LAN)
        self.data: dict[str, Any] = {}
        self._last_state_signature: str | None = None
        self._pending_update_count = 0
        self._pending_changed_keys: set[str] = set()
        self._last_update_log_ts = 0.0

    async def async_send_command(self, msg_type: str, action: str, data: Any = None) -> None:
        await self._transport.async_send_command(msg_type, action, data)

    async def async_query_topic(self, topic: str, action: str = "query") -> bool:
        try:
            await self._transport.async_query_topic(topic, action)
            return True
        except Exception as err:
            _LOGGER.debug("query_topic failed (%s): %s", topic, err)
            return False

    async def async_open_camera_stream(self) -> str | None:
        """Ask the active transport to start camera streaming and return a URL."""
        try:
            return await self._transport.async_open_camera_stream()
        except Exception as err:
            _LOGGER.debug("open_camera_stream failed: %s", err)
            return None

    def get_boxes(self) -> list[dict]:
        return self.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get("multi_color_box", [])

    async def async_get_boxes(self) -> list[dict]:
        try:
            await self.async_query_topic(MULTI_COLOR_BOX_KEY, action="getInfo")
        except Exception:
            pass
        return self.get_boxes()

    def expand_definitions(self, definitions: list[dict]) -> list[dict]:
        """Expand per-box / per-slot templates into concrete definitions."""
        boxes = self.get_boxes() or []
        expanded: list[dict] = []
        for d in definitions:
            if not d.get("per_box"):
                expanded.append(d)
                continue

            for box in boxes:
                box_id = box.get("id")
                if box_id is None:
                    continue
                base = {
                    k: v.replace("{box_id}", str(box_id)) if isinstance(v, str) else v
                    for k, v in d.items()
                }
                base["box_id"] = box_id
                base["device_index"] = box_id
                base.pop("per_box", None)

                if d.get("per_slot"):
                    slot_indexes: list[int] = []
                    for s in (box.get("slots") or []):
                        si = s.get("index")
                        if si is None:
                            continue
                        slot_indexes.append(int(si))
                    if not slot_indexes and d.get("device_type") == DEVICE_TYPE_ACE_PRO:
                        # ACE Pro has 4 logical slots; expose them even when cloud omits slot details.
                        slot_indexes = [1, 2, 3, 4]
                    for si in slot_indexes:
                        slot_def = {
                            k: v.replace("{slot_index}", str(si)) if isinstance(v, str) else v
                            for k, v in base.items()
                        }
                        slot_def["slot_index"] = si
                        slot_def.pop("per_slot", None)
                        expanded.append(slot_def)
                else:
                    expanded.append(base)
        return expanded

    def on_transport_data(self, data: Any) -> None:
        """Receive data from transport and notify all entities."""
        touched_keys = self._extract_touched_keys(data)
        self._merge_data(data)
        signature = self._state_signature(self.data)
        if signature == self._last_state_signature:
            return
        self._last_state_signature = signature

        self._pending_update_count += 1
        self._pending_changed_keys.update(touched_keys)

        now = time.monotonic()
        if now - self._last_update_log_ts >= 5:
            self._last_update_log_ts = now
            snapshot = self._debug_snapshot()
            _LOGGER.debug(
                "Applied %d transport updates; changed_keys=%s snapshot=%s",
                self._pending_update_count,
                sorted(self._pending_changed_keys),
                snapshot,
            )
            self._pending_update_count = 0
            self._pending_changed_keys.clear()

        self._dispatch_boxes()
        try:
            self.async_set_updated_data(self.data)
        except Exception:
            _LOGGER.exception("Failed to notify listeners after data update")

    @callback
    def async_set_updated_data(self, data: dict[str, Any]) -> None:
        """Manually update data without emitting noisy base-class debug logs."""
        self._async_unsub_refresh()
        self._debounced_refresh.async_cancel()

        self.data = data
        self.last_update_success = True

        if self._listeners:
            self._schedule_refresh()

        self.async_update_listeners()

    async def _async_update_data(self) -> dict[str, Any]:
        if hasattr(self._transport, "async_refresh_credentials"):
            try:
                await self._transport.async_refresh_credentials()
            except Exception as err:
                _LOGGER.debug("Transport credential refresh error: %s", err)
        return self.data or {}

    async def async_shutdown(self) -> None:
        await self._transport.async_teardown()

    @property
    def mqtt(self) -> Any:
        """Compatibility accessor used by existing platform modules."""
        return getattr(self._transport, "mqtt", None)

    def _merge_data(self, data: Any) -> None:
        if not hasattr(self, "data") or self.data is None:
            self.data = {}

        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and "type" in msg:
                    msg_type = msg["type"]
                    self.data[msg_type] = self._merge_special(self.data.get(msg_type), msg, msg_type)
                elif isinstance(msg, dict):
                    for key, value in msg.items():
                        self.data[key] = self._merge_special(self.data.get(key), value, key)
            return

        if isinstance(data, dict) and "type" in data:
            msg_type = data["type"]
            self.data[msg_type] = self._merge_special(self.data.get(msg_type), data, msg_type)
            return

        if isinstance(data, dict):
            for key, value in data.items():
                self.data[key] = self._merge_special(self.data.get(key), value, key)
            return

        _LOGGER.warning("Unsupported incoming data type: %s", type(data))

    def _merge_special(self, existing: dict | None, incoming: dict, key: str) -> dict:
        """Preserve last-known ACE slot data when incoming update has empty slots."""
        if key not in (MULTI_COLOR_BOX_KEY, EXT_FILBOX_KEY):
            return incoming
        try:
            data_section = (incoming or {}).get("data") or {}
            if key == MULTI_COLOR_BOX_KEY:
                boxes = data_section.get("multi_color_box")
                if boxes is None:
                    return incoming
                existing_map = {
                    b.get("id"): b
                    for b in ((existing or {}).get("data", {}).get("multi_color_box") or [])
                    if isinstance(b, dict)
                }
                for box in boxes:
                    if not isinstance(box, dict):
                        continue
                    if not box.get("slots"):
                        prev = existing_map.get(box.get("id"))
                        if prev and prev.get("slots"):
                            box["_slots_last_known"] = prev["slots"]
                        box["slots"] = None
        except Exception:
            pass
        return incoming

    def _dispatch_boxes(self) -> None:
        try:
            boxes = self.get_boxes()
            if boxes and not self._boxes_logged:
                _LOGGER.info("Detected multiColorBox entries: %s", [b.get("id") for b in boxes])
                self._boxes_logged = True
            async_dispatcher_send(self.hass, f"{DOMAIN}_boxes_updated", boxes)
        except Exception:
            pass

    @staticmethod
    def _state_signature(value: Any) -> str:
        """Create a stable signature to detect unchanged incoming states."""
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            return repr(value)

    @staticmethod
    def _extract_touched_keys(data: Any) -> set[str]:
        """Return top-level keys affected by an incoming payload."""
        keys: set[str] = set()
        if isinstance(data, dict) and "type" in data and isinstance(data["type"], str):
            keys.add(data["type"])
            return keys
        if isinstance(data, dict):
            keys.update(str(k) for k in data.keys())
            return keys
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "type" in item and isinstance(item["type"], str):
                    keys.add(item["type"])
                elif isinstance(item, dict):
                    keys.update(str(k) for k in item.keys())
        return keys

    def _debug_snapshot(self) -> dict[str, Any]:
        """Compact runtime snapshot for throttled debug logging."""
        info = (self.data.get("info") or {}).get("data") or {}
        pr = (self.data.get("print") or {}).get("data") or {}
        temp = (self.data.get("tempature") or {}).get("data") or {}
        return {
            "state": info.get("state"),
            "online": info.get("printer_online"),
            "progress": pr.get("progress"),
            "file": pr.get("filename"),
            "remaining_min": pr.get("remain_time"),
            "nozzle": temp.get("curr_nozzle_temp"),
            "bed": temp.get("curr_hotbed_temp"),
        }


async def async_create_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> AnycubicCoordinator:
    """Create and initialize coordinator with LAN or Cloud transport."""
    mode = entry.data.get(CONF_CONNECTION_MODE, CONNECTION_MODE_LAN)

    if mode == CONNECTION_MODE_CLOUD:
        from .transports.cloud.transport import CloudTransport

        transport = CloudTransport(hass, entry)
    else:
        from .transports.lan.transport import LanTransport

        transport = LanTransport(hass, entry.data["host"])

    coordinator = AnycubicCoordinator(hass, entry, transport)
    await transport.async_setup(coordinator.on_transport_data)
    await coordinator.async_config_entry_first_refresh()
    return coordinator


# Backward-compatible class name used in some platform modules.
AnycubicDataUpdateCoordinator = AnycubicCoordinator
