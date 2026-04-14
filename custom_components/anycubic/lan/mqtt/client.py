"""LAN MQTT client for Anycubic printers."""

from __future__ import annotations

import json
import logging
import ssl

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AnycubicMQTT:
    """MQTT wrapper for printer updates and command publishing."""

    def __init__(
        self,
        hass: HomeAssistant,
        broker: str,
        port: int,
        username: str,
        password: str,
        mode_id: str,
        device_id: str,
        on_update=None,
    ):
        self.hass = hass
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.mode_id = mode_id
        self.device_id = device_id
        self.on_update = on_update
        self.debug_logging = False

        self.state = {}
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def set_debug_logging(self, enabled: bool) -> None:
        """Enable or disable debug logging of MQTT messages."""
        self.debug_logging = enabled

    def connect(self):
        """Connect to broker and start background loop."""
        self.client.username_pw_set(self.username, self.password)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        _LOGGER.debug("Connecting to MQTT broker %s:%s", self.broker, self.port)
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def disconnect(self):
        """Stop loop and disconnect."""
        self.client.loop_stop()
        self.client.disconnect()
        _LOGGER.info("Disconnected from MQTT broker")

    def publish_json(self, topic: str, payload: dict, qos: int = 0, retain: bool = False) -> None:
        """Publish JSON payload in thread-safe way."""
        if self.debug_logging:
            _LOGGER.debug("MQTT Publish: %s -> %s", topic, json.dumps(payload))
        self.hass.loop.call_soon_threadsafe(
            self.client.publish,
            topic,
            json.dumps(payload),
            qos,
            retain,
        )

    def printer_topic(self, endpoint: str) -> str:
        return f"anycubic/anycubicCloud/v1/printer/public/{self.mode_id}/{self.device_id}/{endpoint}"

    def web_topic(self, endpoint: str) -> str:
        return f"anycubic/anycubicCloud/v1/web/printer/{self.mode_id}/{self.device_id}/{endpoint}"

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker %s:%s", self.broker, self.port)
        else:
            _LOGGER.warning("Failed to connect to MQTT broker %s:%s (rc=%s)", self.broker, self.port, rc)

        topic = self.printer_topic("#")
        client.subscribe(topic)
        _LOGGER.debug("Subscribed to topic: %s", topic)

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)
            if self.debug_logging:
                _LOGGER.debug("MQTT Message: %s -> %s", msg.topic, payload)

            if "type" in data:
                self.state[data["type"]] = data
                if self.on_update:
                    self.hass.loop.call_soon_threadsafe(self.on_update, self.state)

        except Exception as exc:
            _LOGGER.error("Error processing MQTT message: %s", exc)
