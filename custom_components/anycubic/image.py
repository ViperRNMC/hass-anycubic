"""Image platform for Anycubic with LAN and Cloud support."""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera
from homeassistant.components.image import Image, ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .entity import AnycubicEntity
from .helper.mapper import printer_state_for_key
from .descriptions import get_descriptions
from .helper.connection_mode import get_entry_connection_mode
from .const import (
    CONNECTION_MODE_CLOUD,
    COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PrinterEntityType,
)
from .coordinator import AnycubicLanCoordinator

if TYPE_CHECKING:
    from .coordinator import AnycubicBackendCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnycubicImageEntityDescription(
    ImageEntityDescription
):
    """Describes Anycubic Cloud image entity."""
    printer_entity_type: PrinterEntityType | None = None


IMAGE_TYPES: list[AnycubicImageEntityDescription] = list([
    AnycubicImageEntityDescription(**item)
    for item in get_descriptions(CONNECTION_MODE_CLOUD, "image")
])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anycubic images for a config entry."""
    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD:
        await _setup_cloud_images(hass, entry, async_add_entities)
        return

    await _setup_lan_images(hass, entry, async_add_entities)


async def _setup_lan_images(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    async_add_entities(
        [
            AnycubicLanThumbnailImage(hass, coordinator),
            AnycubicLanCameraEntity(hass, coordinator),
        ]
    )


async def _setup_cloud_images(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AnycubicBackendCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR
    ]

    coordinator.add_entities_for_seen_printers(
        async_add_entities=async_add_entities,
        entity_constructor=AnycubicCloudImage,
        platform=Platform.IMAGE,
        available_descriptors=IMAGE_TYPES,
    )


class AnycubicLanCameraEntity(Camera, CoordinatorEntity):
    """Camera entity for LAN mode."""

    async def async_image(self):
        return b""

    def __init__(self, hass: HomeAssistant, coordinator: AnycubicLanCoordinator):
        super().__init__()
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "Camera"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_printer_camera"

    @property
    def stream_source(self):
        info = self.coordinator.data.get("info", {}).get("data", {})
        return info.get("urls", {}).get("rtspUrl")

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }


class AnycubicLanThumbnailImage(ImageEntity, CoordinatorEntity):
    """Thumbnail image entity for LAN mode."""

    def __init__(self, hass: HomeAssistant, coordinator: AnycubicLanCoordinator):
        super().__init__(hass)
        super(CoordinatorEntity, self).__init__(coordinator)
        self._attr_name = "Print Thumbnail"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_thumbnail_image"

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

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            _LOGGER.error("ffmpeg not found for thumbnail conversion")
            return None

        try:
            with tempfile.NamedTemporaryFile(suffix=".flv") as flv_file, tempfile.NamedTemporaryFile(
                suffix=".png"
            ) as png_file:
                flv_file.write(flv_bytes)
                flv_file.flush()

                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    flv_file.name,
                    "-vframes",
                    "1",
                    png_file.name,
                ]
                result = subprocess.run(cmd, capture_output=True, check=False)
                if result.returncode != 0:
                    _LOGGER.error("Failed to convert FLV to PNG: %s", result.stderr.decode("utf-8", errors="replace"))
                    return None

                png_file.seek(0)
                return png_file.read()
        except Exception as err:
            _LOGGER.error("Failed to convert FLV to PNG: %s", err)
            return None

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": self.coordinator.config_entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "entry_type": "service",
        }


class AnycubicCloudImage(AnycubicEntity, ImageEntity):
    """An image for Anycubic Cloud."""

    entity_description: AnycubicImageEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: AnycubicBackendCoordinator,
        printer_id: int,
        entity_description: AnycubicImageEntityDescription,
    ) -> None:
        super().__init__(hass, coordinator, printer_id, entity_description)
        ImageEntity.__init__(self, hass)
        self._known_image_url = None

    def _reset_cached_image(self) -> None:
        self._cached_image = None
        self._attr_image_last_updated = dt_util.utcnow()

    def _check_image_url(self) -> None:
        image_url = printer_state_for_key(self.coordinator, self._printer_id, self.entity_description.key)
        if self._known_image_url != image_url:
            self._reset_cached_image()
            self._known_image_url = image_url

    @property
    def image_url(self) -> str | None:
        return self._known_image_url

    @property
    def image_last_updated(self) -> datetime | None:
        return self._attr_image_last_updated

    async def _async_load_image_from_url(self, url: str) -> Image | None:
        if response := await self._fetch_url(url):
            return Image(content=response.content, content_type="image/png")
        return None

    async def async_image(self) -> bytes | None:
        self._check_image_url()
        return await ImageEntity.async_image(self)