"""Button platform for Anycubic Kobra S1."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, BUTTON_DEFINITIONS


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic buttons for the given config entry.

    The coordinator instance is read from hass.data and used to create
    one :class:`AnycubicButton` per definition in ``BUTTON_DEFINITIONS``.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([AnycubicButton(coordinator, d) for d in BUTTON_DEFINITIONS])

    # Buttons may trigger axis/print actions; request those topics once so
    # state is available after setup.
    try:
        await coordinator.async_query_topic("axis")
    except Exception:
        _LOGGER.debug("Failed to query axis on button setup")
    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Failed to query print on button setup")


class AnycubicButton(CoordinatorEntity, ButtonEntity):
    """Generic button entity for Anycubic actions (homing, print control)."""

    def __init__(self, coordinator, definition: dict):
        """Initialize a button entity from a definition dict.

        Expected definition keys:
        - name: display name
        - key: unique key used for unique_id
        - type: message type (e.g. 'axis' or 'print')
        - action: action name (e.g. 'move', 'stop', 'pause', 'resume')
        - axis: optional axis index for axis actions
        """
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._type = definition["type"]
        self._action = definition["action"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_icon = definition.get("icon", "mdi:button-pointer")
        self._attr_has_entity_name = True
        self._axis = definition.get("axis")

    async def async_press(self) -> None:
        """Send the defined control message when the button is pressed."""
        if self._type == "axis":
            payload = {
                "type": "axis",
                "action": self._action,
                "data": {"axis": self._axis, "move_type": 2, "distance": 0},
            }
            topic_name = "axis"
        elif self._type == "print":
            payload = {"type": "print", "action": self._action, "data": {"taskid": "-1"}}
            topic_name = "print"
        else:
            _LOGGER.debug("Unknown button type: %s", self._type)
            return

        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.web_topic(topic_name)
            # Delegate error handling to the MQTT client implementation
            mqtt.publish_json(topic, payload)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("MQTT publish failed for button %s: %s", self._key, err)

    @property
    def device_info(self) -> dict:
        """Return the device information mapping for the device registry."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }