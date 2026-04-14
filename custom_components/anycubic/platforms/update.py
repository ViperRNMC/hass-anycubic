"""Anycubic firmware update platform for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..helper.device_info import build_ace_device_info, build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator not found for update setup: %s", entry.entry_id)
        return

    entities: list[UpdateEntity] = [AnycubicFirmwareUpdateEntity(coordinator)]
    created_box_ids: set[int] = set()
    for box in coordinator.get_boxes() or []:
        box_id = box.get("id")
        if not isinstance(box_id, int):
            continue
        created_box_ids.add(box_id)
        entities.append(AnycubicAceFirmwareUpdateEntity(coordinator, box_id))

    async_add_entities(entities)

    # If boxes arrive later, add update entities dynamically.
    def _on_boxes_updated(_boxes_list):
        new_entities: list[UpdateEntity] = []
        for box in coordinator.get_boxes() or []:
            box_id = box.get("id")
            if not isinstance(box_id, int) or box_id in created_box_ids:
                continue
            created_box_ids.add(box_id)
            new_entities.append(AnycubicAceFirmwareUpdateEntity(coordinator, box_id))
        if new_entities:
            async_add_entities(new_entities)

    async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)


class AnycubicFirmwareUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Firmware update entity for the Anycubic printer."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_title = "Anycubic Printer Firmware"
    _attr_icon = "mdi:package-up"

    def __init__(self, coordinator) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_name = "Firmware"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_firmware_update"
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> dict[str, Any]:
        return build_main_device_info(self.coordinator)

    def _info_data(self) -> dict[str, Any]:
        return (self.coordinator.data.get("info") or {}).get("data") or {}

    @property
    def installed_version(self) -> str | None:
        return self._info_data().get("version")

    @property
    def latest_version(self) -> str | None:
        info = self._info_data()
        available = info.get("available_version")
        # Fall back to installed so HA shows "up to date" when no update info
        return available if available is not None else info.get("version")


class AnycubicAceFirmwareUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Firmware update entity for an ACE Pro box."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)
    _attr_icon = "mdi:package-up"

    def __init__(self, coordinator, box_id: int) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        self._box_id = box_id
        self._attr_name = "Firmware"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_ace_pro_box_{box_id}_firmware_update"
        self._attr_has_entity_name = True

    def _get_box(self) -> dict[str, Any] | None:
        for box in self.coordinator.get_boxes() or []:
            if box.get("id") == self._box_id:
                return box
        return None

    @property
    def available(self) -> bool:
        return self._get_box() is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return build_ace_device_info(self.coordinator, self._box_id, self.installed_version)

    @property
    def installed_version(self) -> str | None:
        box = self._get_box() or {}
        return box.get("firmware")

    @property
    def latest_version(self) -> str | None:
        box = self._get_box() or {}
        available = box.get("available_firmware")
        return available if available is not None else box.get("firmware")
