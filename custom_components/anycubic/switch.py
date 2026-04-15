"""Clean generic switch platform for Anycubic Ace Pro features.

One class `AnycubicSwitch` is driven by `SWITCH_DEFINITIONS` in `const.py`.
Supports passing optional parameters for setDry (target_temp, duration).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    MULTI_COLOR_BOX_KEY,
    SWITCH_DEFINITIONS,
    DEVICE_TYPE_ACE_PRO,
    DEVICE_TYPE_EXTFILBOX,
)
from .helper.device_info import (
    build_ace_device_info,
    build_extfilbox_device_info,
    build_main_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator for %s not found", entry.entry_id)
        return

    # Force-fetch multiColorBox data so switches have initial state. If MQTT
    # isn't ready, async_get_boxes will fall back to cached boxes (or empty).
    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("Coordinator async_get_boxes failed; falling back to cached boxes")

    entities: list[SwitchEntity] = []
    # Expand per-box switch templates using coordinator information
    expanded_switches = coordinator.expand_definitions(SWITCH_DEFINITIONS)
    for d in expanded_switches:
        if d.get("device_type") == DEVICE_TYPE_ACE_PRO:
            box_id = d.get("box_id")
            entities.append(AnycubicSwitch(coordinator, box_id, d))
        else:
            # non-boxed switches (if any)
            entities.append(AnycubicSwitch(coordinator, None, d))

    # If no boxes were available, wait for boxes_updated and create per-box switches
    if not boxes:
        def _on_boxes_updated(boxes_list):
            expanded = coordinator.expand_definitions(SWITCH_DEFINITIONS)
            new_entities: list[SwitchEntity] = []
            for d in expanded:
                if d.get("device_type") == DEVICE_TYPE_ACE_PRO:
                    box_id = d.get("box_id")
                    new_entities.append(AnycubicSwitch(coordinator, box_id, d))
                else:
                    new_entities.append(AnycubicSwitch(coordinator, None, d))
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

        unsub = async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)

    async_add_entities(entities)


class AnycubicSwitch(CoordinatorEntity, SwitchEntity):
    """Generic switch created from a SWITCH_DEFINITIONS entry for a box."""

    def __init__(self, coordinator, box_id: int, definition: dict):
        super().__init__(coordinator)
        self.box_id = box_id
        self.definition = definition
        self._key = definition["key"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_has_entity_name = True
        self._box_id: Optional[int] = definition.get("box_id")

    def _render_template(self, template: dict, **params) -> dict:
        s = json.dumps(template)
        s = s.replace("{box_id}", str(self.box_id))
        # support optional params like target_temp and duration
        for k, v in params.items():
            s = s.replace(f"{{{k}}}", str(v))
        return json.loads(s)

    async def _publish(self, action: str, data: dict) -> None:
        try:
            await self.coordinator.async_send_command(self.definition.get("type"), action, data)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Command publish failed for switch %s: %s", self._key, err)

    def _find_box(self) -> dict | None:
        boxes = self.coordinator.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if b.get("id") == self.box_id:
                return b
        return None

    @property
    def is_on(self) -> bool:
        box = self._find_box()
        if not box:
            return False
        key = self.definition.get("key")
        # support both base keys (ace_pro_drying) and expanded keys (ace_pro_drying_0)
        if key and "drying" in key:
            ds = box.get("drying_status", {})
            return bool(ds.get("status") == 1)
        if key and ("auto_feed" in key or "autofeed" in key):
            return bool(box.get("auto_feed") == 1)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        # For drying we allow passing `target_temp` and `duration` in kwargs
        params = {}
        if "target_temp" in kwargs:
            params["target_temp"] = kwargs.get("target_temp")
        if "duration" in kwargs:
            params["duration"] = kwargs.get("duration")

        key = self.definition.get("key")
        if key and "drying" in key:
            box = self._find_box() or {}
            drying_status = box.get("drying_status") or {}

            if params.get("target_temp") is None:
                target_temp = drying_status.get("target_temp")
                try:
                    params["target_temp"] = int(target_temp)
                except (TypeError, ValueError):
                    params["target_temp"] = 35

            if params.get("duration") is None:
                duration = drying_status.get("duration")
                try:
                    params["duration"] = int(duration)
                except (TypeError, ValueError):
                    params["duration"] = 1

        data_template = self.definition.get("data_template_on") or {}
        data = self._render_template(data_template, **params)
        action = self.definition.get("action_on")
        await self._publish(action, data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        data_template = self.definition.get("data_template_off") or {}
        data = self._render_template(data_template)
        action = self.definition.get("action_off")
        await self._publish(action, data)

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {}
        box = self._find_box()
        if not box:
            return attrs
        key = self.definition.get("key")
        if key and "drying" in key:
            ds = box.get("drying_status", {})
            attrs["drying_status"] = ds.get("status")
            # Expose both legacy and simple attribute names for compatibility
            attrs["drying_target_temp"] = ds.get("target_temp")
            attrs["target_temp"] = ds.get("target_temp")
            attrs["drying_duration"] = ds.get("duration")
            attrs["duration"] = ds.get("duration")
        if key and ("auto_feed" in key or "autofeed" in key):
            attrs["auto_feed"] = box.get("auto_feed")
        return attrs

    @property
    def device_info(self) -> dict:
        """Get device info based on sensor definition device type."""
        dt = self.definition.get("device_type")

        if dt == DEVICE_TYPE_ACE_PRO:
            return build_ace_device_info(self.coordinator, int(self.box_id))
        elif dt == DEVICE_TYPE_EXTFILBOX:
            return build_extfilbox_device_info(self.coordinator)
        else:
            return build_main_device_info(self.coordinator)

    def _find_box_by_id(self, top_level_data: dict, box_id: int) -> Optional[dict]:
        """Find a multicolor box by its `id` field inside coordinator data.

        top_level_data is the dict under MULTI_COLOR_BOX_KEY (e.g. coordinator.data[MULTI_COLOR_BOX_KEY]).
        """
        boxes = top_level_data.get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if b.get("id") == box_id:
                return b
        return None