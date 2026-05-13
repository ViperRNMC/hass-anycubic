"""Update platform for Anycubic -- triggers cloud OTA installs via MQTT."""
from __future__ import annotations

from typing import Any
import logging

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .definitions import UPDATE_DEFINITIONS
from .helper.device_info import build_ace_device_info, build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return

    entities: list[UpdateEntity] = []

    # Try to fetch boxes so per-box entities are present at setup
    try:
        boxes = await coordinator.async_get_boxes()
    except Exception:
        boxes = coordinator.get_boxes()
        _LOGGER.debug("update setup: async_get_boxes failed; falling back to cached boxes")

    _LOGGER.debug("update setup: found %d boxes at setup", len(boxes) if boxes is not None else 0)

    # Build entities from definitions so per-box expansion matches other platforms
    expanded = coordinator.expand_definitions(UPDATE_DEFINITIONS)

    # Track whether we've added the printer-level entity to avoid duplicates
    printer_added = False
    for d in expanded:
        device_type = d.get("device_type")
        if device_type == "ace_pro":
            box_id = d.get("box_id")
            if box_id is None:
                continue
            try:
                entities.append(AnycubicBoxUpdateEntity(coordinator, int(box_id)))
            except Exception:
                _LOGGER.exception("Failed to create ACE box update entity for %s", d)
        else:
            if not printer_added:
                try:
                    entities.append(AnycubicPrinterUpdateEntity(coordinator))
                    printer_added = True
                except Exception:
                    _LOGGER.exception("Failed to create printer update entity")

    if entities:
        _LOGGER.debug("update setup: creating %d update entities (expanded_defs total=%d)", len(entities), len(expanded))
        async_add_entities(entities)

    # If no boxes were available at setup, wait for boxes_updated and create per-box update entities
    if not boxes:
        def _on_boxes_updated(boxes_list):
            _LOGGER.debug("update listener: boxes_updated fired with %d boxes", len(boxes_list) if boxes_list else 0)
            expanded_l = coordinator.expand_definitions(UPDATE_DEFINITIONS)
            new_entities: list[UpdateEntity] = []
            for d in expanded_l:
                if d.get("box_id") is not None:
                    try:
                        new_entities.append(AnycubicBoxUpdateEntity(coordinator, int(d.get("box_id"))))
                    except Exception:
                        _LOGGER.exception("Failed to create per-box update entity from definition %s", d)
            if not new_entities:
                _LOGGER.debug("update listener: no new per-box update entities to add")
                return

            def _add_and_unsub():
                try:
                    _LOGGER.debug("update listener: adding %d per-box update entities", len(new_entities))
                    async_add_entities(new_entities)
                except Exception:
                    _LOGGER.exception("Failed to add per-box update entities")
                try:
                    unsub()
                except Exception:
                    pass

            coordinator.hass.loop.call_soon_threadsafe(_add_and_unsub)

        unsub = async_dispatcher_connect(coordinator.hass, f"{DOMAIN}_boxes_updated", _on_boxes_updated)


class AnycubicPrinterUpdateEntity(CoordinatorEntity, UpdateEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = ""
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_firmware"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:package"
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def entity_picture(self) -> str | None:
        return None

    @property
    def device_info(self) -> dict:
        return build_main_device_info(self.coordinator)

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.data.get("info", {}).get("data", {}).get("version")

    @property
    def latest_version(self) -> str | None:
        return self.coordinator.data.get("info", {}).get("data", {}).get("available_version")

    @property
    def in_progress(self) -> bool:
        # Best-effort: rely on info->data; printers expose progress via MQTT topics handled by transport.
        return bool(self.coordinator.data.get("info", {}).get("data", {}).get("updating", False))

    async def async_install(self, version: str, **kwargs: Any) -> None:
        # Trigger OTA update via cloud MQTT. The transport maps msg_type 'ota' to an MQTT publish.
        payload = {"version": version} if version else {}
        await self.coordinator.async_send_command("ota", "update", payload)


class AnycubicBoxUpdateEntity(CoordinatorEntity, UpdateEntity):
    def __init__(self, coordinator, box_id: int) -> None:
        super().__init__(coordinator)
        self.box_id = box_id
        
        self._cached_version: str | None = self._extract_firmware_from_coordinator()
        
        self._attr_name = ""
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_ace_box_{box_id}_firmware"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:package"
        self._attr_device_class = UpdateDeviceClass.FIRMWARE
        self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def entity_picture(self) -> str | None:
        return None

    def _extract_firmware_from_coordinator(self) -> str | None:
        """Extract firmware version from coordinator's multiColorBox data."""
        try:
            boxes = self.coordinator.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
            for b in boxes:
                if int(b.get("id", -1)) == self.box_id:
                    # Try multiple possible field names for firmware
                    for key in ("firmware", "firmware_version", "version"):
                        value = b.get(key)
                        if value and str(value).strip():
                            return str(value).strip()
            return None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    async def async_added_to_hass(self) -> None:
        """Ensure state is populated after entity is added."""
        await super().async_added_to_hass()
        
        # Immediately write the current state to Home Assistant
        # This prevents HA from caching "Unknown" before our data is available
        self.async_write_ha_state()
        
        # Then refresh coordinator to get latest data
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> dict:
        return build_ace_device_info(self.coordinator, self.box_id, firmware=self.installed_version)

    @property
    def installed_version(self) -> str | None:
        """Return installed firmware version from coordinator data."""
        version = self._extract_firmware_from_coordinator()
        if version:
            self._cached_version = version
            return version
        # Return cached version to preserve last-known state
        return self._cached_version

    @property
    def latest_version(self) -> str | None:
        boxes = self.coordinator.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if int(b.get("id", -1)) != self.box_id:
                continue
            # Only use explicit ACE firmware availability fields when present.
            for key in (
                "available_firmware",
                "available_firmware_version",
                "firmware_available",
                "latest_firmware",
                "latest_version",
            ):
                value = b.get(key)
                if value:
                    return str(value)
            # No update info available: return installed version so state is "Up-to-date"
            # instead of "Unknown" (HA sets Unknown when latest_version is None)
            return self.installed_version
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        # Box update progress is reported via MQTT and reflected in coordinator data if available.
        boxes = self.coordinator.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
        for b in boxes:
            if int(b.get("id", -1)) == self.box_id:
                return bool(b.get("updating", False) or b.get("downloading", False))
        return False

    async def async_install(self, version: str, **kwargs: Any) -> None:
        # Instruct ACE Pro box to update via MQTT. Include box id in payload.
        payload = {"version": version} if version else {}
        payload["box_id"] = int(self.box_id)
        await self.coordinator.async_send_command("ota", "update", payload)
