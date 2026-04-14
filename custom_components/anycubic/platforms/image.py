"""Image platform exposing print job preview thumbnails."""
from __future__ import annotations

import base64
import logging

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..helper.device_info import build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator not found for image setup: %s", entry.entry_id)
        return
    async_add_entities([AnycubicJobPreviewImage(coordinator)])


class AnycubicJobPreviewImage(CoordinatorEntity, ImageEntity):
    """Job preview image based on thumbnail data in coordinator payloads."""

    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_name = "Print Preview"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_job_preview"
        self._attr_has_entity_name = True
        self._attr_image_last_updated = dt_util.utcnow()
        self._last_image_url: str | None = None

    def _get_image_url(self) -> str | None:
        """Return current image URL from coordinator data."""
        return (
            ((self.coordinator.data.get("print") or {}).get("data") or {}).get("image_url")
        )

    def _handle_coordinator_update(self) -> None:
        """Bump image_last_updated when the URL changes so HA re-fetches the image."""
        url = self._get_image_url()
        if url and url != self._last_image_url:
            self._last_image_url = url
            self._attr_image_last_updated = dt_util.utcnow()
            _LOGGER.debug("Job preview URL updated: %s", url)
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        # 1. Try file thumbnail (LAN path)
        file_data = (self.coordinator.data.get("file") or {}).get("data") or {}
        details = file_data.get("file_details") or {}
        thumbnail = details.get("thumbnail")
        if thumbnail:
            if isinstance(thumbnail, str) and thumbnail.startswith(("http://", "https://")):
                return await self._async_fetch_image(thumbnail)
            try:
                encoded = str(thumbnail)
                if "," in encoded and encoded.split(",", 1)[0].startswith("data:"):
                    encoded = encoded.split(",", 1)[1]
                padded = encoded + ("=" * (-len(encoded) % 4))
                return base64.b64decode(padded)
            except Exception:
                _LOGGER.debug("Failed to decode job preview thumbnail", exc_info=True)

        # 2. Try image_url from print data (cloud path)
        image_url = self._get_image_url()
        if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
            return await self._async_fetch_image(image_url)

        return None

    async def _async_fetch_image(self, url: str) -> bytes | None:
        import aiohttp
        session = async_get_clientsession(self.coordinator.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Job preview fetch failed status=%s url=%s", resp.status, url)
                    return None
                return await resp.read()
        except Exception:
            _LOGGER.debug("Failed to fetch job preview image from %s", url, exc_info=True)
            return None

    @property
    def device_info(self) -> dict:
        return build_main_device_info(self.coordinator)
