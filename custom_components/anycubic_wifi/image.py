import base64
import logging

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnycubicDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    async_add_entities([
        AnycubicThumbnailImage(hass, coordinator),
    ])


class AnycubicThumbnailImage(ImageEntity, CoordinatorEntity):
    def __init__(self, hass: HomeAssistant, coordinator: AnycubicDataUpdateCoordinator):
        super().__init__(hass)
        super(CoordinatorEntity, self).__init__(coordinator)

        self._attr_name = "Anycubic Print Thumbnail"
        self._attr_unique_id = "anycubic_thumbnail_image"

    async def async_image(self):
        thumb_b64 = (
            self.coordinator.data.get("file", {})
            .get("data", {})
            .get("file_details", {})
            .get("thumbnail")
        )
        if thumb_b64:
            try:
                return base64.b64decode(thumb_b64)
            except Exception:
                _LOGGER.warning("Could not decode thumbnail base64")
        return None
    
    @property
    def device_info(self):
        info = self.coordinator.data.get("info", {}).get("data", {})
        return {
            "identifiers": {(DOMAIN, "anycubic_wifi")},
            "name": info.get("model", "Anycubic Printer"),
            "manufacturer": "Anycubic",
            "model": info.get("model", "Unknown"),
            "sw_version": info.get("version", "Unknown"),
        }
