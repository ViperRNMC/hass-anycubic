"""LAN transport; HTTP discovery + local MQTT."""
from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from .api import AnycubicAPI
from .mqtt import AnycubicMQTT
from ..tbase import AnycubicTransport
from .. import ErrorsSystem
_LOGGER = logging.getLogger(__name__)


class LanTransport(AnycubicTransport):
    """Connect to the printer directly via local MQTT after HTTP discovery."""

    def __init__(self, hass, host: str) -> None:
        self._hass = hass
        self._host = host
        self._api: AnycubicAPI | None = None
        self._mqtt: AnycubicMQTT | None = None
        self._current_creds: tuple[str, str] | None = None
        self._on_data: Callable[[dict], None] | None = None

    async def async_setup(self, on_data: Callable[[dict], None]) -> None:
        self._on_data = on_data
        self._api = AnycubicAPI(self._host)
        data = await self._hass.async_add_executor_job(self._api.discover)
        self._current_creds = (data["username"], data["password"])
        await self._init_mqtt(data)

    async def async_refresh_credentials(self) -> None:
        """Re-discover and update MQTT credentials if they changed."""
        if not self._api:
            return
        try:
            data = await self._hass.async_add_executor_job(self._api.discover)
        except Exception as err:
            _LOGGER.debug("LAN credential refresh failed: %s", err)
            return
        creds = (data["username"], data["password"])
        if creds != self._current_creds:
            self._current_creds = creds
            if self._mqtt:
                self._mqtt.client.username_pw_set(*creds)
                await self._hass.async_add_executor_job(self._mqtt.client.reconnect)

    async def _init_mqtt(self, data: dict) -> None:
        match = re.match(r"mqtts?://([^:]+):(\d+)", data["broker"])
        if not match:
            raise ValueError(ErrorsSystem.lan_invalid_broker_url.format(data['broker']))
        broker = match.group(1)
        port = int(match.group(2))
        self._mqtt = AnycubicMQTT(
            self._hass,
            broker,
            port,
            data["username"],
            data["password"],
            data["modeId"],
            data["deviceId"],
        )
        self._mqtt.on_update = self._on_data
        await self._hass.async_add_executor_job(self._mqtt.connect)

    async def async_send_command(self, msg_type: str, action: str, data: Any = None) -> None:
        if not self._mqtt:
            _LOGGER.debug("LAN send_command: MQTT not ready (%s/%s)", msg_type, action)
            return

        if msg_type == "print" and action in ("setPrintSpeedMode", "setNozzleTemp", "setHotbedTemp"):
            settings: dict[str, Any] = {}
            if action == "setPrintSpeedMode":
                settings["print_speed_mode"] = int((data or {}).get("print_speed_mode", 0))
            elif action == "setNozzleTemp":
                settings["target_nozzle_temp"] = int((data or {}).get("target_nozzle_temp", 0))
            elif action == "setHotbedTemp":
                settings["target_hotbed_temp"] = int((data or {}).get("target_hotbed_temp", 0))

            payload = {
                "type": "print",
                "action": "update",
                "data": {"taskid": "-1", "settings": settings},
            }
            self._mqtt.publish_json(self._mqtt.web_topic("print"), payload)
            return

        if msg_type == "fan" and action == "auto":
            payload = {
                "type": "fan",
                "action": "auto",
                "data": data or {},
            }
            self._mqtt.publish_json(self._mqtt.printer_topic("fan"), payload)
            return

        payload: dict[str, Any] = {"type": msg_type, "action": action}
        if data is not None:
            payload["data"] = data
        topic = self._mqtt.web_topic(msg_type)
        self._mqtt.publish_json(topic, payload)

    async def async_query_topic(self, topic: str, action: str = "query") -> None:
        if not self._mqtt:
            return
        payload: dict[str, Any] = {
            "type": topic,
            "action": action,
            "timestamp": int(time.time() * 1000),
            "msgid": str(uuid.uuid4()),
            "data": None,
        }
        self._mqtt.publish_json(self._mqtt.web_topic(topic), payload)

    async def async_teardown(self) -> None:
        if self._mqtt:
            try:
                disconnect = getattr(self._mqtt, "disconnect", None)
                if callable(disconnect):
                    disconnect()
            except Exception:
                pass
            self._mqtt = None

    @property
    def mqtt(self) -> AnycubicMQTT | None:
        """Expose raw MQTT client (used by camera platform)."""
        return self._mqtt

    async def async_open_camera_stream(self) -> str | None:
        """Return the LAN HTTP-FLV stream URL for this printer."""
        return f"http://{self._host}:18088/flv"
