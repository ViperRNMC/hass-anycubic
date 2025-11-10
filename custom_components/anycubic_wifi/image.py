
import base64
import logging
import io
import tempfile
import ffmpeg

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
        if not thumb_b64:
            return None
        try:
            flv_bytes = base64.b64decode(thumb_b64)
        except Exception:
            _LOGGER.warning("Could not decode thumbnail base64")
            return None

        # Convert FLV to PNG using ffmpeg
        try:
            with tempfile.NamedTemporaryFile(suffix=".flv") as flv_file, tempfile.NamedTemporaryFile(suffix=".png") as png_file:
                flv_file.write(flv_bytes)
                flv_file.flush()
                (
                    ffmpeg
                    .input(flv_file.name)
                    .output(png_file.name, vframes=1, format='png')
                    .run(capture_stdout=True, capture_stderr=True)
                )
                png_file.seek(0)
                return png_file.read()
        except Exception as e:
            _LOGGER.error(f"Failed to convert FLV to PNG: {e}")
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
