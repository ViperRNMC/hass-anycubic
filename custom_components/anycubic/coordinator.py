"""Coordinator for Anycubic integration data updates and MQTT handling."""
import asyncio
from datetime import timedelta
import inspect
import logging
import re
import time
import traceback
from typing import TYPE_CHECKING, Any, TypeVar
import copy
import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    MULTI_COLOR_BOX_KEY,
    EXT_FILBOX_KEY,
)
from .descriptions import DESCRIPTIONS_BY_MODE

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .lan.api import AnycubicAPI
from .lan.mqtt import AnycubicMQTT
from .const import COORDINATOR, CONNECTION_MODE_CLOUD, CONNECTION_MODE_LAN, DOMAIN
from .helper.connection_mode import get_entry_connection_mode
from .helper.mapper import build_lan_printer_payload

_LOGGER = logging.getLogger(__name__)
LAN_DESCRIPTIONS = DESCRIPTIONS_BY_MODE[CONNECTION_MODE_LAN]


def _lan_defs_for(platform: str) -> list[dict[str, Any]]:
    return LAN_DESCRIPTIONS.get(platform) or []


class AnycubicRuntimeCoordinator:
    """Single runtime coordinator entrypoint for LAN and Cloud modes.

    This is the one coordinator object stored in hass.data.
    It delegates to the active backend coordinator based on config-entry mode.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.mode = get_entry_connection_mode(entry)
        self._active: Any = None

    async def async_config_entry_first_refresh(self) -> None:
        """Initialize and refresh the active backend coordinator."""
        if self.mode == CONNECTION_MODE_CLOUD:
            coordinator = AnycubicBackendCoordinator(self.hass, self.entry)
            await coordinator.async_config_entry_first_refresh()
            self._active = coordinator
            return

        host = self.entry.data.get("host")
        coordinator = AnycubicLanCoordinator(self.hass, host)
        coordinator.config_entry = self.entry
        await coordinator.async_config_entry_first_refresh()
        self._active = coordinator

    async def async_shutdown(self) -> None:
        """Shutdown active backend resources safely."""
        if self._active is None:
            return

        if self.mode == CONNECTION_MODE_CLOUD:
            stop = getattr(self._active, "stop_anycubic_mqtt_connection_if_started", None)
            if callable(stop):
                await stop()
            return

        mqtt = getattr(self._active, "mqtt", None)
        disconnect = getattr(mqtt, "disconnect", None) if mqtt else None
        if callable(disconnect):
            if inspect.iscoroutinefunction(disconnect):
                await disconnect()
            else:
                disconnect()

    @property
    def backend(self) -> Any:
        """Return active backend coordinator."""
        return self._active

    def __getitem__(self, key: str) -> Any:
        """Compatibility for legacy cloud access pattern using [COORDINATOR]."""
        if key == COORDINATOR:
            return self._active
        raise KeyError(key)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes/methods to active backend coordinator."""
        if self._active is None:
            raise AttributeError(name)
        return getattr(self._active, name)


class AnycubicLanCoordinator(DataUpdateCoordinator):

    def __init__(self, hass, host):
        super().__init__(
            hass,
            _LOGGER,
            name="",
            update_interval=timedelta(seconds=60),
        )
        self.api: AnycubicAPI | None = None
        self.mqtt: AnycubicMQTT | None = None
        self._host: str = host
        self._current_creds = None
        self._boxes_logged = False


    def debug_mqtt_credentials(self):
        """Log the current MQTT credentials for debugging."""
        if self._current_creds:
            user, passwd = self._current_creds
            # Avoid logging raw passwords; mask for diagnostics.
            masked = "*" * min(4, len(passwd) if passwd else 0)
            _LOGGER.debug("MQTT credentials: user=%s, pass=%s", user, masked)
        else:
            _LOGGER.debug("MQTT credentials have not been retrieved yet")

    def build_printer_payload(self) -> dict[str, Any]:
        """Build entity payload for LAN mode (both-mode API entrypoint).

        Returns a cloud-like shape with `states` and `attributes`.
        LAN data is MQTT topic based, so we expose the current normalized
        coordinator data as states and keep attributes minimal.
        """
        return build_lan_printer_payload(self.data if hasattr(self, "data") else None)

    def async_set_updated_data(self, data):
        """Callback to set updated data from MQTT."""
        # Ensure coordinator has a data store
        if not hasattr(self, "data") or self.data is None:
            self.data = {}

        # Snapshot previous data so we can compute before/after values
        old_data = copy.deepcopy(self.data)

        updated_keys = []

        # Normalize different incoming shapes:
        # - single message: {"type": "print", "data": {...}, ...}
        # - list of messages: [{...}, {...}]
        # - mapping of type->payload: {"print": {...}, "fan": {...}}
        try:
            def _merge_special_key(existing: dict, incoming: dict, key: str) -> dict:
                """For certain keys (multiColorBox / extfilbox) avoid overwriting
                previously-known 'slots' with an empty list. If incoming data
                lacks slot information, mark slots as unknown (None) and
                preserve the last-known value under '_slots_last_known'.
                """
                try:
                    if not incoming or not isinstance(incoming, dict):
                        return incoming
                    data_section = incoming.get("data") or {}
                    # multiColorBox carries a list under 'multi_color_box'
                    if key == MULTI_COLOR_BOX_KEY:
                        incoming_boxes = data_section.get("multi_color_box")
                        if incoming_boxes is None:
                            return incoming
                        # existing boxes map by id
                        existing_boxes = (existing or {}).get("data", {}).get("multi_color_box", [])
                        existing_map = {b.get("id"): b for b in existing_boxes if isinstance(b, dict) and b.get("id") is not None}
                        for b in incoming_boxes:
                            if not isinstance(b, dict):
                                continue
                            # If slots key is missing or an empty list, treat as unknown
                            if "slots" not in b or (isinstance(b.get("slots"), list) and len(b.get("slots")) == 0):
                                prev = existing_map.get(b.get("id"))
                                if prev is not None and prev.get("slots") is not None:
                                    # preserve last-known slots separately and mark current as unknown
                                    b["_slots_last_known"] = prev.get("slots")
                                b["slots"] = None
                        data_section["multi_color_box"] = incoming_boxes
                        incoming["data"] = data_section
                        return incoming

                    # extfilbox may be a single dict under data
                    if key == EXT_FILBOX_KEY:
                        # extfilbox payloads are single objects, not lists
                        # If the incoming data lacks 'slots' but existing had them,
                        # preserve last-known under _slots_last_known and set to None.
                        existing_obj = (existing or {}).get("data") or {}
                        if "slots" not in data_section or (isinstance(data_section.get("slots"), list) and len(data_section.get("slots") or []) == 0):
                            prev_slots = existing_obj.get("slots")
                            if prev_slots is not None:
                                data_section["_slots_last_known"] = prev_slots
                            data_section["slots"] = None
                            incoming["data"] = data_section
                        return incoming
                except Exception:
                    # On any error, return incoming unchanged
                    return incoming

            if isinstance(data, list):
                for msg in data:
                    if isinstance(msg, dict) and "type" in msg:
                        # merge special keys to avoid clobbering slots with empty lists
                        msg_type = msg.get("type")
                        if msg_type in (MULTI_COLOR_BOX_KEY, EXT_FILBOX_KEY):
                            msg = _merge_special_key(self.data.get(msg_type), msg, msg_type)
                        self.data[msg["type"]] = msg
                        updated_keys.append(msg["type"])
                    elif isinstance(msg, dict):
                        for k, v in msg.items():
                            if k in (MULTI_COLOR_BOX_KEY, EXT_FILBOX_KEY):
                                v = _merge_special_key(self.data.get(k), v, k)
                            self.data[k] = v
                            updated_keys.append(k)
            elif isinstance(data, dict) and "type" in data:
                # single message
                msg_type = data.get("type")
                if msg_type in (MULTI_COLOR_BOX_KEY, EXT_FILBOX_KEY):
                    data = _merge_special_key(self.data.get(msg_type), data, msg_type)
                self.data[msg_type] = data
                updated_keys.append(msg_type)
            elif isinstance(data, dict):
                # mapping of types -> payloads
                for key, value in data.items():
                    if key in (MULTI_COLOR_BOX_KEY, EXT_FILBOX_KEY):
                        value = _merge_special_key(self.data.get(key), value, key)
                    self.data[key] = value
                    updated_keys.append(key)
            else:
                _LOGGER.warning("Anycubic received unsupported payload type: %s", type(data))
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("Error while normalizing incoming MQTT data: %s", data)

        # Keep a raw-data snapshot for debugging / discovery of new MQTT keys.
        try:
            if self.mqtt is not None:
                self.data["raw_data"] = copy.deepcopy(self.mqtt.state)
        except Exception:
            _LOGGER.exception("Failed to snapshot raw MQTT state")

        # Notify listeners that boxes were updated; include current boxes list
        try:
            multi_color_box = self.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
            # Log on first receipt so user can verify boxes exist; debug on subsequent updates
            if multi_color_box and not self._boxes_logged:
                ids = [b.get("id") for b in multi_color_box]
                _LOGGER.info("Detected multiColorBox entries: %s", ids)
                self._boxes_logged = True
            else:
                _LOGGER.debug("Boxes updated: received %d boxes", len(multi_color_box))
            async_dispatcher_send(self.hass, f"{DOMAIN}_boxes_updated", multi_color_box)
        except Exception:
            pass

        # Log updated keys for debugging and per-entity changes. For each
        # updated top-level key, resolve values for definitions that depend
        # on that key and log old -> new values for visibility.
        if updated_keys:
            _LOGGER.debug("Updated topic: %s", updated_keys)

            def _get_from_path(data_dict, path):
                cur = data_dict
                for p in path:
                    if isinstance(p, int):
                        if not isinstance(cur, list):
                            return None
                        if p < 0 or p >= len(cur):
                            return None
                        cur = cur[p]
                    else:
                        if not isinstance(cur, dict):
                            return None
                        cur = cur.get(p)
                        if cur is None:
                            return None
                return cur

            def _resolve_def_value(defn, data_store):
                # Try to resolve a definition value from coordinator-style data
                data_path = tuple(defn.get("data_path", ()))
                if not data_path:
                    return None
                top = data_path[0]
                rest = data_path[1:]

                top_data = data_store.get(top)
                # Special-case multiColorBox definitions which expect per-box
                if top == MULTI_COLOR_BOX_KEY:
                    box_id = defn.get("device_index")
                    # Accept multiple shapes: either the stored value is the
                    # full message dict with 'data' -> 'multi_color_box' or it
                    # may already be the list of boxes.
                    if isinstance(top_data, dict):
                        boxes = top_data.get("data", {}).get("multi_color_box", [])
                    elif isinstance(top_data, list):
                        boxes = top_data
                    else:
                        boxes = []

                    box = None
                    if box_id is None:
                        box = boxes[0] if boxes else None
                    else:
                        for b in boxes:
                            if isinstance(b, dict) and b.get("id") == box_id:
                                box = b
                                break
                    if box is None:
                        return None

                    # slot sensors
                    if defn.get("slot_index") is not None:
                        slot_index = defn["slot_index"]
                        for s in (box.get("slots") or []):
                            if s.get("index") == slot_index:
                                if s.get("status") == 4:
                                    return "Empty"
                                rgb = tuple(s.get("color", [0, 0, 0]))
                                try:
                                    from .sensor import PLA_COLOR_MAP

                                    color_name = PLA_COLOR_MAP.get(rgb, str(rgb))
                                except Exception:
                                    color_name = str(rgb)
                                return f"{s.get('type', 'Unknown')} ({color_name})"
                        return None

                    # data_field override
                    data_field = defn.get("data_field")
                    if data_field:
                        if isinstance(data_field, tuple):
                            val = box
                            for p in data_field:
                                if isinstance(val, dict):
                                    val = val.get(p)
                                else:
                                    val = None
                                if val is None:
                                    break
                            return val
                        # Normal scalar field requested from the box dict
                        return box.get(data_field)

                    # Default: no specific field requested; do not return the
                    # whole box for numeric sensors — return None instead.
                    return None

                # Generic path: be tolerant to top_data being a mapping or list
                if isinstance(top_data, dict):
                    return _get_from_path(top_data, rest)
                # If top_data is a list, try to follow rest if it starts with 'data' or similar
                if isinstance(top_data, list):
                    # If the rest refers directly to the multi_color_box list,
                    # return the list; otherwise we cannot resolve
                    return _get_from_path({top: top_data}, rest)

                return None

            # Build a list of definitions to check (sensors first, then others)
            all_defs = []
            all_defs.extend(_lan_defs_for("sensor"))
            all_defs.extend(_lan_defs_for("number"))
            all_defs.extend(_lan_defs_for("select"))
            all_defs.extend(_lan_defs_for("fan"))
            all_defs.extend(_lan_defs_for("switch"))
            all_defs.extend(_lan_defs_for("button"))
            all_defs.extend(_lan_defs_for("light"))

            for k in updated_keys:
                for defn in all_defs:
                    # determine the top-level key this definition depends on
                    dp = defn.get("data_path")
                    if isinstance(dp, (list, tuple)) and dp:
                        top_key = dp[0]
                    else:
                        # fallback: some defs expose data_key instead
                        top_key = defn.get("data_key")
                    if top_key != k:
                        continue

                    old_val = _resolve_def_value(defn, old_data)
                    new_val = _resolve_def_value(defn, self.data)
                    if old_val != new_val:
                        try:
                            old_j = json.dumps(old_val, ensure_ascii=False)
                        except Exception:
                            old_j = str(old_val)
                        try:
                            new_j = json.dumps(new_val, ensure_ascii=False)
                        except Exception:
                            new_j = str(new_val)
                        _LOGGER.debug(
                            "State changed: %s (%s): %s -> %s",
                            defn.get("name"),
                            defn.get("key"),
                            old_j,
                            new_j,
                        )

        # Notify DataUpdateCoordinator listeners (entities) that data changed.
        try:
            super().async_set_updated_data(self.data)
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("Failed to notify listeners after MQTT update")

    async def _async_update_data(self):
        """Fetch latest data from Anycubic API and update MQTT credentials if needed."""
        _LOGGER.debug("_async_update_data: fetching Anycubic API data and querying minimal MQTT topics")
        if not self.api:
            self.api = AnycubicAPI(self._host)

        # fetch latest data from API
        try:
            data = await self.hass.async_add_executor_job(self.api.discover)
        except Exception as err:
            _LOGGER.error(f"Anycubic API fetch failed: {err}")
            raise UpdateFailed(f"Could not fetch Anycubic data: {err}") from err

        # extract MQTT credentials
        creds = (data["username"], data["password"])

        # if credentials are new, initialize MQTT client, else reconfigure if changed
        if self._current_creds is None:
            self._current_creds = creds
            self.debug_mqtt_credentials()
            await self._async_init_mqtt(data)
        elif creds != self._current_creds:
            self._current_creds = creds
            self.debug_mqtt_credentials()
            await self._async_reconfigure_mqtt(*creds)

        # Only query minimal required topic(s) here (avoid querying every topic
        # on coordinator startup). Platform code should request additional
        # topics as needed using coordinator.async_query_topic(topic).
        if self.mqtt:
            topics = ["info"]
            _LOGGER.debug("Querying minimal MQTT topics: %s", topics)
            for topic_name in topics:
                payload = {"type": topic_name, "action": "query"}
                topic = self.mqtt.web_topic(topic_name)
                self.mqtt.publish_json(topic, payload)
        else:
            _LOGGER.debug("MQTT client not initialized yet; skipping minimal topic query")

        # return current coordinator data
        _LOGGER.debug("Returning coordinator data keys: %s", list(self.data.keys()) if self.data else [])
        return self.data or {}

    async def _async_init_mqtt(self, data):
        """Initialize MQTT client with credentials from API data."""
        match = re.match(r"mqtts?://([^:]+):(\d+)", data["broker"])
        if not match:
            raise ValueError(f"Invalid broker URL: {data['broker']}")
        broker = match.group(1)
        port = int(match.group(2))
        self.mqtt = AnycubicMQTT(
            self.hass,
            broker,
            port,
            data["username"],
            data["password"],
            data["modeId"],
            data["deviceId"],
        )
        self.mqtt.on_update = self.async_set_updated_data
        
        # Apply debug logging setting if available
        if hasattr(self, 'config_entry') and self.config_entry:
            debug_mqtt_msg = bool(self.config_entry.options.get(CONF_DEBUG_MQTT_MSG, False))
            self.mqtt.set_debug_logging(debug_mqtt_msg)
        
        await self.hass.async_add_executor_job(self.mqtt.connect)

    async def _async_reconfigure_mqtt(self, username, password):
        """Reconfigure MQTT client with new credentials."""
        if self.mqtt is None:
            return await self._async_init_mqtt(await self.hass.async_add_executor_job(self.api.discover))
        self.mqtt.client.username_pw_set(username, password)
        await self.hass.async_add_executor_job(self.mqtt.client.reconnect)

    async def async_query_topic(self, topic: str, action: str = "query"):
        """Send a query MQTT message for the given topic."""
        import time
        import uuid

        payload: dict[str, Any] = {
            "type": topic,
            "action": action,
            "timestamp": int(time.time() * 1000),
            "msgid": str(uuid.uuid4()),
            "data": None,
        }
        if not self.mqtt:
            _LOGGER.debug("Cannot query topic '%s' because MQTT client is not ready", topic)
            return False

        mqtt_topic = self.mqtt.web_topic(topic)
        self.mqtt.publish_json(mqtt_topic, payload)
        _LOGGER.debug("Published query for topic '%s' to MQTT topic '%s'", topic, mqtt_topic)
        return True

    def _lan_publish(
        self,
        topic_name: str,
        payload: dict[str, Any],
        use_printer_topic: bool = False,
    ) -> bool:
        if not self.mqtt:
            _LOGGER.debug("Cannot publish LAN event to '%s': MQTT not ready", topic_name)
            return False

        topic = (
            self.mqtt.printer_topic(topic_name)
            if use_printer_topic
            else self.mqtt.web_topic(topic_name)
        )
        self.mqtt.publish_json(topic, payload)
        return True

    def _find_box_by_id(self, box_id: int | None) -> dict[str, Any] | None:
        if box_id is None:
            return None
        boxes = self.data.get(MULTI_COLOR_BOX_KEY, {}).get("data", {}).get("multi_color_box", [])
        for box in boxes:
            if box.get("id") == int(box_id):
                return box
        return None

    async def button_press_event(
        self,
        printer_id: int | None,
        event_key: str,
    ) -> None:
        axis_map = {
            "home_all": 5,
            "home_xy": 4,
            "home_z": 3,
        }
        print_map = {
            "pause_print": "pause",
            "resume_print": "resume",
            "cancel_print": "stop",
        }

        if event_key in axis_map:
            payload = {
                "type": "axis",
                "action": "move",
                "data": {"axis": axis_map[event_key], "move_type": 2, "distance": 0},
            }
            self._lan_publish("axis", payload)
            return

        if event_key in print_map:
            payload = {
                "type": "print",
                "action": print_map[event_key],
                "data": {"taskid": "-1"},
            }
            self._lan_publish("print", payload)

    async def switch_on_event(
        self,
        printer_id: int | None,
        event_key: str,
        **kwargs: Any,
    ) -> None:
        if event_key == "manual_mqtt_connection_enabled":
            if self.mqtt is not None:
                self.mqtt.set_debug_logging(True)
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Anycubic",
                    "message": "MQTT Debug Logging is enabled. Incoming and outgoing MQTT messages are now logged at DEBUG level.",
                    "notification_id": "anycubic_mqtt_debug_logging",
                },
                blocking=False,
            )
            return

        box_id = kwargs.get("box_id")

        if "drying" in str(event_key):
            target_temp = int(kwargs.get("target_temp", 45))
            duration = int(kwargs.get("duration", 240))
            payload = {
                "type": "multiColorBox",
                "action": "setDry",
                "data": {
                    "multi_color_box": [
                        {
                            "id": box_id,
                            "drying_status": {
                                "status": 1,
                                "target_temp": target_temp,
                                "duration": duration,
                            },
                        }
                    ]
                },
            }
            self._lan_publish("multiColorBox", payload)
            return

        if "auto_feed" in str(event_key):
            payload = {
                "type": "multiColorBox",
                "action": "setAutoFeed",
                "data": {"multi_color_box": [{"id": box_id, "auto_feed": 1}]},
            }
            self._lan_publish("multiColorBox", payload)

    async def switch_off_event(
        self,
        printer_id: int | None,
        event_key: str,
        **kwargs: Any,
    ) -> None:
        if event_key == "manual_mqtt_connection_enabled":
            if self.mqtt is not None:
                self.mqtt.set_debug_logging(False)
            return

        box_id = kwargs.get("box_id")

        if "drying" in str(event_key):
            payload = {
                "type": "multiColorBox",
                "action": "setDry",
                "data": {
                    "multi_color_box": [
                        {
                            "id": box_id,
                            "drying_status": {
                                "status": 0,
                            },
                        }
                    ]
                },
            }
            self._lan_publish("multiColorBox", payload)
            return

        if "auto_feed" in str(event_key):
            payload = {
                "type": "multiColorBox",
                "action": "setAutoFeed",
                "data": {"multi_color_box": [{"id": box_id, "auto_feed": 0}]},
            }
            self._lan_publish("multiColorBox", payload)

    async def number_set_event(
        self,
        event_key: str,
        value: int,
        **kwargs: Any,
    ) -> None:
        kind = kwargs.get("kind")
        box_id = kwargs.get("box_id")

        if kind and box_id is not None:
            current_box = self._find_box_by_id(int(box_id))
            drying_status = (current_box or {}).get("drying_status", {})
            current_target = drying_status.get("target_temp", 45)
            current_duration = drying_status.get("duration", 240)
            current_status = drying_status.get("status", 1)

            if kind == "drying_target":
                target_temp = int(value)
                duration = int(current_duration)
            else:
                target_temp = int(current_target)
                duration = int(value)

            payload = {
                "type": "multiColorBox",
                "action": "setDry",
                "data": {
                    "multi_color_box": [
                        {
                            "id": box_id,
                            "drying_status": {
                                "status": int(current_status),
                                "target_temp": target_temp,
                                "duration": duration,
                            },
                        }
                    ]
                },
            }
            self._lan_publish("multiColorBox", payload)
            return

        data_key = kwargs.get("data_key")
        if data_key:
            payload = {
                "type": "print",
                "action": "update",
                "data": {
                    "taskid": "-1",
                    "settings": {
                        data_key: int(value),
                    },
                },
            }
            self._lan_publish("print", payload)

    async def select_set_event(
        self,
        event_key: str,
        mapped_value: int,
    ) -> None:
        payload = {
            "type": "print",
            "action": "update",
            "data": {
                "taskid": "-1",
                "settings": {
                    "print_speed_mode": int(mapped_value),
                },
            },
        }
        self._lan_publish("print", payload)

    async def fan_set_event(
        self,
        event_key: str,
        data_key: str,
        percentage: int,
    ) -> None:
        fan_payload = self.data.get("fan", {}).get("data", {}) or {}
        fan_data: dict[str, int] = {}
        for fdef in _lan_defs_for("fan"):
            key = fdef.get("data_key")
            if key:
                fan_data[key] = int(fan_payload.get(key, 0))

        fan_data[data_key] = int(percentage)
        payload = {
            "type": "fan",
            "action": "auto",
            "data": fan_data,
        }
        self._lan_publish("fan", payload, use_printer_topic=True)

    async def light_set_event(
        self,
        event_key: str,
        type_id: int,
        status: int,
        brightness: int,
    ) -> None:
        payload = {
            "type": "light",
            "action": "control",
            "data": {
                "type": int(type_id),
                "status": int(status),
                "brightness": int(brightness),
            },
        }
        self._lan_publish("light", payload)

    def get_boxes(self) -> list[dict]:
        """Return the list of multicolor boxes from the last coordinator data snapshot.

        This is synchronous and intended for use by platform setup code.
        """
        return self.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])

    async def async_get_boxes(self) -> list[dict]:
        """Async helper to query the device for boxes and return the latest list.

        Platforms can call this to ensure they have current box info (it will
        publish a query to MQTT and then return whatever is currently stored).
        """
        try:
            # Request the detailed box info using the device's getInfo action
            await self.async_query_topic("multiColorBox", action="getInfo")
        except Exception:
            _LOGGER.debug("Failed to query multiColorBox from coordinator")
        return self.get_boxes()

    def expand_definitions(self, definitions: list[dict]) -> list[dict]:
        """Expand template definitions that are marked as per_box.

        Replaces placeholders like {box_id} in name/key and attaches box_id
        and device_index fields so platforms can create per-box entities.
        """
        try:
            boxes = self.get_boxes() or []
            expanded: list[dict] = []
            skipped_templates = []

            for d in definitions:
                # If this definition is per_box, expand it for each box
                if d.get("per_box"):
                    template_key = d.get("key", "unknown")
                    skipped_templates.append(template_key)
                    for box in boxes:
                        box_id = box.get("id")
                        if box_id is None:
                            continue

                        # Base per-box expansion
                        base = dict(d)
                        # Replace any {box_id} placeholders in string fields
                        for k, v in list(base.items()):
                            # Keep translation keys generic so one translation entry
                            # can serve all expanded per-box entities.
                            if k == "translation_key":
                                continue
                            if isinstance(v, str) and "{box_id}" in v:
                                base[k] = v.replace("{box_id}", str(box_id))

                        # If key doesn't include box_id, append suffix to keep visible key clean
                        key = base.get("key")
                        if isinstance(key, str):
                            if "{box_id}" not in d.get("key", "") and "{box_id}" not in (key or ""):
                                # append box id for uniqueness but keep base name
                                base["key"] = f"{key}_{box_id}"

                        base["box_id"] = box_id
                        base["device_index"] = box_id
                        base.pop("per_box", None)

                        # If this definition should be expanded per slot inside each box
                        if d.get("per_slot"):
                            slots = box.get("slots", []) or []
                            for s in slots:
                                si = s.get("index")
                                if si is None:
                                    continue
                                slot_def = dict(base)
                                # replace any {slot_index} placeholders
                                for k2, v2 in list(slot_def.items()):
                                    if k2 == "translation_key":
                                        continue
                                    if isinstance(v2, str) and "{slot_index}" in v2:
                                        slot_def[k2] = v2.replace("{slot_index}", str(si))
                                # if key doesn't include slot index, append it
                                sk = slot_def.get("key")
                                if isinstance(sk, str) and "{slot_index}" not in (d.get("key", "") or "") and "{slot_index}" not in (sk or ""):
                                    slot_def["key"] = f"{sk}_slot{si}"
                                slot_def["slot_index"] = si
                                slot_def.pop("per_slot", None)
                                expanded.append(slot_def)
                        else:
                            expanded.append(base)
                    # Do NOT add the original template definition (it has per_box=True)
                else:
                    # Not a template; add as-is
                    expanded.append(d)

            # Log expansion results for debugging unique_id collisions
            if skipped_templates:
                _LOGGER.debug("expand_definitions: skipped %d template definitions (per_box/per_slot): %s", len(skipped_templates), skipped_templates)
            _LOGGER.debug("expand_definitions: created %d total definitions from %d input definitions", len(expanded), len(definitions))
            
            # Check for duplicate keys in expanded list
            keys_seen = {}
            for e in expanded:
                k = e.get("key")
                if k in keys_seen:
                    _LOGGER.warning("expand_definitions: DUPLICATE key detected: %s (original: %s, duplicate: %s)", k, keys_seen[k], e.get("name"))
                else:
                    keys_seen[k] = e.get("name")

            return expanded
        except Exception as err:
            _LOGGER.exception("expand_definitions failed: %s", err)
            return []

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    CoreState,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    HomeAssistantError,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceInfo, async_get as async_get_device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud.anycubic_api import AnycubicMQTTAPI as AnycubicCloudAPI
from .cloud.exceptions.exceptions import AnycubicAPIError, AnycubicAPIParsingError
from .const import (
    API_SETUP_RETRIES,
    API_SETUP_RETRY_INTERVAL_SECONDS,
    CONF_DEBUG_API_CALLS,
    CONF_DEBUG_DEPRECATED,
    CONF_DEBUG_MQTT_MSG,
    CONF_MQTT_CONNECT_MODE,
    CONF_PRINTER_ID_LIST,
    CONF_USER_AUTH_MODE,
    CONF_USER_DEVICE_ID,
    CONF_USER_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENTITY_ID_DRYING_START_PRESET_,
    FAILED_UPDATE_DELAY,
    LOGGER,
    MAX_FAILED_UPDATES,
    MQTT_ACTION_RESPONSE_ALIVE_SECONDS,
    MQTT_IDLE_DISCONNECT_SECONDS,
    MQTT_REFRESH_INTERVAL,
    MQTT_SCAN_INTERVAL,
    PRINT_JOB_STARTED_UPDATE_DELAY,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .helper.mapper import (
    AnycubicMQTTConnectMode,
    build_cloud_printer_payload,
    build_printer_device_info,
    check_descriptor_state_ace_not_supported,
    check_descriptor_state_ace_primary_unavailable,
    check_descriptor_state_ace_secondary_unavailable,
    check_descriptor_state_drying_unavailable,
    check_descriptor_status_not_fdm,
    check_descriptor_status_not_lcd,
    get_drying_preset_from_entry_options,
    printer_attributes_for_key,
    printer_state_connected_ace_units,
    printer_state_supports_ace,
)
from .entity import AnycubicEntity, AnycubicEntityDescription

if TYPE_CHECKING:
    from .cloud.data_models.printer import AnycubicPrinter


_AnycubicEntityT = TypeVar("_AnycubicEntityT", bound=AnycubicEntity)


class AnycubicBackendCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Anycubic backend data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize Anycubic backend coordinator."""
        self.entry: ConfigEntry = entry
        self._anycubic_api: AnycubicCloudAPI | None = None
        self._anycubic_printers: dict[int, AnycubicPrinter] = dict()
        self._cloud_file_list: list[dict[str, Any]] | None = None
        self._last_state_update: int | None = None
        self._failed_updates: int = 0
        self._mqtt_task: asyncio.Future[None] | None = None
        self._mqtt_manually_connected = False
        self._mqtt_idle_since: int | None = None
        self._mqtt_last_action: int | None = None
        self._mqtt_connect_check_lock = asyncio.Lock()
        self._mqtt_refresh_lock = asyncio.Lock()
        self._mqtt_file_list_check_lock = asyncio.Lock()
        self._mqtt_last_refresh: int | None = None
        self._printer_device_map: dict[str, int] | None = None
        mqtt_connect_mode = self.entry.options.get(CONF_MQTT_CONNECT_MODE)
        self._mqtt_connection_mode = (
            AnycubicMQTTConnectMode.Printing_Only
            if mqtt_connect_mode is None
            else mqtt_connect_mode
        )
        self._unregistered_descriptors: dict[int, dict[str, list[AnycubicEntityDescription]]] = dict()
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=MQTT_SCAN_INTERVAL),
            always_update=False,
        )

    @property
    def anycubic_api(self) -> AnycubicCloudAPI:
        if not self._anycubic_api:
            raise ConfigEntryError("Anycubic API instance is missing.")
        return self._anycubic_api

    def _any_printers_are_printing(self) -> bool:
        return any([
            printer.is_busy for printer_id, printer in self._anycubic_printers.items()
        ])

    def _any_printers_are_drying(self) -> bool:
        return any([
            (
                printer.primary_drying_status_is_drying or
                printer.secondary_drying_status_is_drying
            ) for printer_id, printer in self._anycubic_printers.items()
        ])

    def _any_printers_are_online(self) -> bool:
        return any([
            (
                printer.printer_online or printer.is_busy
            ) for printer_id, printer in self._anycubic_printers.items()
        ])

    def _no_printers_are_printing(self) -> bool:
        return all([
            not printer.is_busy and
            (not printer.latest_project_print_in_progress)
            for printer_id, printer in self._anycubic_printers.items()
        ])

    def _check_mqtt_connection_last_action_waiting(self) -> bool:
        if (
            self._mqtt_last_action is not None and
            int(time.time()) < self._mqtt_last_action + MQTT_ACTION_RESPONSE_ALIVE_SECONDS
        ):
            return True

        return False

    def _check_mqtt_connection_modes_active(self) -> bool:
        if self._check_mqtt_connection_last_action_waiting():
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Printing_Only and
            self._any_printers_are_printing()
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Printing_Drying and
            (self._any_printers_are_printing() or self._any_printers_are_drying())
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Device_Online and
            self._any_printers_are_online()
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Always
        ):
            return True

        else:
            return False

    def _check_mqtt_connection_modes_inactive(self) -> bool:
        if self._check_mqtt_connection_last_action_waiting():
            return False

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Printing_Only and
            self._no_printers_are_printing()
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Printing_Drying and
            (self._no_printers_are_printing() and not self._any_printers_are_drying())
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Device_Online and
            not self._any_printers_are_online()
        ):
            return True

        elif (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Always
        ):
            return False

        else:
            return False

    def _build_cloud_printer_dict(self, printer: AnycubicPrinter) -> dict[str, Any]:
        return build_cloud_printer_payload(
            printer=printer,
            cloud_file_list=self._cloud_file_list,
            mqtt_manually_connected=self._mqtt_manually_connected,
            mqtt_supports_login=self.anycubic_api.anycubic_auth.supports_mqtt_login,
            entry_options=self.entry.options,
        )

    def build_printer_payload(self, printer: AnycubicPrinter) -> dict[str, Any]:
        """Build entity payload for Cloud mode (both-mode API entrypoint)."""
        return self._build_cloud_printer_dict(printer)

    def _build_coordinator_data(self) -> dict[str, Any]:
        data_dict: dict[str, Any] = dict()

        data_dict['user_info'] = {
            "id": self.anycubic_api.anycubic_auth.api_user_id
        }

        data_dict['printers'] = dict()

        for printer_id, printer in self._anycubic_printers.items():
            data_dict['printers'][printer_id] = self.build_printer_payload(printer)

        return data_dict

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from AnycubicCloud."""

        if not self._last_state_update or int(time.time()) > self._last_state_update + DEFAULT_SCAN_INTERVAL:
            await self.get_anycubic_updates()

        data_dict = self._build_coordinator_data()

        if self._printer_device_map is None:
            await self._register_printer_devices(data_dict)

        return data_dict

    async def _async_force_data_refresh(self) -> None:
        self.data = self._build_coordinator_data()
        self.last_update_success = True
        self.async_update_listeners()

    @callback
    def add_entities_for_seen_printers(
        self,
        async_add_entities: AddEntitiesCallback,
        entity_constructor: type[_AnycubicEntityT],
        platform: Platform,
        available_descriptors: list[AnycubicEntityDescription],
    ) -> None:
        """Add Anycubic Cloud entities.

        Called from a platforms `async_setup_entry`.
        """

        for printer_id in self.entry.data[CONF_PRINTER_ID_LIST]:
            if printer_id not in self._unregistered_descriptors:
                self._unregistered_descriptors[printer_id] = dict()

            self._unregistered_descriptors[printer_id][platform] = available_descriptors.copy()

        @callback
        def _add_entities_for_unregistered_descriptors() -> None:
            new_entities: list[_AnycubicEntityT] = []

            for printer_id in self.entry.data[CONF_PRINTER_ID_LIST]:
                if printer_id not in self._unregistered_descriptors:
                    continue
                if platform not in self._unregistered_descriptors[printer_id]:
                    continue

                status_attr: dict[str, Any] | None = printer_attributes_for_key(self, printer_id, 'current_status')
                if not status_attr:
                    raise ConfigEntryError(f"Printer {printer_id} status attributes not found.")
                material_type = status_attr['material_type']
                connected_ace_units = printer_state_connected_ace_units(self, printer_id)
                supports_ace = printer_state_supports_ace(self, printer_id)

                remaining_unregistered_descriptors = list()

                for description in self._unregistered_descriptors[printer_id][platform]:
                    if (
                        check_descriptor_status_not_lcd(
                            description,
                            material_type,
                        )
                        or
                        check_descriptor_status_not_fdm(
                            description,
                            material_type,
                        )
                        or
                        check_descriptor_state_ace_not_supported(
                            description,
                            supports_ace,
                        )
                    ):
                        continue
                    elif (
                        check_descriptor_state_ace_primary_unavailable(
                            description,
                            supports_ace,
                            connected_ace_units,
                        )
                        or
                        check_descriptor_state_ace_secondary_unavailable(
                            description,
                            supports_ace,
                            connected_ace_units,
                        )
                        or
                        check_descriptor_state_drying_unavailable(
                            description,
                            supports_ace,
                            connected_ace_units,
                            self.entry.options,
                        )
                    ):
                        remaining_unregistered_descriptors.append(description)
                        continue
                    elif description.printer_entity_type is None:
                        raise ConfigEntryError(f"Descriptor {description.key} is missing printer_entity_type.")

                    new_entities.append(
                        entity_constructor(
                            self.hass,
                            self,
                            printer_id,
                            description
                        )
                    )

                if len(remaining_unregistered_descriptors) > 0:
                    self._unregistered_descriptors[printer_id][platform] = remaining_unregistered_descriptors
                else:
                    self._unregistered_descriptors[printer_id].pop(platform)

                if len(self._unregistered_descriptors[printer_id]) == 0:
                    self._unregistered_descriptors.pop(printer_id)

            async_add_entities(new_entities)

        _add_entities_for_unregistered_descriptors()
        self.entry.async_on_unload(
            self.async_add_listener(_add_entities_for_unregistered_descriptors)
        )

    async def _async_print_job_started(self) -> None:
        LOGGER.debug(
            f"Print job started, forcing state update in {PRINT_JOB_STARTED_UPDATE_DELAY} seconds."
        )
        await asyncio.sleep(PRINT_JOB_STARTED_UPDATE_DELAY)
        await self.force_state_update()

    async def _async_mqtt_callback_subscribed(self) -> None:
        await asyncio.sleep(10)
        for printer_id, printer in self._anycubic_printers.items():
            try:
                if printer.printer_online:
                    await printer.query_printer_options()
            except Exception as error:
                tb = traceback.format_exc()
                LOGGER.warning(f"Anycubic MQTT on subscribe error: {error}\n{tb}")

    @callback
    def _mqtt_callback_data_updated(self) -> None:
        self.hass.create_task(
            self._async_force_data_refresh(),
            f"Anycubic coordinator {self.entry.entry_id} data refresh",
        )

    @callback
    def _mqtt_callback_print_job_started(
        self,
    ) -> None:
        self.hass.create_task(
            self._async_print_job_started(),
            f"Anycubic coordinator {self.entry.entry_id} print job started",
        )

    @callback
    def _mqtt_callback_subscribed(
        self,
    ) -> None:
        self.hass.create_task(
            self._async_mqtt_callback_subscribed(),
            f"Anycubic coordinator {self.entry.entry_id} MQTT subscribed",
        )

    def _anycubic_mqtt_connection_should_start(self) -> bool:

        if (
            self._mqtt_connection_mode == AnycubicMQTTConnectMode.Never_Connect
            or not self.anycubic_api.anycubic_auth.supports_mqtt_login
        ):
            return False

        return (
            not self.anycubic_api.mqtt_is_started and
            not self.hass.is_stopping and
            self.hass.state is CoreState.running and
            (
                self._check_mqtt_connection_modes_active() or
                self._mqtt_manually_connected
            )
        )

    def _anycubic_mqtt_connection_should_stop(self) -> bool:

        return (
            self.anycubic_api.mqtt_is_started and
            (
                self.hass.is_stopping or
                (
                    self._anycubic_mqtt_connection_is_idle() and
                    not self._mqtt_manually_connected
                )
            )
        )

    def _anycubic_mqtt_connection_is_idle(self) -> bool:
        if self._check_mqtt_connection_modes_inactive():
            if self._mqtt_idle_since is None:
                self._mqtt_idle_since = int(time.time())

            if int(time.time()) > self._mqtt_idle_since + MQTT_IDLE_DISCONNECT_SECONDS:
                self._mqtt_idle_since = None
                return True

        else:
            self._mqtt_idle_since = None

        return False

    async def _check_anycubic_mqtt_connection(self, refreshing: bool = False) -> None:
        if not refreshing and self._mqtt_refresh_lock.locked():
            return

        async with self._mqtt_connect_check_lock:
            if self._anycubic_mqtt_connection_should_start():

                for printer_id, printer in self._anycubic_printers.items():
                    self.anycubic_api.mqtt_add_subscribed_printer(
                        printer
                    )

                if self._mqtt_task is None:
                    LOGGER.debug("Starting Anycubic MQTT Task.")
                    self._mqtt_task = self.hass.async_add_executor_job(
                        self.anycubic_api.connect_mqtt
                    )

            elif self._anycubic_mqtt_connection_should_stop():
                await self._stop_anycubic_mqtt_connection()

    async def _stop_anycubic_mqtt_connection(self) -> None:
        for printer_id, printer in self._anycubic_printers.items():
            await self.hass.async_add_executor_job(
                self.anycubic_api.mqtt_unsubscribe_printer_status,
                printer,
            )
        await self.hass.async_add_executor_job(
            self.anycubic_api.disconnect_mqtt,
        )

        await self.anycubic_api.mqtt_wait_for_disconnect()

        if self._mqtt_task is not None and not self._mqtt_task.done():
            self._mqtt_task.cancel()

        self._mqtt_task = None

    async def stop_anycubic_mqtt_connection_if_started(self) -> None:
        if self._anycubic_api and self._anycubic_api.mqtt_is_started:
            await self._stop_anycubic_mqtt_connection()

    async def refresh_anycubic_mqtt_connection(self) -> None:
        if self._mqtt_last_refresh and int(time.time()) < self._mqtt_last_refresh + MQTT_REFRESH_INTERVAL:
            return

        if self._mqtt_connect_check_lock.locked():
            return

        if self._anycubic_api and self._anycubic_api.mqtt_is_started:
            async with self._mqtt_refresh_lock:
                self._mqtt_last_refresh = int(time.time())
                await self._stop_anycubic_mqtt_connection()
                await asyncio.sleep(2)
                await self._check_anycubic_mqtt_connection(True)

    async def _async_check_local_file_list_changed(
        self,
        prev_file_list: list[dict[str, str | float]] | None,
        printer: AnycubicPrinter,
    ) -> None:
        if self._mqtt_file_list_check_lock.locked():
            return

        async with self._mqtt_file_list_check_lock:
            if not printer.printer_online:
                return

            await asyncio.sleep(5)
            new_file_list = printer.local_file_list_object
            if prev_file_list is None and new_file_list is None:
                LOGGER.debug("Anycubic MQTT response for local file list appears to be empty, refreshing MQTT and retrying.")
                await self.refresh_anycubic_mqtt_connection()
                await self.anycubic_api.mqtt_wait_for_connect()
                await asyncio.sleep(2)
                await printer.request_local_file_list()

    async def _setup_anycubic_api_connection(self) -> None:
        LOGGER.debug("Coordinator setting up Anycubic Cloud API connection.")
        store = Store[dict[str, Any]](self.hass, STORAGE_VERSION, STORAGE_KEY)

        if self.entry.data.get(CONF_USER_TOKEN) is None:
            raise ConfigEntryAuthFailed("Authentication Token not found.")

        try:
            # config = await store.async_load()
            cookie_jar = CookieJar(unsafe=True)
            websession = async_create_clientsession(
                self.hass,
                cookie_jar=cookie_jar,
            )
            self._anycubic_api = AnycubicCloudAPI(
                session=websession,
                cookie_jar=cookie_jar,
                debug_logger=LOGGER,
                mqtt_callback_printer_update=self._mqtt_callback_data_updated,
                mqtt_callback_printer_busy=self._mqtt_callback_print_job_started,
                mqtt_callback_subscribed=self._mqtt_callback_subscribed,
            )
            self._anycubic_api.set_authentication(
                auth_token=self.entry.data[CONF_USER_TOKEN],
                auth_mode=self.entry.data.get(CONF_USER_AUTH_MODE),
                device_id=self.entry.data.get(CONF_USER_DEVICE_ID),
            )

            debug_all: bool = bool(self.entry.options.get(CONF_DEBUG_DEPRECATED))
            debug_mqtt_msg: bool = bool(
                self.entry.options.get(CONF_DEBUG_MQTT_MSG, debug_all)
            )
            debug_api_calls: bool = bool(
                self.entry.options.get(CONF_DEBUG_API_CALLS, debug_all)
            )

            self._anycubic_api.set_mqtt_log_all_messages(debug_mqtt_msg)
            self._anycubic_api.set_log_api_call_info(debug_api_calls)

            success = await self._anycubic_api.check_api_tokens()
            if not success:
                raise ConfigEntryAuthFailed("Authentication failed. Check credentials.")

            # Create config
            await store.async_save(self._anycubic_api.get_auth_config_dict())

            first_printer_id = self.entry.data[CONF_PRINTER_ID_LIST][0]

            printer_status = await self._anycubic_api.printer_info_for_id(first_printer_id)

            if printer_status is None:
                raise ConfigEntryAuthFailed("Printer not found. Check config.")

        except ConfigEntryAuthFailed:
            raise

        except AnycubicAPIParsingError:
            raise

        except Exception as error:
            raise ConfigEntryAuthFailed(
                f"Coordinator authentication failed with unknown Error. Check credentials {error}"
            )

    async def _setup_anycubic_printer_objects(self) -> None:
        for printer_id in self.entry.data[CONF_PRINTER_ID_LIST]:
            try:
                printer = await self.anycubic_api.printer_info_for_id(printer_id)
                if not printer:
                    raise ConfigEntryError(f"Failed to load printer object for {printer_id}")
                self._anycubic_printers[int(printer_id)] = printer
            except ConfigEntryError:
                raise
            except Exception as error:
                raise ConfigEntryError(error) from error

    async def _register_printer_devices(
        self,
        data_dict: dict[str, Any],
    ) -> None:
        self._printer_device_map = dict()
        dev_reg = async_get_device_registry(self.hass)
        for printer_id in self.entry.data[CONF_PRINTER_ID_LIST]:
            printer_device_info: DeviceInfo = build_printer_device_info(
                data_dict,
                printer_id,
            )
            printer_device = dev_reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                **printer_device_info,
            )
            self._printer_device_map[printer_device.id] = printer_id

    async def _check_or_save_tokens(self) -> None:
        success = await self.anycubic_api.check_api_tokens()

        if not success:
            raise ConfigEntryAuthFailed("Authentication failed. Check credentials.")

        if self.anycubic_api.tokens_changed:
            store = Store[dict[str, Any]](self.hass, STORAGE_VERSION, STORAGE_KEY)
            await store.async_save(self.anycubic_api.get_auth_config_dict())

    async def _connect_mqtt_for_action_response(self) -> None:
        self._mqtt_last_action = int(time.time())
        await self._check_anycubic_mqtt_connection()
        if not await self.anycubic_api.mqtt_wait_for_connect():
            raise HomeAssistantError(
                "Anycubic MQTT Timed out waiting for connection, try manually enabling MQTT."
            )

    async def _async_setup(self) -> None:
        setup_retries = 0
        while setup_retries < API_SETUP_RETRIES + 1:
            try:
                await self._setup_anycubic_api_connection()
                await self._setup_anycubic_printer_objects()
                return
            except AnycubicAPIParsingError as error:
                if setup_retries >= API_SETUP_RETRIES:
                    raise ConfigEntryError(error) from error
                setup_retries += 1
                LOGGER.warning(
                    f"Error during Anycubic Cloud setup, retrying in {API_SETUP_RETRY_INTERVAL_SECONDS} seconds."
                )
                await asyncio.sleep(API_SETUP_RETRY_INTERVAL_SECONDS)

    async def get_anycubic_updates(self) -> bool:
        """Fetch data from AnycubicCloud."""

        if self._failed_updates >= MAX_FAILED_UPDATES:
            self._last_state_update = int(time.time()) + FAILED_UPDATE_DELAY
            self._failed_updates = 0
            return False

        self._last_state_update = int(time.time())

        try:
            await self._check_or_save_tokens()

            for printer_id, printer in self._anycubic_printers.items():
                await printer.update_info_from_api(True)

            self._failed_updates = 0

            await self._check_anycubic_mqtt_connection()

        except ConfigEntryAuthFailed:
            raise

        except AnycubicAPIParsingError as error:
            self._failed_updates += 1
            raise UpdateFailed(error) from error

        except AnycubicAPIError as error:
            self._failed_updates += 1
            raise UpdateFailed(error) from error

        except Exception as error:
            tb = traceback.format_exc()
            LOGGER.debug(f"Anycubic update error: {error}\n{tb}")
            self._failed_updates += 1
            raise UpdateFailed(error) from error

        self._last_state_update = int(time.time())

        return True

    def get_printer_for_id(
        self,
        printer_id: int | None,
    ) -> AnycubicPrinter | None:
        if printer_id is None or len(str(printer_id)) == 0:
            return None

        return self._anycubic_printers.get(int(printer_id))

    def get_printer_for_device_id(
        self,
        device_id: str | None,
    ) -> AnycubicPrinter | None:
        if self._printer_device_map is None:
            return None

        if device_id is None or len(str(device_id)) == 0:
            return None

        printer_id = self._printer_device_map.get(device_id)

        if not printer_id:
            return None

        return self._anycubic_printers.get(int(printer_id))

    async def refresh_cloud_files(self) -> None:
        self._cloud_file_list = await self.anycubic_api.get_user_cloud_files_data_object()

    async def force_state_update(self) -> None:
        self._last_state_update = None
        await self.async_refresh()
        self._last_state_update = int(time.time()) - DEFAULT_SCAN_INTERVAL + 10

    async def button_press_event(
        self,
        printer_id: int,
        event_key: str,
    ) -> None:
        printer = self.get_printer_for_id(printer_id)

        try:

            if printer and (
                event_key.startswith(ENTITY_ID_DRYING_START_PRESET_) or
                event_key.startswith(f"secondary_{ENTITY_ID_DRYING_START_PRESET_}")
            ):
                preset_duration, preset_temperature = get_drying_preset_from_entry_options(
                    self.entry.options,
                    event_key[-1],
                )
                if preset_duration is None or preset_temperature is None:
                    return

                if event_key.startswith(f"secondary_{ENTITY_ID_DRYING_START_PRESET_}"):
                    box_id = 1
                else:
                    box_id = 0

                await self._connect_mqtt_for_action_response()
                await printer.multi_color_box_drying_start(
                    duration=preset_duration,
                    target_temp=preset_temperature,
                    box_id=box_id,
                )

            elif printer and event_key == 'refresh_mqtt_connection':
                await self.refresh_anycubic_mqtt_connection()

            elif printer and event_key == 'request_file_list_cloud':
                await self._connect_mqtt_for_action_response()
                await self.refresh_cloud_files()

            elif printer and event_key == 'request_file_list_local':
                prev_file_list = printer.local_file_list_object
                await self._connect_mqtt_for_action_response()
                await printer.request_local_file_list()
                self.hass.create_task(
                    self._async_check_local_file_list_changed(prev_file_list, printer),
                    f"Anycubic coordinator {self.entry.entry_id} {printer.id} local file list check",
                )

            elif printer and event_key == 'request_file_list_udisk':
                await self._connect_mqtt_for_action_response()
                await printer.request_udisk_file_list()

            elif printer and event_key == 'drying_stop':
                await self._connect_mqtt_for_action_response()
                await printer.multi_color_box_drying_stop()

            elif printer and event_key == 'secondary_drying_stop':
                await self._connect_mqtt_for_action_response()
                await printer.multi_color_box_drying_stop(box_id=1)

            elif printer and event_key == 'pause_print':
                await self._connect_mqtt_for_action_response()
                await printer.pause_print()

            elif printer and event_key == 'resume_print':
                await self._connect_mqtt_for_action_response()
                await printer.resume_print()

            elif printer and event_key == 'cancel_print':
                await self._connect_mqtt_for_action_response()
                await printer.cancel_print()

            # elif printer and event_key == 'toggle_auto_feed':
            #     await printer.multi_color_box_toggle_auto_feed()

            # elif event_key == 'toggle_mqtt_connection':
            #     self._mqtt_manually_connected = not self._mqtt_manually_connected

            else:
                return

            await self.force_state_update()

        except AnycubicAPIError as ex:
            raise HomeAssistantError(ex) from ex

    async def fw_update_event(
        self,
        printer_id: int,
        event_key: str,
    ) -> None:
        printer = self.get_printer_for_id(printer_id)

        try:

            if printer and event_key == 'fw_version':
                await self._connect_mqtt_for_action_response()
                await printer.update_printer_firmware()

            elif printer and event_key == 'multi_color_box_fw_version':
                await self._connect_mqtt_for_action_response()
                await printer.update_printer_multi_color_box_firmware()

            elif printer and event_key == 'secondary_multi_color_box_fw_version':
                await self._connect_mqtt_for_action_response()
                await printer.update_printer_multi_color_box_firmware(box_id=1)

            else:
                return

            await self.force_state_update()

        except AnycubicAPIError as ex:
            raise HomeAssistantError(ex) from ex

    async def switch_on_event(
        self,
        printer_id: int,
        event_key: str,
    ) -> None:
        printer = self.get_printer_for_id(printer_id)

        if event_key == 'manual_mqtt_connection_enabled':
            self._mqtt_manually_connected = True
            self._anycubic_api.set_mqtt_log_all_messages(True)
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Anycubic",
                    "message": "MQTT Debug Logging is enabled. Incoming and outgoing MQTT messages are now logged at DEBUG level.",
                    "notification_id": "anycubic_mqtt_debug_logging",
                },
                blocking=False,
            )

        elif printer and event_key == 'multi_color_box_runout_refill':
            await self._connect_mqtt_for_action_response()
            await printer.multi_color_box_switch_on_auto_feed()

        elif printer and event_key == 'secondary_multi_color_box_runout_refill':
            await self._connect_mqtt_for_action_response()
            await printer.multi_color_box_switch_on_auto_feed(box_id=1)

        else:
            return

        await self.force_state_update()

    async def switch_off_event(
        self,
        printer_id: int,
        event_key: str,
    ) -> None:
        printer = self.get_printer_for_id(printer_id)

        if event_key == 'manual_mqtt_connection_enabled':
            self._mqtt_manually_connected = False
            self._anycubic_api.set_mqtt_log_all_messages(False)

        elif printer and event_key == 'multi_color_box_runout_refill':
            await self._connect_mqtt_for_action_response()
            await printer.multi_color_box_switch_off_auto_feed()

        elif printer and event_key == 'secondary_multi_color_box_runout_refill':
            await self._connect_mqtt_for_action_response()
            await printer.multi_color_box_switch_off_auto_feed(box_id=1)

        else:
            return

        await self.force_state_update()

    async def fan_set_event(
        self,
        printer_id: int,
        event_key: str,
        percentage: int,
    ) -> None:
        printer = self.get_printer_for_id(printer_id)

        try:
            if printer and event_key == 'fan_speed_pct':
                await self._connect_mqtt_for_action_response()
                await printer.change_print_setting_fan_speed_pct(int(percentage))
            elif printer and event_key == 'aux_fan_speed_pct':
                await self._connect_mqtt_for_action_response()
                await printer.change_print_setting_aux_fan_speed_pct(int(percentage))
            elif printer and event_key == 'box_fan_level':
                await self._connect_mqtt_for_action_response()
                await printer.change_print_setting_box_fan_level(int(percentage))
            else:
                return

            await self.force_state_update()

        except AnycubicAPIError as ex:
            raise HomeAssistantError(ex) from ex
