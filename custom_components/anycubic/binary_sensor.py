"""Binary sensors for the Anycubic integration with LAN and Cloud support."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import AnycubicEntity
from .helper.mapper import printer_attributes_for_key, printer_state_for_key
from .descriptions import get_descriptions
from .helper.connection_mode import get_entry_connection_mode
from .const import (
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    MSG_TRANSLATIONS,
    PrinterEntityType,
)

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator

_LOGGER = logging.getLogger(__name__)
LAN_BINARY_DEFINITIONS = get_descriptions(CONNECTION_MODE_LAN, "binary_sensor")


@dataclass(frozen=True)
class AnycubicBinarySensorEntityDescription(
    BinarySensorEntityDescription
):
    """Describes Anycubic Cloud binary sensor entity."""
    printer_entity_type: PrinterEntityType | None = None


SENSOR_TYPES: list[AnycubicBinarySensorEntityDescription] = list([
    AnycubicBinarySensorEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "binary_sensor")
])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anycubic binary sensors for a config entry."""
    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD:
        await _setup_cloud_binary_sensors(hass, entry, async_add_entities)
        return

    await _setup_lan_binary_sensors(hass, entry, async_add_entities)


async def _setup_lan_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    entities: list[BinarySensorEntity] = []
    for definition in LAN_BINARY_DEFINITIONS:
        try:
            entities.append(AnycubicLanBinarySensor(coordinator, definition))
        except Exception:
            _LOGGER.exception("Failed to create binary sensor from definition %s", definition)

    if entities:
        async_add_entities(entities)

    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Coordinator print query failed or MQTT not ready")
    try:
        await coordinator.async_query_topic("tempature")
    except Exception:
        _LOGGER.debug("Coordinator tempature query failed or MQTT not ready")


async def _setup_cloud_binary_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR
    ]
    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudBinarySensor,
        platform=Platform.BINARY_SENSOR,
        available_descriptors=SENSOR_TYPES,
    )


class AnycubicLanBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Definition-driven binary sensor for LAN mode."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition.get("key")
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_has_entity_name = True

        category = definition.get("entity_category")
        if category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        device_class = definition.get("device_class")
        if device_class:
            try:
                self._attr_device_class = getattr(BinarySensorDeviceClass, device_class.upper())
            except AttributeError:
                _LOGGER.warning("Unknown device_class '%s' for %s", device_class, self._key)

        icon = definition.get("icon")
        if icon:
            self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        dtype = self.definition.get("type")

        if dtype == "print_problem":
            data = self.coordinator.data.get("print", {})
            code = data.get("code")
            msg = data.get("msg")
            try:
                if code is not None and int(code) != 200:
                    return True
            except Exception:
                return True
            if msg is not None and str(msg).strip().lower() != "done":
                return True
            return False

        if dtype in ("nozzle_heating", "bed_heating"):
            tdata = self.coordinator.data.get("tempature", {})
            t = tdata.get("data") or {}
            try:
                if dtype == "nozzle_heating":
                    curr = float(t.get("curr_nozzle_temp") or 0)
                    target = float(t.get("target_nozzle_temp") or 0)
                else:
                    curr = float(t.get("curr_hotbed_temp") or 0)
                    target = float(t.get("target_hotbed_temp") or 0)
            except Exception:
                return False
            return target > (curr + 0.5)

        _LOGGER.debug("Unknown binary sensor type '%s' for %s", dtype, self._key)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dtype = self.definition.get("type")
        if dtype == "print_problem":
            data = self.coordinator.data.get("print", {})
            text = data.get("msg")
            translated = None
            if text:
                translated = MSG_TRANSLATIONS.get(str(text).strip())
            return {"code": data.get("code"), "text": text, "text_translated": translated}
        if dtype == "nozzle_heating":
            tdata = self.coordinator.data.get("tempature", {})
            t = tdata.get("data") or {}
            return {"current": t.get("curr_nozzle_temp"), "target": t.get("target_nozzle_temp")}
        if dtype == "bed_heating":
            tdata = self.coordinator.data.get("tempature", {})
            t = tdata.get("data") or {}
            return {"current": t.get("curr_hotbed_temp"), "target": t.get("target_hotbed_temp")}
        return {}

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }


class AnycubicCloudBinarySensor(AnycubicEntity, BinarySensorEntity):
    """Representation of an Anycubic Cloud binary sensor."""

    entity_description: AnycubicBinarySensorEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicBinarySensorEntityDescription,
    ) -> None:
        super().__init__(hass, coordinator, printer_id, entity_description)

    @property
    def is_on(self) -> bool:
        return bool(
            printer_state_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrib = printer_attributes_for_key(
            self.coordinator,
            self._printer_id,
            self.entity_description.key,
        )
        if attrib is not None:
            return attrib
        return None