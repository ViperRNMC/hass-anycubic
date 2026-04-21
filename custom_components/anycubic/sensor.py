"""Anycubic sensor platform for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any, Optional
import math

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    SENSOR_DEFINITIONS,
    MULTI_COLOR_BOX_KEY,
    DEVICE_TYPE_ACE_PRO,
    DEVICE_TYPE_EXTFILBOX,
    FILAMENT_DIAMETER_MM,
    FILAMENT_DENSITY_G_CM3,
)
from .helper.device_info import (
    build_ace_device_info,
    build_extfilbox_device_info,
    build_main_device_info,
)
from .helper.color import nearest_color_name
from .helper.time import minutes_to_hhmm
from .helper.path import get_from_path

try:
    import webcolors  # type: ignore
    _HAS_WEBCOLORS = True
except Exception:
    _HAS_WEBCOLORS = False


_LOGGER = logging.getLogger(__name__)


def _compute_supplies_from_raw(raw: Optional[int]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Compute grams, factor and method from raw supplies usage value.

    Returns (grams, factor, method). Uses FILAMENT_DIAMETER_MM constant to
    compute grams-per-mm from geometry + internal density; falls back to
    the geometry-based estimate.
    """
    if raw is None:
        return None, None, None
    # Compute using filament cross-section area * length * density
    d = float(FILAMENT_DIAMETER_MM)
    radius = d / 2.0
    area_mm2 = math.pi * (radius ** 2)
    grams_per_mm = (area_mm2 / 1000.0) * FILAMENT_DENSITY_G_CM3
    factor = grams_per_mm
    method = "constant_diameter"
    grams = raw * factor
    return grams, factor, method





async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors from SENSOR_DEFINITIONS."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found in hass.data", entry.entry_id)
        return

    # Force-fetch multiColorBox and extfilbox so per-box sensors have initial values
    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("Coordinator async_get_boxes failed; falling back to cached boxes")
    _LOGGER.debug("sensor setup: found %d boxes at setup", len(boxes) if boxes is not None else 0)
    try:
        await coordinator.async_query_topic(DEVICE_TYPE_EXTFILBOX)
    except Exception:
        _LOGGER.debug("Coordinator query for extfilbox failed or MQTT not ready")

    # Expand per-box sensor templates and create entities
    expanded_defs = coordinator.expand_definitions(SENSOR_DEFINITIONS)
    entities: list[SensorEntity] = []
    for d in expanded_defs:
        try:
            entities.append(AnycubicSensorEntity(coordinator, d))
        except Exception:  # defensive: skip bad definitions
            _LOGGER.exception("Failed to create sensor from definition %s", d)

    # Register the entities created from SENSOR_DEFINITIONS
    if entities:
        _LOGGER.debug("sensor setup: creating %d sensor entities (expanded_defs total=%d)", len(entities), len(expanded_defs))
        _LOGGER.debug("sensor setup: sensor keys: %s", [e.definition.get('key') for e in entities])
        async_add_entities(entities)

    # If no boxes were available at setup, wait for boxes_updated and create per-box sensors
    if not boxes:
        def _on_boxes_updated(boxes_list):
            _LOGGER.debug("sensor listener: boxes_updated fired with %d boxes", len(boxes_list) if boxes_list else 0)
            expanded = coordinator.expand_definitions(SENSOR_DEFINITIONS)
            _LOGGER.debug("sensor listener: expanded_defs count=%d", len(expanded))
            new_entities: list[SensorEntity] = []
            for d in expanded:
                if d.get("box_id") is not None:
                    try:
                        new_entities.append(AnycubicSensorEntity(coordinator, d))
                    except Exception:
                        _LOGGER.exception("Failed to create per-box sensor from definition %s", d)
            if not new_entities:
                _LOGGER.debug("sensor listener: no new per-box sensors to add")
                return

            def _add_and_unsub():
                try:
                    _LOGGER.debug("sensor listener: adding %d per-box sensor entities", len(new_entities))
                    async_add_entities(new_entities)
                except Exception:
                    _LOGGER.exception("Failed to add per-box sensor entities")
                try:
                    unsub()
                except Exception:
                    pass

            coordinator.hass.loop.call_soon_threadsafe(_add_and_unsub)

        unsub = async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)

class AnycubicSensorEntity(CoordinatorEntity, SensorEntity):
    """Generic sensor backed by coordinator data.

    Definition keys supported:
    - name, key, data_path (tuple/list of keys), unit, icon, entity_category,
      formatter (callable name string supported in this module).
    """

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._data_key = definition.get("data_key")
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = definition.get("unit")
        # Use icon from definition when provided (icons live in `const.py` as mdi strings)
        icon = definition.get("icon")
        if icon:
            self._attr_icon = icon
        self._formatter = definition.get("formatter")
        cat = definition.get("entity_category")
        if cat == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        # convenience helpers custom in definitions
        self._data_field = definition.get("data_field")
        self._slot_index = definition.get("slot_index")

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def _resolve_slot(self, box: dict, desired_index: Any) -> Optional[dict]:
        """Resolve a slot robustly across LAN/cloud payload variants.

        Cloud payloads may omit `index` and use positional ordering, or use
        zero-based indexes. LAN payloads typically expose one-based `index`.
        """
        slots = box.get("slots") or []
        if not isinstance(slots, list) or not slots:
            return None

        desired = self._to_int(desired_index)
        if desired is None:
            return None

        explicit_indexes: list[int] = []
        for s in slots:
            if not isinstance(s, dict):
                continue
            for k in ("index", "slot_index", "ams_index"):
                si = self._to_int(s.get(k))
                if si is not None:
                    explicit_indexes.append(si)
                    break

        zero_based = bool(explicit_indexes) and min(explicit_indexes) == 0
        desired_cmp = desired - 1 if zero_based and desired > 0 else desired

        for pos, s in enumerate(slots, start=1):
            if not isinstance(s, dict):
                continue

            slot_idx = None
            for k in ("index", "slot_index", "ams_index"):
                slot_idx = self._to_int(s.get(k))
                if slot_idx is not None:
                    break

            if slot_idx is None:
                # No explicit index present: use payload order as 1-based slots.
                slot_idx = (pos - 1) if zero_based else pos

            if slot_idx == desired_cmp:
                return s

        return None

    @property
    def native_value(self) -> Any:
        data_path = tuple(self.definition.get("data_path", ()))
        if not data_path:
            return None

        top = data_path[0]
        rest = data_path[1:]
        data = self.coordinator.data.get(top, {})

        # Special handling for multiColorBox: definitions may be per_box templates
        if top == MULTI_COLOR_BOX_KEY:
            box_id = self.definition.get("box_id") or self.definition.get("device_index")
            if box_id is None:
                # fallback to first box
                boxes = data.get("data", {}).get("multi_color_box", [])
                box = boxes[0] if boxes else None
            else:
                box = self._find_box_by_id(data, box_id)

            if box is None:
                return None

            # If this is a slot sensor, return formatted slot info
            if self._slot_index is not None:
                slot = self._resolve_slot(box, self._slot_index)
                if slot is None:
                    self._attr_icon = "mdi:tray"
                    return "Empty"

                # format slot value similar to legacy AceProBoxSlotSensor
                if slot.get("status") == 4:
                    # empty slot
                    self._attr_icon = "mdi:tray"
                    return "Empty"

                # filled slot
                self._attr_icon = "mdi:tray-full"
                slot_type = slot.get("type") or slot.get("material_type") or "Unknown"
                # Prefer explicit color_group if present (more accurate)
                if slot.get("color_group"):
                    color_input = slot.get("color_group")
                else:
                    color_input = tuple(slot.get("color", [0, 0, 0]))
                color_name = nearest_color_name(color_input)
                rgb = tuple(slot.get("color", [0, 0, 0]))
                # store per-slot attributes for UI
                self._slot_attrs = {
                    "index": slot.get("index"),
                    "sku": slot.get("sku"),
                    "type": slot.get("type"),
                    "color_rgb": rgb,
                }
                return f"{slot_type} ({color_name})"

            # If a specific data_field is requested, support tuple path or str
            if self._data_field:
                if isinstance(self._data_field, tuple):
                    val = box
                    for p in self._data_field:
                        val = val.get(p) if isinstance(val, dict) else None
                        if val is None:
                            break
                    value = val
                else:
                    value = box.get(self._data_field)
                # special-case for loaded_slot: expose index and store slot attrs
                if self._data_field == "loaded_slot":
                    loaded = value
                    # default: unknown
                    if loaded is None:
                        self._attr_icon = "mdi:package-variant-closed"
                        self._loaded_slot_attrs = {}
                        return "Empty"
                    # explicit -1 means empty: return canonical numeric -1
                    try:
                        if int(loaded) == -1:
                            self._attr_icon = "mdi:package-variant-closed"
                            self._loaded_slot_attrs = {}
                            return "Empty"
                    except Exception:
                        pass
                    li = int(loaded)
                    # find slot metadata
                    slot = self._resolve_slot(box, li)
                    if slot is None:
                        self._attr_icon = "mdi:package-variant-closed"
                        self._loaded_slot_attrs = {}
                        return li + 1
                    # filled — use a distinct package icon for loaded_slot
                    self._attr_icon = "mdi:package-variant"
                    rgb = tuple(slot.get("color", [0, 0, 0]))
                    color_name = nearest_color_name(rgb)
                    self._loaded_slot_attrs = {
                        "loaded_slot_index": li,
                        "loaded_slot_sku": slot.get("sku"),
                        "loaded_slot_type": slot.get("type") or slot.get("material_type"),
                        "loaded_slot_color_rgb": rgb,
                        "loaded_slot_color_name": color_name,
                    }
                    return li + 1
            else:
                # default: follow rest path inside the box dict
                value = get_from_path(box, rest[2:]) if len(rest) >= 2 else None
        # Special handling for external filament rack (single-slot extfilbox)
        if top == DEVICE_TYPE_EXTFILBOX:
            # top-level stored data may be either the full message dict or
            # already the inner 'data' section depending on MQTT normalization.
            if isinstance(data, dict):
                ext = data.get("data") if data.get("data") is not None else data
            else:
                ext = data or {}

            # Interpret status flags: -1 often indicates 'not present' / empty
            status_type = ext.get("status_type")
            current_status = ext.get("current_status")
            loaded_raw = ext.get("loaded")
            # Parse loaded defensively (may be string or int)
            try:
                loaded = int(loaded_raw) if loaded_raw is not None else None
            except Exception:
                loaded = loaded_raw

            # If both status flags indicate 'not present' treat as empty (canonical -1)
            if status_type == -1 and current_status == -1:
                _LOGGER.debug("extfilbox: status indicates not present (status_type=%s current_status=%s loaded=%s)", status_type, current_status, loaded_raw)
                self._attr_icon = "mdi:package-variant-closed"
                self._loaded_slot_attrs = {}
                return "Empty"

            # If loaded explicitly indicates empty, return canonical -1
            if loaded in (0, -1):
                self._attr_icon = "mdi:package-variant-closed"
                self._loaded_slot_attrs = {}
                return "Empty"

            # If there is no loaded value at all, return Unknown (None)
            if loaded is None:
                return None

            # Otherwise, expose the loaded slot info and attributes
            li = loaded
            rgb = tuple(ext.get("color", [0, 0, 0]))
            color_name = nearest_color_name(rgb)
            self._attr_icon = "mdi:package-variant"
            self._loaded_slot_attrs = {
                "loaded_slot_index": li,
                "loaded_slot_type": ext.get("type"),
                "loaded_slot_color_rgb": rgb,
                "loaded_slot_color_name": color_name,
            }
            return li

        else:
            # Generic path handling for other top-level keys
            value = get_from_path(data, rest)

        # Ensure numeric sensors return numeric primitives (not lists/dicts).
        # If a numeric unit is configured (e.g. °C), try to extract a numeric
        # value from common nested shapes; otherwise return None to avoid
        # Home Assistant raising a ValueError when a numeric sensor yields
        # a non-numeric type (like list/dict).
        unit = self._attr_native_unit_of_measurement
        if unit is not None and isinstance(value, (list, dict)):
            try:
                # Lists: try first element numeric or dict with known numeric keys
                if isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, dict):
                        for k in ("temp", "value", "temperature", "t"):
                            if k in first:
                                value = first.get(k)
                                break
                    else:
                        # list of primitives: take first numeric-like
                        for item in value:
                            if isinstance(item, (int, float)):
                                value = item
                                break
                            if isinstance(item, str):
                                try:
                                    value = float(item)
                                    break
                                except Exception:
                                    continue
                elif isinstance(value, dict):
                    for k in ("temp", "value", "temperature", "t"):
                        if k in value:
                            value = value.get(k)
                            break
            except Exception:
                # Fall through and let the post-check return None
                value = None

            # If extraction didn't produce a primitive numeric value, avoid
            # returning the original list/dict which would cause HA to error.
            if isinstance(value, (list, dict)):
                return None

        # Convert print supplies_usage to grams
        if top == "print" and rest and rest[-1] == "supplies_usage":
            try:
                raw = int(value) if value is not None else None
                grams, factor, method = _compute_supplies_from_raw(raw)
                self._last_supplies_raw, self._last_supplies_factor, self._last_supplies_method = raw, factor, method
                return round(grams, 2) if grams is not None else None
            except Exception:
                return value
            
        # Apply formatter if any
        if self._formatter:
            if self._formatter == "minutes_to_hhmm":
                return minutes_to_hhmm(value)
        return value

    @property
    def extra_state_attributes(self):
        attrs = {}
        # expose supplies usage converted value if available
        if hasattr(self, "_last_supplies_raw"):
            attrs["supplies_usage_raw"] = getattr(self, "_last_supplies_raw")
            # expose which method was used to compute grams
            attrs["supplies_usage_method"] = getattr(self, "_last_supplies_method", None)
        # expose loaded slot attributes (for both Ace Pro boxes and extfilbox)
        if hasattr(self, "_loaded_slot_attrs") and self._loaded_slot_attrs:
            attrs.update(self._loaded_slot_attrs)
        # expose per-slot attributes when available
        if hasattr(self, "_slot_attrs") and self._slot_attrs:
            attrs.update(self._slot_attrs)
        # Inform in logs when webcolors isn't available (user may expect CSS3 names)
        if not _HAS_WEBCOLORS:
            attrs.setdefault("color_naming", "heuristic")
        return attrs

    @property
    def device_info(self) -> dict:
        """Get device info based on sensor definition device type."""
        dt = self.definition.get("device_type")

        if dt == DEVICE_TYPE_ACE_PRO:
            box_id = self.definition.get("device_index", 0)
            return build_ace_device_info(self.coordinator, int(box_id))
        elif dt == DEVICE_TYPE_EXTFILBOX:
            return build_extfilbox_device_info(self.coordinator)
        else:
            return build_main_device_info(self.coordinator)

    def _find_box_by_id(self, top_level_data: dict, box_id: int) -> Optional[dict]:
        """Find a multicolor box by its `id` field inside coordinator data.

        top_level_data is the dict under MULTI_COLOR_BOX_KEY (e.g. coordinator.data[MULTI_COLOR_BOX_KEY]).
        """
        boxes = top_level_data.get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if b.get("id") == box_id:
                return b
        return None
