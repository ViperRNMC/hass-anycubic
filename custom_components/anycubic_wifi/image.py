import os
import base64
import logging
import io
import tempfile


from homeassistant.components.image import ImageEntity
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnycubicDataUpdateCoordinator
from .helper.gcode_to_png import gcode_to_png

_LOGGER = logging.getLogger(__name__)

class AnycubicGcodePreviewImage(ImageEntity, CoordinatorEntity):
    def __init__(self, hass: HomeAssistant, coordinator: AnycubicDataUpdateCoordinator):
        super().__init__(hass)
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "G-code Preview"
        self._attr_unique_id = "anycubic_gcode_preview_image"

    async def async_image(self):
        gcode_path = self._get_gcode_path()
        png_path = os.path.join(tempfile.gettempdir(), "gcode_preview.png")
        if not gcode_path or not os.path.exists(gcode_path):
            return None
        try:
            gcode_to_png(gcode_path, png_path)
            with open(png_path, "rb") as f:
                return f.read()
        except Exception as e:
            _LOGGER.error(f"Failed to generate G-code preview: {e}")
            return None

    def _get_gcode_path(self):
        # Pas deze aan naar waar het G-code bestand staat in je coordinator/data
        return self.coordinator.data.get("file", {}).get("data", {}).get("file_details", {}).get("gcode_path")

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

import base64
import logging
import io
import tempfile
# import ffmpeg

from homeassistant.components.image import ImageEntity
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnycubicDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([
        AnycubicThumbnailImage(hass, coordinator),
        AnycubicCameraEntity(hass, coordinator)
    ])

class AnycubicCameraEntity(Camera, CoordinatorEntity):
    async def async_image(self):
        # Geeft een lege afbeelding terug, zodat HA niet crasht
        return b""
    def __init__(self, hass: HomeAssistant, coordinator: AnycubicDataUpdateCoordinator):
        super().__init__()
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "Camera"
        self._attr_unique_id = "printer_camera"

    @property
    def stream_source(self):
        # Get RTSP URL from printer info
        info = self.coordinator.data.get("info", {}).get("data", {})
        return info.get("urls", {}).get("rtspUrl")

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


class AnycubicThumbnailImage(ImageEntity, CoordinatorEntity):
    def __init__(self, hass: HomeAssistant, coordinator: AnycubicDataUpdateCoordinator):
        super().__init__(hass)
        super(CoordinatorEntity, self).__init__(coordinator)

        self._attr_name = "Print Thumbnail"
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
