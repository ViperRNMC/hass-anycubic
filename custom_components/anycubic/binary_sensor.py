"""Binary sensors for the Anycubic integration.

This module creates binary sensors using definitions in
`custom_components.anycubic.const.BINARY_DEFINITIONS`.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_DEFINITIONS, DOMAIN, MSG_TRANSLATIONS
from .helper.device_info import build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up binary sensors for a config entry.

    Creates one entity per entry in `BINARY_DEFINITIONS`.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    entities: list[BinarySensorEntity] = []
    for definition in BINARY_DEFINITIONS:
        try:
            entities.append(AnycubicBinarySensorEntity(coordinator, definition))
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("Failed to create binary sensor from definition %s", definition)

    if entities:
        async_add_entities(entities)

    # Request print and temperature topics so sensors initialize quickly
    try:
        await coordinator.async_query_topic("print")
    except Exception:  # pragma: no cover - coordinator may not be ready
        _LOGGER.debug("Coordinator print query failed or MQTT not ready")
    try:
        await coordinator.async_query_topic("tempature")
    except Exception:  # pragma: no cover
        _LOGGER.debug("Coordinator tempature query failed or MQTT not ready")


class AnycubicBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Definition-driven binary sensor.

    Supported types:
    - print_problem: on when print.code != 200 or print.msg != 'done'
    - nozzle_heating / bed_heating: on when target > current (+ hysteresis)
    """

    def __init__(self, coordinator, definition: dict):
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition.get("key")
        self._attr_name = definition.get("name")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_has_entity_name = True

        # map entity category if provided
        category = definition.get("entity_category")
        if category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # map device class (string) to BinarySensorDeviceClass enum
        device_class = definition.get("device_class")
        if device_class:
            try:
                self._attr_device_class = getattr(BinarySensorDeviceClass, device_class.upper())
            except AttributeError:
                _LOGGER.warning("Unknown device_class '%s' for %s", device_class, self._key)

        # optional icon from definition
        icon = definition.get("icon")
        if icon:
            self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        dtype = self.definition.get("type")

        if dtype == "printer_online":
            info = (self.coordinator.data.get("info") or {}).get("data") or {}
            online = info.get("printer_online")
            if isinstance(online, bool):
                return online
            state = info.get("state")
            if isinstance(state, str):
                return state.strip().lower() not in {"offline", "disconnected", "unavailable"}
            if isinstance(state, (int, float)):
                return state > 0
            return bool(state)

        if dtype == "job_failed":
            print_data = (self.coordinator.data.get("print") or {}).get("data") or {}
            state = print_data.get("state")
            if state is None:
                state = ((self.coordinator.data.get("info") or {}).get("data") or {}).get("project", {}).get("state")
            state_txt = str(state).strip().lower() if state is not None else ""
            return any(token in state_txt for token in ("fail", "error", "abort", "cancel"))

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
            # heating if target noticeably greater than current
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
        """Return device registry information for this integration."""
        return build_main_device_info(self.coordinator)