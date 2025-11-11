import logging
from homeassistant.components.camera import Camera
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities([
        PrinterCameraEntity(coordinator),
    ])

class PrinterCameraEntity(Camera, CoordinatorEntity):
    def __init__(self, coordinator):
        super().__init__()
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "Camera"
        self._attr_unique_id = "printer_camera"
        _LOGGER.debug("Camera entity initialized")

    @property
    def stream_source(self):
        info = self.coordinator.data.get("info", {}).get("data", {})
        rtsp_url = info.get("urls", {}).get("rtspUrl")
        _LOGGER.debug("Camera stream_source called, RTSP URL: %s", rtsp_url)
        return rtsp_url
    def camera_image(self, width=None, height=None):
        """Return None for snapshot requests (stream-only camera)."""
        return None
    def __init__(self, coordinator):
        super().__init__()
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "Camera"
        self._attr_unique_id = "printer_camera"

    @property
    def stream_source(self):
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