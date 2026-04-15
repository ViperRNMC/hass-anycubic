"""Camera platform with a hardcoded stream URL for debugging.

This minimal camera always exposes the configured URL as the stream source
and provides a small probe that fetches the first bytes and logs response
metadata so you can debug connectivity and initial stream traffic.
"""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime
import asyncio
from homeassistant.components.ffmpeg import async_get_image as ffmpeg_async_get_image

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CAMERA_NAME, VIDEO_KEY
from .helper.device_info import build_main_device_info

_LOGGER = logging.getLogger(__name__)

# Hardcoded stream URL for testing — change to your working URL if needed.
DEFAULT_STREAM_URL: str = "http://10.0.3.246:18088/flv"


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator not found for camera setup: %s", entry.entry_id)
        return

    async_add_entities([AnycubicCamera(coordinator)])


class AnycubicCamera(CoordinatorEntity, Camera):
    """Camera entity exposing a hardcoded stream URL and probe/debug info."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        Camera.__init__(self)

        self._attr_name = CAMERA_NAME
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_camera"
        self._attr_has_entity_name = True
        self._attr_supported_features = CameraEntityFeature.STREAM
        self._attr_icon = "mdi:camera"

        # last probe results
        self._last_probe: dict[str, Any] = {}
        self._access_count = 0
        # cache last provided URL to avoid noisy repeated logs
        self._last_provided_url: str | None = None
        # prevent concurrent probe/start tasks which can race and cause
        # subprocess stream-reading issues in asyncio
        self._probe_lock = asyncio.Lock()
        # Flag to indicate we are in the process of creating/opening a stream
        self._creating_stream: bool = False

    @property
    def available(self) -> bool:
        # Avoid awaiting in property; return True if we have a configured
        # hardcoded URL or a previously cached provided URL.
        return bool(DEFAULT_STREAM_URL or self._last_provided_url)

    async def stream_source(self) -> str | None:
        """Return the stream URL (async) as Home Assistant expects a coroutine.

        Previous implementation used a property returning a string. HA calls
        `await camera.stream_source()` when creating streams, so expose an
        async callable to avoid TypeError: 'str' object is not callable.
        """
        # Hardcoded URL for quick testing
        if DEFAULT_STREAM_URL:
            # Only log when the provided URL changes to reduce spam
            if self._last_provided_url != DEFAULT_STREAM_URL:
                _LOGGER.info("Providing hardcoded stream URL: %s", DEFAULT_STREAM_URL)
                self._last_provided_url = DEFAULT_STREAM_URL
            return DEFAULT_STREAM_URL
        return None

    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        # We don't fetch still images; return None
        return None

    async def async_get_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """Return a single-frame PNG image using the FFmpeg helper.

        This uses Home Assistant's ffmpeg integration to request a single
        frame from the configured stream. If FFmpeg is not available or
        the stream is unreachable, this returns None.
        """
        url = await self.stream_source()
        if not url:
            _LOGGER.debug("No stream URL available for ffmpeg snapshot")
            return None
        # If we're currently creating/opening a stream, avoid launching
        # ffmpeg for a snapshot to prevent subprocess/read races with the
        # stream worker.
        if self._creating_stream:
            _LOGGER.debug("Skipping ffmpeg snapshot while stream is being created")
            return None

        # Serialize ffmpeg/subprocess access to avoid concurrent reads which
        # can raise RuntimeError when multiple coroutines read subprocess pipes
        # at the same time.
        async with self._probe_lock:
            try:
                # async_get_image returns PNG bytes or None
                image = await ffmpeg_async_get_image(self.hass, url, input_args=None)
                if image:
                    _LOGGER.debug("FFmpeg snapshot captured (%d bytes)", len(image))
                else:
                    _LOGGER.debug("FFmpeg snapshot returned no data")
                return image
            except Exception as err:  # pragma: no cover - defensive
                _LOGGER.exception("FFmpeg snapshot failed for %s: %s", url, err)
                return None

    async def async_start_stream(self) -> bool:
        """Probe the stream URL to fetch first bytes and log metadata.

        This helps debugging whether the stream is reachable and what the
        initial response headers/content look like. It does NOT attempt to
        transcode or maintain the stream.
        """
        url = await self.stream_source()
        if not url:
            _LOGGER.warning("No stream URL configured to start")
            return False
        # ensure only one probe runs at a time
        async with self._probe_lock:
            # count probes and log attempt
            self._access_count += 1
            _LOGGER.info("Probing stream URL (attempt #%d): %s", self._access_count, url)
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(url, timeout=10) as resp:
                    status = resp.status
                    ctype = resp.headers.get("Content-Type")
                    # read a small chunk of bytes to inspect the stream header
                    chunk = await resp.content.read(1024)
                    self._last_probe = {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "status": "ok" if 200 <= status < 400 else "error",
                        "status_code": status,
                        "content_type": ctype,
                        "bytes_peeked": len(chunk),
                    }
                    _LOGGER.info(
                        "Probe result: status=%s code=%s content_type=%s bytes=%d",
                        self._last_probe["status"],
                        status,
                        ctype,
                        len(chunk),
                    )
                    # Optionally log a short hexdump or text preview (safeguard size)
                    preview = chunk[:256]
                    try:
                        _LOGGER.debug("Stream preview (first %d bytes): %s", len(preview), preview)
                    except Exception:
                        _LOGGER.debug("Stream preview binary (non-printable)")
                    return True
            except Exception as err:
                self._last_probe = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "status": "exception",
                    "error": str(err),
                }
                _LOGGER.exception("Failed to probe stream URL %s: %s", url, err)
                return False
        

    def turn_on(self) -> None:
        """Sync entrypoint called by HA camera.turn_on service.

        Schedule the async probe to run in the event loop so the service
        doesn't raise NotImplementedError and the probe runs from the HA host.
        """
        try:
            # Schedule a task that requests the device to startCapture and then probes
            asyncio.run_coroutine_threadsafe(self._async_request_start_and_probe(), self.hass.loop)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.exception("Failed to schedule async_start_stream: %s", err)

    def turn_off(self) -> None:
        """Sync entrypoint called by HA camera.turn_off service.

        Schedule the async stop operation; this is a no-op for the hardcoded
        stream but kept for symmetry and future extension.
        """
        try:
            asyncio.run_coroutine_threadsafe(self.async_stop_stream(), self.hass.loop)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.exception("Failed to schedule async_stop_stream: %s", err)

    async def _async_request_start_and_probe(self) -> None:
        """Request device to startCapture then run the probe.

        Some devices only begin streaming after a startCapture command; we
        publish that request using the coordinator helper and then probe the
        configured URL.
        """
        try:
            _LOGGER.info("Requesting device to startCapture before probing")
            # Ask the device to start publishing the stream (non-blocking)
            try:
                await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
            except Exception as err:  # pragma: no cover - defensive
                _LOGGER.debug("Failed to send startCapture via coordinator: %s", err)

            # Give the device a short moment to begin streaming, then probe
            await asyncio.sleep(0.5)
            await self.async_start_stream()
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.exception("Error while requesting startCapture and probing: %s", err)

    async def async_stop_stream(self) -> bool:
        # Nothing to stop for a hardcoded external stream; just log
        _LOGGER.info("Stop stream requested (no-op for hardcoded URL)")
        return True

    async def async_create_stream(self):
        """Ensure device is publishing before Home Assistant opens the stream.

        We request startCapture via the coordinator and wait a short period
        while holding the probe lock to avoid concurrent subprocess/read
        races. After the device had a moment to begin streaming we delegate
        to the base Camera implementation which will start HA's stream
        worker (ffmpeg) to open the stream URL.
        """
        # Mark that stream creation is in progress to prevent snapshots
        # from racing with the stream worker.
        self._creating_stream = True
        try:
            # Ensure only one start request happens at a time
            async with self._probe_lock:
                try:
                    _LOGGER.info("async_create_stream: requesting startCapture before stream open")
                    try:
                        await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
                    except Exception as err:  # pragma: no cover - defensive
                        _LOGGER.debug("Failed to send startCapture via coordinator: %s", err)

                    # Give device a short moment to start serving the stream
                    await asyncio.sleep(0.7)
                except Exception as err:  # pragma: no cover - defensive
                    _LOGGER.exception("Error preparing stream: %s", err)

            # Call base implementation to actually create the stream endpoint
            return await super().async_create_stream()
        finally:
            self._creating_stream = False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        # Expose a sync stream_url for state attributes. Use cached provided
        # URL if available, otherwise fall back to the hardcoded default.
        attrs["stream_url"] = self._last_provided_url or DEFAULT_STREAM_URL
        attrs["last_probe"] = self._last_probe
        attrs["probe_access_count"] = self._access_count
        return attrs

    @property
    def device_info(self) -> dict:
        return build_main_device_info(self.coordinator)
