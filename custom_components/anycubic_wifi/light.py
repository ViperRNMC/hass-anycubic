import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    async_add_entities([
        AnycubicLightEntity(coordinator, "printer"),
        AnycubicLightEntity(coordinator, "camera"),
    ])


class AnycubicLightEntity(CoordinatorEntity, LightEntity):
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, coordinator, channel: str):
        super().__init__(coordinator)
        self._type_id = 3 if channel == "camera" else 1
        self._attr_unique_id = f"anycubic_light_{channel}"
        self._attr_name = f"Anycubic Light {channel.title()}"

    @property
    def is_on(self) -> bool:
        light = self.coordinator.data.get("light")
        if light and isinstance(light.get("data"), dict):
            return (
                    light["data"].get("type") == self._type_id
                    and light["data"].get("status") == 1
            )
        return False

    @property
    def brightness(self) -> int:
        light = self.coordinator.data.get("light")
        if light and isinstance(light.get("data"), dict):
            if light["data"].get("type") == self._type_id:
                pct = light["data"].get("brightness", 0)
                return int(pct * 2.55)
        return 0

    async def async_turn_on(self, **kwargs: Any):
        pct = int(kwargs.get(ATTR_BRIGHTNESS, 255) / 2.55)
        await self._publish_light(status=1, brightness=pct)

    async def async_turn_off(self, **kwargs: Any):
        await self._publish_light(status=0, brightness=0)

    async def _publish_light(self, status: int, brightness: int):
        payload = {
            "type": "light",
            "action": "control",
            "data": {"type": self._type_id, "status": status, "brightness": brightness},
        }
        topic = self.coordinator.mqtt.web_topic("light")
        _LOGGER.debug("%s → MQTT %s: %s", self.entity_id, topic, payload)
    
    @property
    def device_info(self):
        info = self.coordinator.data.get("info", {}).get("data", {})
        return {
            "identifiers": {(DOMAIN, "anycubic_wifi")},
            "name": info.get("model", "Anycubic Printer"),
            "manufacturer": "Anycubic",
            "model": info.get("model", "Unknown"),
            "sw_version": info.get("version", "Unknown"),
        }
        self.coordinator.mqtt.publish_json(topic, payload)
