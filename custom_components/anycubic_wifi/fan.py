
import logging
from typing import Any
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN



_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic fan entities for Kobra S1."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([
        AnycubicFanEntity(coordinator, "main"),
        AnycubicFanEntity(coordinator, "aux"),
        AnycubicFanEntity(coordinator, "box"),
    ])


class AnycubicFanEntity(CoordinatorEntity, FanEntity):
    """Anycubic Kobra S1 fan entity (main, aux, box)."""
    _attr_percentage_step = 1
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )
    _attr_supported_percentage = True

    def __init__(self, coordinator, fan_type: str):
        super().__init__(coordinator)
        self._fan_type = fan_type
        self._attr_unique_id = f"anycubic_fan_{fan_type}"
        self._attr_name = f"{fan_type.title()} Fan"

    @property
    def is_on(self) -> bool:
        """Return True if fan speed > 0."""
        speed = self._get_speed()
        return speed > 0

    @property
    def percentage(self) -> int:
        """Return current fan speed percentage."""
        return self._get_speed()

    def _get_speed(self) -> int:
        """Get the current fan speed percentage."""
        fan_data = self.coordinator.data.get("fan", {}).get("data", {})
        print_data = self.coordinator.data.get("print", {}).get("data", {})
        if self._fan_type == "main":
            if "fan_speed_pct" in print_data:
                return int(print_data.get("fan_speed_pct", 0))
            return int(fan_data.get("fan_speed_pct", 0))
        if self._fan_type == "aux":
            if "aux_fan_speed_pct" in print_data:
                return int(print_data.get("aux_fan_speed_pct", 0))
            return int(fan_data.get("aux_fan_speed_pct", 0))
        if self._fan_type == "box":
            if "box_fan_level" in print_data:
                return int(print_data.get("box_fan_level", 0))
            return int(fan_data.get("box_fan_level", 0))
        return 0

    async def async_set_percentage(self, percentage: int):
        """Set fan speed percentage."""
        await self._publish_fan(percentage)

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn fan on (default 100%)."""
        if percentage is None:
            percentage = 100
        await self._publish_fan(percentage)

    async def async_turn_off(self, **kwargs: Any):
        """Turn fan off (set speed to 0%)."""
        await self._publish_fan(0)

    async def _publish_fan(self, percentage: int):
        """Publish MQTT message to control fan speed."""
        payload = {
            "type": "fan",
            "action": "control",
            "fan_type": self._fan_type,
        }
        if self._fan_type == "box":
            payload["box_fan_level"] = percentage
        elif self._fan_type == "aux":
            payload["aux_fan_speed_pct"] = percentage
        elif self._fan_type == "main":
            payload["fan_speed_pct"] = percentage
        else:
            payload["percentage"] = percentage
        if self.coordinator.mqtt:
            topic = self.coordinator.mqtt.printer_topic("fan")
            _LOGGER.debug("Publishing fan command: topic=%s, payload=%s", topic, payload)
            _LOGGER.debug("Current fan data: %s", self.coordinator.data.get("fan", {}))
            self.coordinator.mqtt.publish_json(topic, payload)
        else:
            _LOGGER.warning(
                "%s: MQTT client not available, cannot publish fan state!", self.entity_id
            )

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
    
    def handle_mqtt_message(self, topic, payload):
        logging.getLogger(__name__).debug(f"RAW MQTT: topic={topic}, payload={payload}")