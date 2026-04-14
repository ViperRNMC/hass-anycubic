"""Camera platform with FLV to RTSP conversion and MQTT control.

This camera platform:
- Converts FLV stream (18088/flv) to RTSP via embedded ffmpeg restreamer
- Provides snapshots via ffmpeg
- Controls camera via MQTT startCapture/stopCapture commands
- Integrates with Home Assistant stream component for HLS playback
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, CAMERA_NAME, VIDEO_KEY

_LOGGER = logging.getLogger(__name__)

# FLV source URL (printer streams FLV on this port)
FLV_SOURCE_URL: str = "http://10.0.3.246:18088/flv"

# RTSP restreamer config (local conversion from FLV → RTSP)
RTSP_LISTEN_PORT: int = 8554
RTSP_STREAM_PATH: str = "/live"
RTSP_SERVER_URL: str = f"rtsp://127.0.0.1:{RTSP_LISTEN_PORT}{RTSP_STREAM_PATH}"

# Ffmpeg configuration for FLV→RTSP restreaming
FFMPEG_RESTREAMER_ARGS = [
    "ffmpeg",
    "-rtbufsize", "32M",  # FLV buffer
    "-fflags", "nobuffer",
    "-flags", "low_delay",
    "-i", FLV_SOURCE_URL,
    "-c:v", "libx264",
    "-preset", "ultrafast",  # Minimal latency
    "-tune", "zerolatency",
    "-f", "rtsp",
    RTSP_SERVER_URL,
]

# Snapshot capture timeout
SNAPSHOT_TIMEOUT: int = 10


class RTSPRestreamer:
    """Manages FLV to RTSP conversion process."""

    def __init__(self, hass):
        self.hass = hass
        self.process: subprocess.Popen | None = None
        self.is_running = False

    def start(self) -> bool:
        """Start ffmpeg FLV→RTSP restreamer."""
        if self.is_running:
            _LOGGER.debug("RTSP restreamer already running")
            return True

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            _LOGGER.error("ffmpeg not found; cannot start RTSP restreamer")
            return False

        try:
            _LOGGER.info("Starting RTSP restreamer: FLV → RTSP on port %d", RTSP_LISTEN_PORT)
            self.process = subprocess.Popen(
                FFMPEG_RESTREAMER_ARGS,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,  # Create new process group
            )
            self.is_running = True
            _LOGGER.info("RTSP restreamer started (PID: %d)", self.process.pid)
            return True
        except Exception as err:
            _LOGGER.error("Failed to start RTSP restreamer: %s", err)
            self.is_running = False
            return False

    def stop(self) -> None:
        """Stop ffmpeg restreamer."""
        if not self.is_running or not self.process:
            return

        try:
            _LOGGER.info("Stopping RTSP restreamer (PID: %d)", self.process.pid)
            # Kill process group (all children)
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            self.process.wait(timeout=5)
            _LOGGER.info("RTSP restreamer stopped")
        except subprocess.TimeoutExpired:
            _LOGGER.warning("RTSP restreamer did not stop gracefully, killing...")
            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
        except Exception as err:
            _LOGGER.error("Error stopping RTSP restreamer: %s", err)
        finally:
            self.process = None
            self.is_running = False


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up camera entity and RTSP restreamer."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("Coordinator not found for camera setup: %s", entry.entry_id)
        return

    try:
        # Create and start RTSP restreamer
        restreamer = RTSPRestreamer(hass)
        if not restreamer.start():
            _LOGGER.warning("Failed to start RTSP restreamer, camera may not work")

        camera = AnycubicCamera(coordinator, restreamer)
        async_add_entities([camera])
        _LOGGER.debug("Camera entity created and added")
    except Exception:
        _LOGGER.exception("Failed to create camera entity")


class AnycubicCamera(CoordinatorEntity, Camera):
    """Camera entity with FLV→RTSP conversion and MQTT control."""

    def __init__(self, coordinator, restreamer: RTSPRestreamer):
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_name = CAMERA_NAME
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_camera"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:camera"
        self.restreamer = restreamer

        # Locks for stream operations
        self._stream_lock = asyncio.Lock()
        self._is_streaming = False

        _LOGGER.info("AnycubicCamera initialized with RTSP restreamer")

    @property
    def available(self) -> bool:
        """Camera available if restreamer is running."""
        return self.restreamer.is_running

    @property
    def device_info(self) -> dict:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": f"{MANUFACTURER} {MODEL}",
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def frontend_stream_type(self) -> str:
        """Return frontend stream type (HLS via HA stream integration)."""
        return "hls"

    async def async_added_to_hass(self) -> None:
        """Set up entity when added to HA."""
        await super().async_added_to_hass()
        _LOGGER.info("Camera entity '%s' added to Home Assistant", self._attr_name)

    async def stream_source(self) -> str | None:
        """Return RTSP stream URL and trigger startCapture."""
        async with self._stream_lock:
            if not self.restreamer.is_running:
                _LOGGER.error("RTSP restreamer not running")
                return None

            _LOGGER.info("Stream source requested; sending startCapture to device")
            try:
                await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
                self._is_streaming = True
            except Exception as err:
                _LOGGER.error("Failed to send startCapture: %s", err)

            _LOGGER.debug("Returning RTSP stream URL: %s", RTSP_SERVER_URL)
            return RTSP_SERVER_URL

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """Return JPEG snapshot from FLV stream.
        
        Sends startCapture MQTT command first to activate printer camera,
        then captures snapshot after brief delay.
        """
        _LOGGER.debug("Snapshot requested (width=%s, height=%s)", width, height)
        
        # Send startCapture command to activate printer camera
        try:
            _LOGGER.debug("Sending startCapture to activate printer camera for snapshot")
            await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
            # Give camera time to start streaming
            await asyncio.sleep(1)
        except Exception as err:
            _LOGGER.warning("Failed to send startCapture before snapshot: %s", err)
            # Continue anyway; camera might already be streaming
        
        return await self.hass.async_add_executor_job(self._capture_snapshot)

    def _capture_snapshot(self) -> bytes | None:
        """Capture JPEG snapshot directly from FLV stream via ffmpeg."""
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            _LOGGER.error("ffmpeg not found for snapshot capture")
            return None

        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(prefix="anycubic_snapshot_", suffix=".jpg", delete=False) as tf:
                tmp_file = tf.name

            # Capture directly from FLV source (FLV_SOURCE_URL) instead of relying on RTSP restreamer
            cmd = [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-i", FLV_SOURCE_URL,
                "-vframes", "1",
                "-q:v", "2",
                tmp_file,
            ]

            _LOGGER.debug("Capturing snapshot from FLV source: %s (timeout %ds)", FLV_SOURCE_URL, SNAPSHOT_TIMEOUT)
            result = subprocess.run(cmd, capture_output=True, timeout=SNAPSHOT_TIMEOUT, check=False)

            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace').strip()
                stdout = result.stdout.decode('utf-8', errors='replace').strip()
                error_msg = stderr or stdout or "(no error output)"
                _LOGGER.error("Snapshot capture failed (exit %d): %s", result.returncode, error_msg[:500])
                return None

            with open(tmp_file, "rb") as f:
                data = f.read()

            if data:
                _LOGGER.debug("Snapshot captured (%d bytes) from FLV source", len(data))
                return data
            else:
                _LOGGER.error("Snapshot file is empty")
                return None

        except subprocess.TimeoutExpired:
            _LOGGER.error("Snapshot capture timed out after %ds", SNAPSHOT_TIMEOUT)
            return None
        except Exception as err:
            _LOGGER.exception("Error capturing snapshot: %s", err)
            return None
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    async def async_turn_on(self) -> None:
        """Turn on camera (start streaming)."""
        try:
            await self.coordinator.async_query_topic(VIDEO_KEY, action="startCapture")
            self._is_streaming = True
            _LOGGER.info("Camera turned on (startCapture sent)")
        except Exception as err:
            _LOGGER.error("Failed to turn on camera: %s", err)

    async def async_turn_off(self) -> None:
        """Turn off camera (stop streaming)."""
        try:
            await self.coordinator.async_query_topic(VIDEO_KEY, action="stopCapture")
            self._is_streaming = False
            _LOGGER.info("Camera turned off (stopCapture sent)")
        except Exception as err:
            _LOGGER.error("Failed to turn off camera: %s", err)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "stream_url": RTSP_SERVER_URL,
            "flv_source": FLV_SOURCE_URL,
            "is_streaming": self._is_streaming,
        }

