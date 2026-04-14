"""Update platform for Anycubic — supports both LAN and Cloud modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COORDINATOR,
    DOMAIN,
    CONNECTION_MODE_CLOUD,
    PrinterEntityType,
)
from .descriptions import get_descriptions
from .helper.connection_mode import get_entry_connection_mode
from .entity import AnycubicEntity
from .helper.mapper import printer_attributes_for_key, printer_state_for_key

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator


@dataclass(frozen=True)
class AnycubicCloudUpdateEntityDescription(
    UpdateEntityDescription
):
    """Describes Anycubic Cloud update entity."""
    printer_entity_type: PrinterEntityType | None = None


UPDATE_TYPES: list[AnycubicCloudUpdateEntityDescription] = list([
    AnycubicCloudUpdateEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "update")
])


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up update entities — Cloud mode only."""
    mode = get_entry_connection_mode(entry)
    
    if mode == CONNECTION_MODE_CLOUD:
        return await _setup_cloud_updates(hass, entry, async_add_entities)
    # LAN mode has no update platform


async def _setup_cloud_updates(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cloud mode update entities."""
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    
    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudUpdateEntity,
        platform=Platform.UPDATE,
        available_descriptors=UPDATE_TYPES,
    )


class AnycubicCloudUpdateEntity(AnycubicEntity, UpdateEntity):
    """Representation of a Anycubic Cloud update entity."""

    entity_description: AnycubicCloudUpdateEntityDescription
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicCloudUpdateEntityDescription,
    ) -> None:
        """Initialize Anycubic Update Entity."""
        super().__init__(hass, coordinator, printer_id, entity_description)

    @property
    def installed_version(self) -> str:
        """Version currently in use."""
        return str(printer_state_for_key(self.coordinator, self._printer_id, self.entity_description.key))

    @property
    def latest_version(self) -> str:
        """Latest version available for install."""
        fw_attr = printer_attributes_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        return str(fw_attr['latest_version']) if fw_attr else "error"

    @property
    def in_progress(self) -> bool:
        """Update installation in progress."""
        fw_attr = printer_attributes_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        return bool(fw_attr['in_progress']) if fw_attr else False

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the latest version."""
        await self.coordinator.fw_update_event(self._printer_id, self.entity_description.key)
