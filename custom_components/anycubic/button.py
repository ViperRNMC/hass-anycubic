"""Button platform for Anycubic with LAN and Cloud support."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import AnycubicEntity
from .helper.mapper import printer_attributes_for_key
from .descriptions import get_descriptions
from .helper.connection_mode import get_entry_connection_mode
from .const import (
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PrinterEntityType,
)

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator

_LOGGER = logging.getLogger(__name__)
LAN_BUTTON_DEFINITIONS = get_descriptions(CONNECTION_MODE_LAN, "button")


@dataclass(frozen=True)
class AnycubicButtonEntityDescription(
    ButtonEntityDescription
):
    """Describes Anycubic Cloud button entity."""
    printer_entity_type: PrinterEntityType | None = None


BUTTON_TYPES: list[AnycubicButtonEntityDescription] = list([
    AnycubicButtonEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "button")
])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anycubic buttons for the given config entry."""
    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD:
        await _setup_cloud_buttons(hass, entry, async_add_entities)
        return

    await _setup_lan_buttons(hass, entry, async_add_entities)


async def _setup_lan_buttons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    entities: list[ButtonEntity] = []
    for definition in LAN_BUTTON_DEFINITIONS:
        if definition.get("key") in ("pause_print", "resume_print"):
            continue
        entities.append(AnycubicLanButton(coordinator, definition))

    entities.append(AnycubicLanPrintToggle(coordinator))

    async_add_entities(entities)

    try:
        await coordinator.async_query_topic("axis")
    except Exception:
        _LOGGER.debug("Failed to query axis on button setup")
    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Failed to query print on button setup")


async def _setup_cloud_buttons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR
    ]

    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudButton,
        platform=Platform.BUTTON,
        available_descriptors=BUTTON_TYPES,
    )


class AnycubicLanButton(CoordinatorEntity, ButtonEntity):
    """Generic LAN button entity for Anycubic actions."""

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._type = definition["type"]
        self._action = definition["action"]
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_icon = definition.get("icon", "mdi:button-pointer")
        self._attr_has_entity_name = True
        self._axis = definition.get("axis")

    async def async_press(self) -> None:
        try:
            await self.coordinator.button_press_event(None, self._key)
        except Exception as err:
            _LOGGER.debug("MQTT publish failed for button %s: %s", self._key, err)

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }


class AnycubicLanPrintToggle(CoordinatorEntity, ButtonEntity):
    """Single LAN button that toggles print pause/resume."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Print Pause/Resume"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_print_pause_resume"
        self._attr_has_entity_name = True

    @property
    def _print_state(self) -> dict:
        return self.coordinator.data.get("print", {})

    @property
    def name(self) -> str:
        state = self._print_state.get("state")
        if state == "paused":
            return "Print Resume"
        return "Print Pause"

    @property
    def icon(self) -> str:
        state = self._print_state.get("state")
        return "mdi:play" if state == "paused" else "mdi:pause"

    async def async_press(self) -> None:
        state = self._print_state.get("state")
        event_key = "resume_print" if state == "paused" else "pause_print"
        try:
            await self.coordinator.button_press_event(None, event_key)
        except Exception as err:
            _LOGGER.debug("MQTT publish failed for print toggle: %s", err)

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }


class AnycubicCloudButton(AnycubicEntity, ButtonEntity):
    """A button for Anycubic Cloud."""

    entity_description: AnycubicButtonEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicButtonEntityDescription,
    ) -> None:
        super().__init__(hass, coordinator, printer_id, entity_description)

    async def async_press(self) -> None:
        if TYPE_CHECKING:
            assert self.coordinator.anycubic_api, "Connection to API is missing"

        await self.coordinator.button_press_event(self._printer_id, self.entity_description.key)

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