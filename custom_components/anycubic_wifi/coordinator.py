"""Coordinator for Anycubic integration data updates and MQTT handling."""
from datetime import timedelta
import logging
import re
from typing import Any
import copy
import json

from .const import (
    SENSOR_DEFINITIONS,
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    FAN_DEFINITIONS,
    SWITCH_DEFINITIONS,
    BUTTON_DEFINITIONS,
    LIGHT_DEFINITION,
    MULTI_COLOR_BOX_KEY,
    EXT_FILBOX_KEY,
)

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .helper.api import AnycubicAPI
from .helper.mqtt import AnycubicMQTT
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AnycubicDataUpdateCoordinator(DataUpdateCoordinator):

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
            all_defs.extend(SENSOR_DEFINITIONS or [])
            all_defs.extend(NUMBER_DEFINITIONS or [])
            all_defs.extend(SELECT_DEFINITIONS or [])
            all_defs.extend(FAN_DEFINITIONS or [])
            all_defs.extend(SWITCH_DEFINITIONS or [])
            all_defs.extend(BUTTON_DEFINITIONS or [])
            if LIGHT_DEFINITION:
                all_defs.append(LIGHT_DEFINITION)

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

            for d in definitions:
                # If this definition is per_box, expand it for each box
                if d.get("per_box"):
                    for box in boxes:
                        box_id = box.get("id")
                        if box_id is None:
                            continue

                        # Base per-box expansion
                        base = dict(d)
                        # Replace any {box_id} placeholders in string fields
                        for k, v in list(base.items()):
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
                else:
                    expanded.append(d)

            try:
                sample_keys = [e.get("key") for e in expanded][:20]
            except Exception:
                pass
            return expanded
        except Exception as err:
            _LOGGER.exception("expand_definitions failed: %s", err)
            return []