"""Light platform for Anycubic Kobra S1."""

import logging

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, LIGHT_DEFINITION


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Anycubic chamber light for the given config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([AnycubicLightEntity(coordinator, LIGHT_DEFINITION)])

    # Request initial state for the light topic specifically. Platforms
    # should request only topics they need to avoid unnecessary queries on
    # coordinator startup.
    try:
        await coordinator.async_query_topic("light")
    except Exception:
        _LOGGER.debug("Failed to query light on setup")


class AnycubicLightEntity(CoordinatorEntity, LightEntity):
    """Chamber light entity backed by the integration coordinator."""

    def __init__(self, coordinator, definition: dict):
        """Initialize the entity using the provided definition."""
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{self._key}"
        )
        self._attr_icon = definition.get("icon", "mdi:lightbulb")
        self._attr_has_entity_name = True
        self._type_id = definition["type_id"]

    def _find_light_data(self) -> dict:
        """Return the dict containing status/brightness for this light type.

        The device may report a single ``data`` mapping or a list under
        ``data.lights``. This helper normalizes those shapes and returns the
        matching dict (or empty dict when not present).
        """
        light = self.coordinator.data.get("light", {}) or {}
        data = light.get("data") if isinstance(light.get("data"), dict) else {}
        lights = data.get("lights")
        if isinstance(lights, list):
            for l in lights:
                if l.get("type") == self._type_id:
                    return l
        if data.get("type") == self._type_id:
            return data
        return {}

    @property
    def is_on(self) -> bool:
        """Return True if the chamber light is currently on."""
        data = self._find_light_data()
        return data.get("status") == 1

    @property
    def brightness(self) -> int:
        """Return the brightness scaled to 0-255 for Home Assistant."""
        data = self._find_light_data()
        pct = int(data.get("brightness", 0))
        return max(0, min(255, int(pct * 2.55)))

    async def async_turn_on(self, **kwargs: Any):
        """Turn the chamber light on and optionally set brightness."""
        pct = int(kwargs.get(ATTR_BRIGHTNESS, 255) / 2.55)
        payload = {
            "type": "light",
            "action": "control",
            "data": {"type": self._type_id, "status": 1, "brightness": pct},
        }
        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic("light")
            # Delegate publish and error handling to the MQTT client layer
            mqtt.publish_json(topic, payload)

            # optimistic update
            self.async_write_ha_state()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish light command: %s", err)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the chamber light off."""
        payload = {
            "type": "light",
            "action": "control",
            "data": {"type": self._type_id, "status": 0, "brightness": 0},
        }
        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic("light")
            mqtt.publish_json(topic, payload)

            # optimistic update
            self.async_write_ha_state()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish light off command: %s", err)

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