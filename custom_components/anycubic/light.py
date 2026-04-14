"""Light platform for Anycubic Kobra S1."""

import logging

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONNECTION_MODE_LAN, DOMAIN, MANUFACTURER, MODEL
from .descriptions import get_descriptions


_LOGGER = logging.getLogger(__name__)
LAN_LIGHT_DEFINITION = get_descriptions(CONNECTION_MODE_LAN, "light")[0]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Anycubic chamber light for the given config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([AnycubicLightEntity(coordinator, LAN_LIGHT_DEFINITION)])

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
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_icon = definition.get("icon", "mdi:lightbulb")
        self._attr_has_entity_name = True
        self._type_id = definition["type_id"]
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS

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
        try:
            await self.coordinator.light_set_event(self._key, self._type_id, status=1, brightness=pct)

            # optimistic update
            self.async_write_ha_state()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish light command: %s", err)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the chamber light off."""
        try:
            await self.coordinator.light_set_event(self._key, self._type_id, status=0, brightness=0)

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