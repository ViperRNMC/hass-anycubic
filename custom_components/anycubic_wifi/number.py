"""Anycubic number platform for Home Assistant.

This module exposes two kinds of numbers:
- Static numbers defined in NUMBER_DEFINITIONS (nozzle/hotbed targets).
- Dynamic per-AcePro-box numbers created at setup: drying target temp and drying duration.
"""

import logging
from typing import Optional

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL,
    NUMBER_DEFINITIONS,
    MULTI_COLOR_BOX_KEY,
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up number entities for Anycubic printers.

    Creates static numbers from NUMBER_DEFINITIONS and per-box drying numbers.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    # Force-fetch multiColorBox initial state so per-box numbers have values
    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("Coordinator async_get_boxes failed; falling back to cached boxes")

    # Expand any per-box template definitions using coordinator knowledge
    expanded_defs = coordinator.expand_definitions(NUMBER_DEFINITIONS)
    entities = [AnycubicNumber(coordinator, d) for d in expanded_defs]
    if entities:
        async_add_entities(entities)

    # If no boxes were available, wait for boxes_updated and create per-box numbers
    if not boxes:
        def _on_boxes_updated(boxes_list):
            expanded = coordinator.expand_definitions(NUMBER_DEFINITIONS)
            new_entities: list[NumberEntity] = []
            for d in expanded:
                # only create per-box entries (they will include box_id)
                if d.get("box_id") is not None:
                    new_entities.append(AnycubicNumber(coordinator, d))
            if not new_entities:
                return

            # async_add_entities must run on the event loop; schedule it safely
            def _add_and_unsub():
                try:
                    async_add_entities(new_entities)
                except Exception:
                    _LOGGER.exception("Failed to add per-box number entities")
                try:
                    unsub()
                except Exception:
                    pass

            coordinator.hass.loop.call_soon_threadsafe(_add_and_unsub)

        unsub = async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)


class AnycubicNumber(CoordinatorEntity, NumberEntity):
    """Generic number entity for target temperatures and per-box drying values."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_has_entity_name = True
        self._attr_icon = definition.get("icon", "mdi:thermometer")
        self._attr_native_min_value = definition.get("min")
        self._attr_native_max_value = definition.get("max")
        self._attr_native_step = 1
        # Allow unit override in dynamic defs
        self._attr_native_unit_of_measurement = definition.get("unit", "°C")
        self._box_id: Optional[int] = definition.get("box_id")
        self._kind: Optional[str] = definition.get("kind")

    @property
    def native_value(self):
        # Box-specific numbers read from multiColorBox drying_status
        if self._kind and self._box_id is not None:
            boxes = self.coordinator.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get("multi_color_box", [])
            for b in boxes:
                if b.get("id") == self._box_id:
                    ds = b.get("drying_status", {})
                    if self._kind == "drying_target":
                        return ds.get("target_temp")
                    if self._kind == "drying_duration":
                        return ds.get("duration")

        # Fallback: existing behavior for static number definitions (nozzle/hotbed)
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        key = self.definition.get("data_key")
        if key and temp_report.get(key) is not None:
            return temp_report.get(key)
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get(key) if key else None

    async def async_set_native_value(self, value):
        try:
            if self._kind and self._box_id is not None:
                # For drying target/duration, publish a setDry payload including both fields
                boxes = self.coordinator.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get("multi_color_box", [])
                current_target = None
                current_duration = None
                current_status = 1
                for b in boxes:
                    if b.get("id") == self._box_id:
                        ds = b.get("drying_status", {})
                        current_target = ds.get("target_temp")
                        current_duration = ds.get("duration")
                        current_status = ds.get("status", 1)
                        break

                if self._kind == "drying_target":
                    target_val = int(value)
                    duration_val = int(current_duration) if current_duration is not None else 240
                else:
                    duration_val = int(value)
                    target_val = int(current_target) if current_target is not None else 45

                payload = {
                    "type": "multiColorBox",
                    "action": "setDry",
                    "data": {
                        "multi_color_box": [
                            {
                                "id": self._box_id,
                                "drying_status": {
                                    "status": current_status,
                                    "target_temp": target_val,
                                    "duration": duration_val,
                                },
                            }
                        ]
                    },
                }
                mqtt = self.coordinator.mqtt
                topic = mqtt.web_topic("multiColorBox")
                mqtt.publish_json(topic, payload)

                # optimistic update
                self._attr_native_value = int(value)
                self.async_write_ha_state()
                return

            # Static numbers: publish via print update as before
            settings = {self.definition.get("data_key"): int(value)}
            payload = {
                "type": "print",
                "action": "update",
                "data": {"taskid": "-1", "settings": settings},
            }
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic("print")
            mqtt.publish_json(topic, payload)

            # optimistic update
            self._attr_native_value = int(value)
            self.async_write_ha_state()

        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish number set %s: %s", self._key, err)

    @property
    def device_info(self) -> dict:
        if self._box_id is not None:
            entry_id = getattr(self.coordinator.config_entry, "entry_id", "unknown")
            return {"identifiers": {(DOMAIN, f"{entry_id}_ace_pro_box_{self._box_id}")}}
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }
