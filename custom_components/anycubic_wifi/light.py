import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic light entity for Kobra S1."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([
        AnycubicLightEntity(coordinator, "printer"),
    ])


class AnycubicLightEntity(CoordinatorEntity, LightEntity):
    """Anycubic Kobra S1 enclosure light as Home Assistant light entity."""
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator, channel: str):
        super().__init__(coordinator)
        self._type_id = 2
        self._attr_unique_id = "anycubic_light_printer"
        self._attr_name = "Enclosure Light"

    @property
    def is_on(self) -> bool:
        """Return True if the enclosure light is on."""
        light = self.coordinator.data.get("light")
        if light and isinstance(light.get("data"), dict):
            lights = light["data"].get("lights")
            if isinstance(lights, list):
                for l in lights:
                    if l.get("type") == self._type_id:
                        return l.get("status") == 1
            if light["data"].get("type") == self._type_id:
                return light["data"].get("status") == 1
        return False

    @property
    def brightness(self) -> int:
        """Return the brightness of the enclosure light."""
        light = self.coordinator.data.get("light")
        if light and isinstance(light.get("data"), dict):
            lights = light["data"].get("lights")
            if isinstance(lights, list):
                for l in lights:
                    if l.get("type") == self._type_id:
                        pct = l.get("brightness", 0)
                        return int(pct * 2.55)
            if light["data"].get("type") == self._type_id:
                pct = light["data"].get("brightness", 0)
                return int(pct * 2.55)
        return 0

    async def async_turn_on(self, **kwargs: Any):
        """Turn the enclosure light on."""
        pct = int(kwargs.get(ATTR_BRIGHTNESS, 255) / 2.55)
        await self._publish_light(status=1, brightness=pct)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the enclosure light off."""
        await self._publish_light(status=0, brightness=0)

    async def _publish_light(self, status: int, brightness: int):
        """Publish MQTT message to control enclosure light."""
        payload = {
            "type": "light",
            "action": "control",
            "data": {"type": self._type_id, "status": status, "brightness": brightness},
        }
        if self.coordinator.mqtt:
            topic = self.coordinator.mqtt.web_topic("light")
            self.coordinator.mqtt.publish_json(topic, payload)
        else:
            _LOGGER.warning("%s: MQTT client not available, cannot publish light state!", self.entity_id)

    @property
    def device_info(self):
        """Return device info for Home Assistant device registry."""
        info = self.coordinator.data.get("info", {}).get("data", {})
        return {
            "identifiers": {(DOMAIN, "anycubic_wifi")},
            "name": info.get("model", "Anycubic Printer"),
            "manufacturer": "Anycubic",
            "model": info.get("model", "Unknown"),
            "sw_version": info.get("version", "Unknown"),
        }