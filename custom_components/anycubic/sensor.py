"""Anycubic sensor platform for Home Assistant (LAN and Cloud modes)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Sequence
from dataclasses import dataclass
import math

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.const import (
    PERCENTAGE,
    Platform,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL,
    ACE_PRO_DEVICE_BASE,
    EXTFILBOX_DEVICE_BASE,
    MULTI_COLOR_BOX_KEY,
    EXT_FILBOX_KEY,
    DEVICE_TYPE_ACE_PRO,
    DEVICE_TYPE_EXTFILBOX,
    FILAMENT_DIAMETER_MM,
    FILAMENT_DENSITY_G_CM3,
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    COORDINATOR,
    UNIT_LAYERS,
    PrinterEntityType,
)
from .descriptions import get_descriptions
from .helper.color import nearest_color_name
from .helper.time import minutes_to_hhmm
from .helper.path import get_from_path 
from .entity import AnycubicEntity
from .helper.mapper import printer_attributes_for_key, printer_state_for_key

try:
    import webcolors  # type: ignore
    _HAS_WEBCOLORS = True
except Exception:
    _HAS_WEBCOLORS = False


_LOGGER = logging.getLogger(__name__)
LAN_SENSOR_DEFINITIONS = get_descriptions(CONNECTION_MODE_LAN, "sensor")


def _compute_supplies_from_raw(raw: Optional[int]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Compute grams, factor and method from raw supplies usage value."""
    if raw is None:
        return None, None, None
    d = float(FILAMENT_DIAMETER_MM)
    radius = d / 2.0
    area_mm2 = math.pi * (radius ** 2)
    grams_per_mm = (area_mm2 / 1000.0) * FILAMENT_DENSITY_G_CM3
    factor = grams_per_mm
    method = "constant_diameter"
    grams = raw * factor
    return grams, factor, method


# ============================================================================
# Cloud Sensor Definitions
# ============================================================================

@dataclass(frozen=True)
class AnycubicCloudSensorEntityDescription(
    SensorEntityDescription
):
    """Cloud sensor entity description."""
    printer_entity_type: PrinterEntityType | None = None
    not_measured: bool = False


CLOUD_ALL_SENSOR_TYPES: list[AnycubicCloudSensorEntityDescription] = list([
    AnycubicCloudSensorEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "sensor")
])


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors - handles both LAN and Cloud modes."""
    mode = entry.options.get(CONF_CONNECTION_MODE) or entry.data.get(
        CONF_CONNECTION_MODE, CONNECTION_MODE_LAN
    )
    
    if mode == CONNECTION_MODE_CLOUD:
        return await _setup_cloud_sensors(hass, entry, async_add_entities)
    else:
        return await _setup_lan_sensors(hass, entry, async_add_entities)


async def _setup_lan_sensors(hass, entry, async_add_entities):
    """Set up LAN-mode sensors from centralized LAN descriptions."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found in hass.data", entry.entry_id)
        return

    # Force-fetch multiColorBox and extfilbox
    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("Coordinator async_get_boxes failed; falling back to cached boxes")
    
    try:
        await coordinator.async_query_topic(EXT_FILBOX_KEY)
    except Exception:
        _LOGGER.debug("Coordinator query for extfilbox failed or MQTT not ready")

    # Expand per-box sensor templates and create entities
    expanded_defs = coordinator.expand_definitions(LAN_SENSOR_DEFINITIONS)
    entities: list[SensorEntity] = []
    for d in expanded_defs:
        try:
            entities.append(AnycubicLanSensor(coordinator, d))
        except Exception:
            _LOGGER.exception("Failed to create LAN sensor from definition %s", d)

    # Add raw MQTT debug sensor
    try:
        entities.append(AnycubicRawMQTTSensor(coordinator))
    except Exception:
        _LOGGER.exception("Failed to create raw MQTT debug sensor")

    if entities:
        async_add_entities(entities)

    # Wait for boxes_updated if no initial boxes
    if not boxes:
        added_once = False
        
        def _on_boxes_updated(boxes_list):
            nonlocal added_once
            if added_once:
                _LOGGER.debug("sensor listener: already added per-box sensors, skipping")
                return
                
            expanded = coordinator.expand_definitions(LAN_SENSOR_DEFINITIONS)
            new_entities: list[SensorEntity] = []
            for d in expanded:
                if d.get("box_id") is not None:
                    try:
                        new_entities.append(AnycubicLanSensor(coordinator, d))
                    except Exception:
                        _LOGGER.exception("Failed to create per-box LAN sensor from definition %s", d)
            
            if not new_entities:
                _LOGGER.debug("sensor listener: no per-box sensors to add")
                return

            def schedule_add_entities():
                try:
                    async_add_entities(new_entities)
                except Exception:
                    _LOGGER.exception("Failed to add per-box sensor entities")
            
            coordinator.hass.loop.call_soon_threadsafe(schedule_add_entities)
            added_once = True

        unsub = async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)


async def _setup_cloud_sensors(hass, entry, async_add_entities):
    """Set up Cloud-mode sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    
    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudSensor,
        platform=Platform.SENSOR,
        available_descriptors=CLOUD_ALL_SENSOR_TYPES,
    )


# ============================================================================
# LAN Mode Sensor Class
# ============================================================================

class AnycubicLanSensor(CoordinatorEntity, SensorEntity):
    """Generic sensor backed by LAN coordinator data (MQTT)."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._data_key = definition.get("data_key")
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = definition.get("unit")
        icon = definition.get("icon")
        if icon:
            self._attr_icon = icon
        self._formatter = definition.get("formatter")
        cat = definition.get("entity_category")
        if cat == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._data_field = definition.get("data_field")
        self._slot_index = definition.get("slot_index")

    @property
    def native_value(self) -> Any:
        data_path = tuple(self.definition.get("data_path", ()))
        if not data_path:
            return None

        top = data_path[0]
        rest = data_path[1:]
        data = self.coordinator.data.get(top, {})

        # Special handling for multiColorBox
        if top == MULTI_COLOR_BOX_KEY:
            box_id = self.definition.get("box_id") or self.definition.get("device_index")
            if box_id is None:
                boxes = data.get("data", {}).get("multi_color_box", [])
                box = boxes[0] if boxes else None
            else:
                box = self._find_box_by_id(data, box_id)

            if box is None:
                return None

            # Slot sensor handling
            if self._slot_index is not None:
                slot = None
                for s in box.get("slots", []):
                    if s.get("index") == self._slot_index:
                        slot = s
                        break
                if slot is None:
                    return None

                if slot.get("status") == 4:
                    self._attr_icon = "mdi:tray"
                    return "Empty"

                self._attr_icon = "mdi:tray-full"
                slot_type = slot.get("type", "Unknown")
                color_input = slot.get("color_group") or tuple(slot.get("color", [0, 0, 0]))
                color_name = nearest_color_name(color_input)
                rgb = tuple(slot.get("color", [0, 0, 0]))
                self._slot_attrs = {
                    "index": slot.get("index"),
                    "sku": slot.get("sku"),
                    "type": slot.get("type"),
                    "color_rgb": rgb,
                }
                return f"{slot_type} ({color_name})"

            # Data field handling
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
                
                if isinstance(value, (dict, list)) and self._data_field not in ("slots", "multi_color_box"):
                    _LOGGER.debug("Sensor %s requested field '%s' but got %s", self._key, self._data_field, type(value).__name__)
                    return None
                
                if self._data_field == "loaded_slot":
                    loaded = value
                    if loaded is None:
                        return None
                    try:
                        if int(loaded) == -1:
                            self._attr_icon = "mdi:package-variant-closed"
                            self._loaded_slot_attrs = {}
                            return "Empty"
                    except Exception:
                        pass
                    li = int(loaded)
                    slot = None
                    for s in box.get("slots", []):
                        if s.get("index") == li:
                            slot = s
                            break
                    if slot is None:
                        self._attr_icon = "mdi:package-variant-closed"
                        self._loaded_slot_attrs = {}
                        return li
                    self._attr_icon = "mdi:package-variant"
                    rgb = tuple(slot.get("color", [0, 0, 0]))
                    color_name = nearest_color_name(rgb)
                    self._loaded_slot_attrs = {
                        "loaded_slot_index": li,
                        "loaded_slot_sku": slot.get("sku"),
                        "loaded_slot_type": slot.get("type"),
                        "loaded_slot_color_rgb": rgb,
                        "loaded_slot_color_name": color_name,
                    }
                    return li
            else:
                value = get_from_path(box, rest[2:]) if len(rest) >= 2 else None
        
        # Special handling for external filament rack
        elif top == EXT_FILBOX_KEY:
            if isinstance(data, dict):
                ext = data.get("data") if data.get("data") is not None else data
            else:
                ext = data or {}

            status_type = ext.get("status_type")
            current_status = ext.get("current_status")
            loaded_raw = ext.get("loaded")
            try:
                loaded = int(loaded_raw) if loaded_raw is not None else None
            except Exception:
                loaded = loaded_raw

            if status_type == -1 and current_status == -1:
                self._attr_icon = "mdi:package-variant-closed"
                self._loaded_slot_attrs = {}
                return "Empty"

            if loaded in (0, -1):
                self._attr_icon = "mdi:package-variant-closed"
                self._loaded_slot_attrs = {}
                return "Empty"

            if loaded is None:
                return None

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
            value = get_from_path(data, rest)

        # Handle numeric sensors with list/dict values
        unit = self._attr_native_unit_of_measurement
        if unit is not None and isinstance(value, (list, dict)):
            try:
                if isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, dict):
                        for k in ("temp", "value", "temperature", "t"):
                            if k in first:
                                value = first.get(k)
                                break
                    else:
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
                value = None

            if isinstance(value, (list, dict)):
                return None

        # Convert supplies_usage to grams
        if top == "print" and rest and rest[-1] == "supplies_usage":
            try:
                raw = int(value) if value is not None else None
                grams, factor, method = _compute_supplies_from_raw(raw)
                self._last_supplies_raw, self._last_supplies_factor, self._last_supplies_method = raw, factor, method
                return round(grams, 2) if grams is not None else None
            except Exception:
                return value

        if self._formatter:
            if self._formatter == "minutes_to_hhmm":
                return minutes_to_hhmm(value)
        return value

    @property
    def extra_state_attributes(self):
        attrs = {}
        if hasattr(self, "_last_supplies_raw"):
            attrs["supplies_usage_raw"] = getattr(self, "_last_supplies_raw")
            attrs["supplies_usage_method"] = getattr(self, "_last_supplies_method", None)
        if hasattr(self, "_loaded_slot_attrs") and self._loaded_slot_attrs:
            attrs.update(self._loaded_slot_attrs)
        if hasattr(self, "_slot_attrs") and self._slot_attrs:
            attrs.update(self._slot_attrs)
        if not _HAS_WEBCOLORS:
            attrs.setdefault("color_naming", "heuristic")
        return attrs

    @property
    def device_info(self) -> dict:
        """Get device info based on sensor definition device type."""
        dt = self.definition.get("device_type")
        entry_id = getattr(self.coordinator.config_entry, "entry_id", "unknown")
        
        if dt == DEVICE_TYPE_ACE_PRO:
            box_id = self.definition.get("device_index", 0)
            return {"identifiers": {(DOMAIN, f"{entry_id}_ace_pro_box_{box_id}")}, **ACE_PRO_DEVICE_BASE}
        elif dt == DEVICE_TYPE_EXTFILBOX:
            return {"identifiers": {(DOMAIN, f"{entry_id}_extfilbox")}, **EXTFILBOX_DEVICE_BASE}
        else:
            return {
                "identifiers": {(DOMAIN, entry_id)},
                "name": self.coordinator.config_entry.title,
                "manufacturer": MANUFACTURER,
                "model": MODEL,
                "entry_type": "service",
            }

    def _find_box_by_id(self, top_level_data: dict, box_id: int) -> Optional[dict]:
        """Find a multicolor box by its `id` field inside coordinator data."""
        boxes = top_level_data.get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if b.get("id") == box_id:
                return b
        return None


class AnycubicRawMQTTSensor(CoordinatorEntity, SensorEntity):
    """Debug sensor that exposes the raw MQTT state as JSON."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic MQTT raw payload"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_mqtt_raw_payload"
        self._attr_icon = "mdi:code-json"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        raw = self.coordinator.data.get("raw_data")
        if raw is None:
            return "unavailable"
        try:
            count = len(raw) if isinstance(raw, dict) else 0
            return f"{count} topics"
        except Exception:
            return "error"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {"last_update": self.coordinator.last_update_success}
        data = self.coordinator.data.get("raw_data")
        if data is not None:
            attrs["topic_count"] = len(data) if isinstance(data, dict) else None
        return attrs


# ============================================================================
# Cloud Mode Sensor Class
# ============================================================================

class AnycubicCloudSensor(AnycubicEntity, SensorEntity):
    """Representation of a Anycubic Cloud sensor."""

    entity_description: AnycubicCloudSensorEntityDescription

    def __init__(
        self,
        hass,
        coordinator,
        printer_id: int,
        entity_description: AnycubicCloudSensorEntityDescription,
    ) -> None:
        """Initiate Anycubic Cloud Sensor."""
        super().__init__(hass, coordinator, printer_id, entity_description)

        if entity_description.native_unit_of_measurement == UnitOfTemperature.CELSIUS:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        else:
            self._attr_native_unit_of_measurement = entity_description.native_unit_of_measurement

        if entity_description.not_measured:
            self._attr_state_class = None
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        
        self._attr_device_class = entity_description.device_class
        self._attr_icon = entity_description.icon

    @property
    def available(self) -> bool:
        return printer_state_for_key(
            self.coordinator,
            self._printer_id,
            self.entity_description.key
        ) is not None

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        state = printer_state_for_key(self.coordinator, self._printer_id, self.entity_description.key)

        if state is None:
            return None

        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            return dt_util.utc_from_timestamp(state)

        elif (
            isinstance(state, float)
            or self.entity_description.native_unit_of_measurement == UnitOfTemperature.CELSIUS
        ):
            return float(state)

        elif (
            isinstance(state, int)
            or self.entity_description.native_unit_of_measurement == UNIT_LAYERS
            or self.entity_description.native_unit_of_measurement == PERCENTAGE
        ):
            return int(state)

        return str(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attrib = printer_attributes_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        return attrib if attrib is not None else None
