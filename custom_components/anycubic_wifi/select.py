"""Select platform for Anycubic print settings (speed mode)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SELECT_DEFINITIONS, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    # Request current print settings so the select has an initial value
    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Coordinator query for print failed or MQTT not ready")

    entities: list[SelectEntity] = []
    for d in SELECT_DEFINITIONS:
        entities.append(AnycubicSelect(coordinator, d))

    async_add_entities(entities)


class AnycubicSelect(CoordinatorEntity, SelectEntity):
    """Generic Select backed by SELECT_DEFINITIONS."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_options = definition.get("options", [])
        self._value_map = definition.get("value_map", {})
        self._attr_has_entity_name = True

    @property
    def current_option(self) -> str | None:
        # map coordinator.info or settings to option string; fall back to None
        info = self.coordinator.data.get("info", {}).get("data", {})
        val = info.get("print_speed_mode")
        if val is None:
            return None
        # reverse map
        for k, v in self._value_map.items():
            if v == val:
                return k
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            _LOGGER.debug("Invalid option selected: %s", option)
            return
        mapped = self._value_map.get(option)
        if mapped is None:
            _LOGGER.debug("No mapping for option %s", option)
            return

        # publish via print update settings
        payload = {"type": "print", "action": "update", "data": {"taskid": "-1", "settings": {"print_speed_mode": mapped}}}
        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic("print")
            mqtt.publish_json(topic, payload)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish print_speed_mode change: %s", err)

    @property
    def device_info(self) -> dict:
        """Return device registry information for this integration."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }