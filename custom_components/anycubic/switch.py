"""Switch platform for Anycubic with LAN and Cloud support."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .entity import AnycubicEntity
from .helper.mapper import printer_state_for_key
from .descriptions import get_descriptions
from .helper.connection_mode import get_entry_connection_mode
from .const import (
    ACE_PRO_DEVICE_BASE,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    COORDINATOR,
    DEVICE_TYPE_ACE_PRO,
    DEVICE_TYPE_EXTFILBOX,
    DOMAIN,
    EXTFILBOX_DEVICE_BASE,
    MANUFACTURER,
    MODEL,
    MULTI_COLOR_BOX_KEY,
    PrinterEntityType,
)

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator

_LOGGER = logging.getLogger(__name__)
LAN_SWITCH_DEFINITIONS = get_descriptions(CONNECTION_MODE_LAN, "switch")


@dataclass(frozen=True)
class AnycubicSwitchEntityDescription(
    SwitchEntityDescription
):
    """Describes Anycubic Cloud switch entity."""
    printer_entity_type: PrinterEntityType | None = None


SWITCH_TYPES: list[AnycubicSwitchEntityDescription] = list([
    AnycubicSwitchEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "switch")
])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anycubic switches for a config entry."""
    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD:
        await _setup_cloud_switches(hass, entry, async_add_entities)
        return

    await _setup_lan_switches(hass, entry, async_add_entities)


async def _setup_lan_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("Coordinator async_get_boxes failed; falling back to cached boxes")

    entities: list[SwitchEntity] = []
    expanded_switches = coordinator.expand_definitions(LAN_SWITCH_DEFINITIONS)
    for definition in expanded_switches:
        if definition.get("device_type") == DEVICE_TYPE_ACE_PRO:
            box_id = definition.get("box_id")
            entities.append(AnycubicLanSwitch(coordinator, box_id, definition))
        else:
            entities.append(AnycubicLanSwitch(coordinator, None, definition))

    if not boxes:

        def _on_boxes_updated(boxes_list):
            expanded = coordinator.expand_definitions(LAN_SWITCH_DEFINITIONS)
            new_entities: list[SwitchEntity] = []
            for definition in expanded:
                if definition.get("device_type") == DEVICE_TYPE_ACE_PRO:
                    box_id = definition.get("box_id")
                    new_entities.append(AnycubicLanSwitch(coordinator, box_id, definition))
                else:
                    new_entities.append(AnycubicLanSwitch(coordinator, None, definition))
            if not new_entities:
                return

            def _add_and_unsub():
                try:
                    async_add_entities(new_entities)
                except Exception:
                    _LOGGER.exception("Failed to add per-box switch entities")
                try:
                    unsub()
                except Exception:
                    pass

            coordinator.hass.loop.call_soon_threadsafe(_add_and_unsub)

        unsub = async_dispatcher_connect(
            coordinator.hass,
            f"{DOMAIN}_boxes_updated",
            _on_boxes_updated,
        )

    async_add_entities(entities)


async def _setup_cloud_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR
    ]
    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudSwitch,
        platform=Platform.SWITCH,
        available_descriptors=SWITCH_TYPES,
    )


class AnycubicLanSwitch(CoordinatorEntity, SwitchEntity):
    """Generic LAN switch created from SWITCH_DEFINITIONS."""

    def __init__(self, coordinator, box_id: int, definition: dict):
        super().__init__(coordinator)
        self.box_id = box_id
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition.get("name")
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_has_entity_name = True
        self._box_id: Optional[int] = definition.get("box_id")

    def _find_box(self) -> dict | None:
        boxes = self.coordinator.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get(
            "multi_color_box", []
        )
        for box in boxes:
            if box.get("id") == self.box_id:
                return box
        return None

    @property
    def is_on(self) -> bool:
        if self._key == "manual_mqtt_connection_enabled":
            return bool(getattr(self.coordinator.mqtt, "debug_logging", False))

        box = self._find_box()
        if not box:
            return False
        key = self.definition.get("key")
        if key and "drying" in key:
            drying_status = box.get("drying_status", {})
            return bool(drying_status.get("status") == 1)
        if key and ("auto_feed" in key or "autofeed" in key):
            return bool(box.get("auto_feed") == 1)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.switch_on_event(
            None,
            self._key,
            box_id=self.box_id,
            target_temp=kwargs.get("target_temp"),
            duration=kwargs.get("duration"),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.switch_off_event(
            None,
            self._key,
            box_id=self.box_id,
        )

    @property
    def extra_state_attributes(self) -> dict:
        attributes: dict = {}
        box = self._find_box()
        if not box:
            return attributes
        key = self.definition.get("key")
        if key and "drying" in key:
            drying_status = box.get("drying_status", {})
            attributes["drying_status"] = drying_status.get("status")
            attributes["drying_target_temp"] = drying_status.get("target_temp")
            attributes["target_temp"] = drying_status.get("target_temp")
            attributes["drying_duration"] = drying_status.get("duration")
            attributes["duration"] = drying_status.get("duration")
        if key and ("auto_feed" in key or "autofeed" in key):
            attributes["auto_feed"] = box.get("auto_feed")
        return attributes

    @property
    def device_info(self) -> dict:
        device_type = self.definition.get("device_type")
        entry_id = getattr(self.coordinator.config_entry, "entry_id", "unknown")

        if device_type == DEVICE_TYPE_ACE_PRO:
            return {
                "identifiers": {(DOMAIN, f"{entry_id}_ace_pro_box_{self.box_id}")},
                **ACE_PRO_DEVICE_BASE,
            }
        if device_type == DEVICE_TYPE_EXTFILBOX:
            return {
                "identifiers": {(DOMAIN, f"{entry_id}_extfilbox")},
                **EXTFILBOX_DEVICE_BASE,
            }

        return {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }

    def _find_box_by_id(self, top_level_data: dict, box_id: int) -> Optional[dict]:
        boxes = top_level_data.get("data", {}).get("multi_color_box", [])
        for box in boxes:
            if box.get("id") == box_id:
                return box
        return None


class AnycubicCloudSwitch(AnycubicEntity, SwitchEntity):
    """Representation of an Anycubic Cloud switch."""

    entity_description: AnycubicSwitchEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicSwitchEntityDescription,
    ) -> None:
        super().__init__(hass, coordinator, printer_id, entity_description)

    @property
    def is_on(self) -> bool:
        return bool(
            printer_state_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.switch_on_event(self._printer_id, self.entity_description.key)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.switch_off_event(self._printer_id, self.entity_description.key)