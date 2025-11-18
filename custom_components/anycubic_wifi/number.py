"""Anycubic number platform for Home Assistant."""

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, NUMBER_DEFINITIONS


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up number entities for Anycubic printers."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entities = [AnycubicNumber(coordinator, d) for d in NUMBER_DEFINITIONS]
    async_add_entities(entities)


class AnycubicNumber(CoordinatorEntity, NumberEntity):
    """Generic number entity for target temperatures (nozzle/hotbed)."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{self._key}_{serial}"
        )
        self._attr_icon = definition.get("icon", "mdi:thermometer")
        self._attr_has_entity_name = True
        self._attr_native_min_value = definition.get("min")
        self._attr_native_max_value = definition.get("max")
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        key = self.definition.get("data_key")
        if temp_report.get(key) is not None:
            return temp_report.get(key)
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get(key)

    async def async_set_native_value(self, value):
        # The device accepts temperature changes via a ``print`` update on
        # the web topic. Build a payload similar to:
        # {"type":"print","action":"update","data":{"taskid":"-1","settings":{<key>: value}}}
        settings = {self.definition.get("data_key"): int(value)}
        payload = {
            "type": "print",
            "action": "update",
            "data": {"taskid": "-1", "settings": settings},
        }
        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic("print")
            mqtt.publish_json(topic, payload)

            # optimistic update
            self._attr_native_value = int(value)
            self.async_write_ha_state()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish temp set via web topic %s: %s", self._key, err)

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }



