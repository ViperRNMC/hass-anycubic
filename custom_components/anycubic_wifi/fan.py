"""Fan platform for Anycubic Kobra S1."""

import logging

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, FAN_DEFINITIONS


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic fan entities for the given config entry.

    The coordinator instance is pulled from hass.data and used to construct
    one AnycubicFanEntity per definition in ``FAN_DEFINITIONS``.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([AnycubicFanEntity(coordinator, d) for d in FAN_DEFINITIONS])

    # Request initial fan status specifically from the device. Platforms
    # should request only the topics they need to avoid unnecessary queries.
    try:
        await coordinator.async_query_topic("fan")
    except Exception:
        _LOGGER.debug("Failed to query fan on setup")


class AnycubicFanEntity(CoordinatorEntity, FanEntity):
    """Generic fan entity for Anycubic."""

    _attr_percentage_step = 1
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON |
        FanEntityFeature.TURN_OFF
    )
    _attr_supported_percentage = True

    def __init__(self, coordinator, definition: dict):
        """Initialize the fan entity from a definition dict."""
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._data_key = definition.get("data_key")
        self._attr_icon = definition.get("icon", "mdi:fan")
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        """Return True if the fan is currently on (percentage > 0)."""
        return self._get_speed() > 0

    @property
    def percentage(self) -> int:
        """Return the current fan speed as a percentage."""
        return self._get_speed()

    def _get_speed(self) -> int:
        """Retrieve the current fan speed from coordinator data.

        The device reports fan data under two topics: ``fan`` and ``print``.
        Values from the ``print`` topic take precedence when present.
        """
        fan_data = self.coordinator.data.get("fan", {}).get("data", {})
        print_data = self.coordinator.data.get("print", {}).get("data", {})
        # Use the configured data key, allowing 'print' topic to override
        # 'fan' topic
        return int(print_data.get(self._data_key, fan_data.get(self._data_key, 0)))

    async def async_set_percentage(self, percentage: int):
        """Set the fan speed to the requested percentage."""
        await self._publish_fan(percentage)

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn the fan on (defaults to 100% if no percentage provided)."""
        if percentage is None:
            percentage = 100
        await self._publish_fan(percentage)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the fan off (set percentage to 0)."""
        await self._publish_fan(0)

    async def _publish_fan(self, percentage: int):
        """Publish a single MQTT message containing all fan values.

        The device expects a payload with ``action: "auto"`` containing
        ``fan_speed_pct``, ``aux_fan_speed_pct`` and ``box_fan_level`` in
        ``data``. We assemble the payload using the current known values and
        override the targeted fan with the requested percentage.
        """
        # Build a baseline using current coordinator values for each known
        # fan data_key
        fan_payload = self.coordinator.data.get("fan", {}).get("data", {}) or {}
        fan_data = {}
        for fdef in FAN_DEFINITIONS:
            key = fdef.get("data_key")
            fan_data[key] = int(fan_payload.get(key, 0))

        # Overwrite the requested fan value using this instance's data_key
        fan_data[self._data_key] = int(percentage)

        payload = {
            "type": "fan",
            "action": "auto",
            "data": fan_data,
        }
        try:
            mqtt = self.coordinator.mqtt
            topic = mqtt.printer_topic("fan")
            _LOGGER.debug("Publishing fan command: topic=%s, payload=%s", topic, payload)
            _LOGGER.debug("Current fan data: %s", self.coordinator.data.get("fan", {}))
            # Delegate publishing and error handling to mqtt client
            mqtt.publish_json(topic, payload)

            # optimistic update for UI
            self._attr_percentage = int(percentage)
            self.async_write_ha_state()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to publish fan command: %s", err)

    @property
    def device_info(self) -> dict:
        """Return the device info mapping for the device registry."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }