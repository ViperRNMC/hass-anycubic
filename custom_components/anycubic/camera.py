"""Camera platform using unified LAN/Cloud transport stream flow."""

from __future__ import annotations

import logging
import asyncio
from typing import Any

from homeassistant.components.ffmpeg import async_get_image as ffmpeg_async_get_image

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CAMERA_NAME, VIDEO_KEY
from .helper.device_info import build_main_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator not found for camera setup: %s", entry.entry_id)
        return

    async_add_entities([AnycubicCameraEntity(coordinator)])


class AnycubicCameraEntity(CoordinatorEntity, Camera):
    """Camera entity backed by transport-provided stream URLs."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        Camera.__init__(self)

        self._attr_name = CAMERA_NAME
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_camera"
        self._attr_has_entity_name = True
        self._attr_supported_features = CameraEntityFeature.STREAM
        self._attr_icon = "mdi:camera"

        self._stream_url: str | None = None
        self._last_open_status: str = "idle"
        self._open_attempt_count = 0
        self._probe_lock = asyncio.Lock()
        self._creating_stream: bool = False

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        video_data = self._video_data()
        reason = video_data.get("stream_reason")
        if reason:
            return False
        return bool(video_data.get("stream_available", True))

    @property
    def supported_features(self) -> CameraEntityFeature:
        video_data = self._video_data()
        if not self.coordinator.last_update_success:
            return CameraEntityFeature(0)
        if video_data.get("stream_reason"):
            return CameraEntityFeature(0)
        if video_data.get("stream_available") is False:
            return CameraEntityFeature(0)
        return CameraEntityFeature.STREAM

    def _video_data(self) -> dict[str, Any]:
        video = self.coordinator.data.get("video", {}) if isinstance(self.coordinator.data, dict) else {}
        data = video.get("data", {}) if isinstance(video, dict) else {}
        return data if isinstance(data, dict) else {}

    async def _ensure_stream_source(self) -> str | None:
        video_data = self._video_data()
        if video_data.get("stream_reason"):
            self._last_open_status = f"blocked:{video_data.get('stream_reason')}"
            return None

        if self._stream_url:
            return self._stream_url

        self._open_attempt_count += 1
        stream_url = await self.coordinator.async_open_camera_stream()
        if stream_url:
            self._stream_url = stream_url
            self._last_open_status = "ok"
            _LOGGER.debug("Camera stream opened at %s", stream_url)
            return stream_url

        self._last_open_status = "unavailable"
        _LOGGER.debug("Camera stream open returned no URL")
        return None

    async def stream_source(self) -> str | None:
        return await self._ensure_stream_source()

    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        return None

    async def async_get_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        url = await self.stream_source()
        if not url:
            self._last_open_status = "snapshot_no_url"
            return None
        if self._creating_stream:
            self._last_open_status = "snapshot_skipped_while_creating"
            return None
        async with self._probe_lock:
            try:
                image = await ffmpeg_async_get_image(self.hass, url, input_args=None)
                self._last_open_status = "snapshot_ok" if image else "snapshot_empty"
                return image
            except Exception as err:  # pragma: no cover - defensive
                self._last_open_status = f"snapshot_error:{type(err).__name__}"
                _LOGGER.debug("FFmpeg snapshot failed for %s: %s", url, err)
                return None

    def turn_on(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._async_request_start_capture(), self.hass.loop)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to schedule camera turn_on: %s", err)

    def turn_off(self) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.async_stop_stream(), self.hass.loop)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to schedule camera turn_off: %s", err)

    async def _async_request_start_capture(self) -> None:
        try:
            await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
            await self._ensure_stream_source()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Camera startCapture request failed: %s", err)

    async def async_stop_stream(self) -> bool:
        try:
            await self.coordinator.async_query_topic(VIDEO_KEY, action="stopCapture")
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Camera stopCapture request failed: %s", err)
        return True

    async def async_create_stream(self):
        self._creating_stream = True
        try:
            async with self._probe_lock:
                try:
                    await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
                    await self._ensure_stream_source()
                except Exception as err:  # pragma: no cover - defensive
                    _LOGGER.debug("Error preparing camera stream: %s", err)
            return await super().async_create_stream()
        finally:
            self._creating_stream = False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        video_data = self._video_data()
        return {
            "stream_url": self._stream_url,
            "stream_status": self._last_open_status,
            "stream_open_attempts": self._open_attempt_count,
            "stream_reason": video_data.get("stream_reason"),
            "stream_available": video_data.get("stream_available"),
        }

    @property
    def device_info(self) -> dict:
        return build_main_device_info(self.coordinator)
