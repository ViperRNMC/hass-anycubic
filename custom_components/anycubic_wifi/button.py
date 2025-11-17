
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HOMING_BUTTONS = [
    ("Home All", 5),
    ("Home XY", 4),
    ("Home Z", 3),
]

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic home buttons."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entities = []
    for name, axis in HOMING_BUTTONS:
        entities.append(AnycubicHomeButton(coordinator, name, axis))
    async_add_entities(entities)

class AnycubicHomeButton(CoordinatorEntity, ButtonEntity):
    """Button entity for homing axes."""
    def __init__(self, coordinator, name: str, axis: int):
        super().__init__(coordinator)
        self._axis = axis
        self._attr_name = f"{name}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_home_{axis}"

    async def async_press(self) -> None:
        """Send homing command via MQTT."""
        payload = {
            "type": "axis",
            "action": "move",
            "data": {
                "axis": self._axis,
                "move_type": 2,
                "distance": 0
            }
        }
        topic = self.coordinator.mqtt.web_topic("axis")
        self.coordinator.mqtt.publish_json(topic, payload)

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
