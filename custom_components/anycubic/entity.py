"""Generic base entity classes shared by Anycubic backends."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import PrinterEntityType
from .helper.mapper import build_cloud_entity_device_info, printer_entity_unique_id

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo


@dataclass(frozen=True, kw_only=True)
class AnycubicEntityDescription(EntityDescription):
    """Generic Anycubic entity description."""

    printer_entity_type: PrinterEntityType | None = None


def _humanize_entity_key(value: str) -> str:
    """Convert snake_case entity keys to readable titles."""
    text = value.replace("_", " ").strip()
    for prefix in ["ace pro 1 ", "ace pro 2 ", "secondary "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.replace("job ", "print ")
    text = text.replace("curr ", "current ")
    text = text.replace("fw ", "firmware ")
    return text.title()


def _normalize_entity_name(description: EntityDescription) -> str | None:
    """Return a valid human-readable name candidate."""
    name = getattr(description, "name", None)
    if name is not None and name is not UNDEFINED and str(name).strip() != "":
        return _humanize_entity_key(str(name))

    return None


class AnycubicEntity(CoordinatorEntity, Entity):
    """Base implementation for Anycubic entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._printer_id = int(printer_id)
        printer_entity_type = getattr(entity_description, "printer_entity_type", None)
        self._attr_device_info: DeviceInfo = build_cloud_entity_device_info(
            coordinator.data,
            self._printer_id,
            printer_entity_type,
        )
        self.entity_description = entity_description
        self._attr_unique_id = printer_entity_unique_id(coordinator, self._printer_id, entity_description.key)

        if not getattr(self, "_attr_name", None):
            normalized_name = _normalize_entity_name(entity_description)
            if normalized_name:
                self._attr_name = normalized_name
        self._attr_translation_key = (
            getattr(entity_description, "translation_key", None)
            or getattr(entity_description, "key", None)
        )

