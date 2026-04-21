"""Select platform for Anycubic print settings (speed mode)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SELECT_DEFINITIONS
from .helper.device_info import build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    # Request current print settings so the select has an initial value
    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Coordinator query for print failed or MQTT not ready")

    entities: list[SelectEntity] = []
    for d in SELECT_DEFINITIONS:
        entities.append(AnycubicSelectEntity(coordinator, d))

    async_add_entities(entities)


class AnycubicSelectEntity(CoordinatorEntity, SelectEntity):
    """Generic Select backed by SELECT_DEFINITIONS."""

    _ACTIVE_PRINT_STATES = {"printing", "paused", "pausing", "resuming", "preheating"}

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_options = definition.get("options", [])
        self._value_map = definition.get("value_map", {})
        self._attr_has_entity_name = True

    @property
    def current_option(self) -> str | None:
        # map coordinator.info or settings to option string; fall back to None
        info = self.coordinator.data.get("info", {}).get("data", {})
        val = info.get("print_speed_mode")
        if val is None:
            return None
        effective_map = self._get_effective_value_map(info)
        # reverse map
        for k, v in effective_map.items():
            if v == int(val):
                return k
        return None

    @property
    def available(self) -> bool:
        return super().available and self._is_print_active()

    async def async_select_option(self, option: str) -> None:
        if not self._is_print_active():
            _LOGGER.debug("Ignoring print_speed_mode change while no print is active")
            return
        if option not in self._attr_options:
            _LOGGER.debug("Invalid option selected: %s", option)
            return
        info = self.coordinator.data.get("info", {}).get("data", {})
        mapped = self._get_effective_value_map(info).get(option)
        if mapped is None:
            _LOGGER.debug("No mapping for option %s", option)
            return

        # publish via transport-agnostic coordinator command path
        try:
            await self.coordinator.async_send_command("print", "setPrintSpeedMode", {"print_speed_mode": mapped})
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to send print_speed_mode change: %s", err)

    def _is_print_active(self) -> bool:
        print_data = self.coordinator.data.get("print", {}).get("data", {})
        state = str(print_data.get("state") or "").strip().lower()
        return state in self._ACTIVE_PRINT_STATES

    def _get_effective_value_map(self, info: dict[str, Any]) -> dict[str, int]:
        """Prefer cloud-provided mode mapping; fall back to static defaults."""
        effective_map: dict[str, int] = {}
        for k, v in self._value_map.items():
            try:
                effective_map[k] = int(v)
            except (TypeError, ValueError):
                continue

        cloud_map = info.get("print_speed_mode_map")
        if isinstance(cloud_map, dict):
            for option in self._attr_options:
                if option not in cloud_map:
                    continue
                try:
                    effective_map[option] = int(cloud_map[option])
                except (TypeError, ValueError):
                    continue

        return effective_map

    @property
    def device_info(self) -> dict:
        """Return device registry information for this integration."""
        return build_main_device_info(self.coordinator)
