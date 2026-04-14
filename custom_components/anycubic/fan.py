"""Fan platform for Anycubic Kobra S1."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.fan import FanEntity, FanEntityDescription, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PrinterEntityType,
)
from .descriptions import get_descriptions
from .entity import AnycubicEntity
from .helper.connection_mode import get_entry_connection_mode
from .helper.mapper import printer_attributes_for_key, printer_state_for_key

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator


_LOGGER = logging.getLogger(__name__)
LAN_FAN_DEFINITIONS = get_descriptions(CONNECTION_MODE_LAN, "fan")
CLOUD_FAN_DEFINITIONS = get_descriptions(CONNECTION_MODE_CLOUD, "fan")


@dataclass(frozen=True)
class AnycubicCloudFanEntityDescription(FanEntityDescription):
    """Describes Anycubic Cloud fan entity."""

    printer_entity_type: PrinterEntityType | None = None


CLOUD_FAN_TYPES: list[AnycubicCloudFanEntityDescription] = [
    AnycubicCloudFanEntityDescription(**item)
    for item in CLOUD_FAN_DEFINITIONS
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anycubic fan entities for the given config entry.

    The coordinator instance is pulled from hass.data and used to construct
    one AnycubicFanEntity per centralized LAN fan definition.
    """
    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD:
        await _setup_cloud_fans(hass, entry, async_add_entities)
        return

    await _setup_lan_fans(hass, entry, async_add_entities)


async def _setup_lan_fans(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([AnycubicFanEntity(coordinator, d) for d in LAN_FAN_DEFINITIONS])

    # Request initial fan status specifically from the device. Platforms
    # should request only the topics they need to avoid unnecessary queries.
    try:
        await coordinator.async_query_topic("fan")
    except Exception:
        _LOGGER.debug("Failed to query fan on setup")


async def _setup_cloud_fans(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudFan,
        platform=Platform.FAN,
        available_descriptors=CLOUD_FAN_TYPES,
    )


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
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
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
        try:
            await self.coordinator.fan_set_event(self._key, self._data_key, int(percentage))

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


class AnycubicCloudFan(AnycubicEntity, FanEntity):
    """Cloud fan entity mapped from cloud printer state."""

    entity_description: AnycubicCloudFanEntityDescription

    _attr_percentage_step = 1
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicCloudFanEntityDescription,
    ) -> None:
        super().__init__(hass, coordinator, printer_id, entity_description)
        self._attr_icon = entity_description.icon or "mdi:fan"

    @property
    def percentage(self) -> int | None:
        state = printer_state_for_key(
            self.coordinator,
            self._printer_id,
            self.entity_description.key,
        )
        if state is None:
            return None
        try:
            return int(state)
        except Exception:
            return None

    @property
    def is_on(self) -> bool:
        pct = self.percentage
        return pct is not None and pct > 0

    async def async_set_percentage(self, percentage: int) -> None:
        await self.coordinator.fan_set_event(
            self._printer_id,
            self.entity_description.key,
            int(percentage),
        )

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        if percentage is None:
            percentage = 100
        await self.async_set_percentage(int(percentage))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_percentage(0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return printer_attributes_for_key(
            self.coordinator,
            self._printer_id,
            self.entity_description.key,
        )