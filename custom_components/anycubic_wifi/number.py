"""Anycubic number platform for Home Assistant."""

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

class AnycubicTargetNozzleTempNumber(CoordinatorEntity, NumberEntity):
    """Number entity for target nozzle temperature."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_name = "Target Nozzle Temperature"
        self._attr_unique_id = f"anycubic_target_nozzle_temp_{serial}"
        self._attr_icon = "mdi:thermometer"
        self._attr_native_min_value = 185
        self._attr_native_max_value = 320
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("target_nozzle_temp") is not None:
            return temp_report.get("target_nozzle_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("target_nozzle_temp")

    async def async_set_native_value(self, value):
        # Example MQTT publish logic (adjust topic and payload as needed)
        payload = {
            "type": "tempature",
            "action": "set",
            "target_nozzle_temp": int(value),
        }
        topic = f"anycubic/anycubicCloud/v1/printer/public/{{printer_id}}/{{serial}}/tempature/set"
        # Replace printer_id and serial with actual values
        printer_id = self.coordinator.data.get("info", {}).get("data", {}).get("printer_id", "")
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "")
        topic = topic.replace("{printer_id}", str(printer_id)).replace("{serial}", str(serial))
        # Publish via coordinator.mqtt.publish_json
        if getattr(self.coordinator, "mqtt", None):
            self.coordinator.mqtt.publish_json(topic, payload)
        else:
            import logging
            logging.getLogger(__name__).warning("No mqtt instance found on coordinator")

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

class AnycubicTargetHotbedTempNumber(CoordinatorEntity, NumberEntity):
    """Number entity for target hotbed temperature."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_name = "Target Hotbed Temperature"
        self._attr_unique_id = f"anycubic_target_hotbed_temp_{serial}"
        self._attr_icon = "mdi:thermometer"
        self._attr_native_min_value = 35
        self._attr_native_max_value = 120
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("target_hotbed_temp") is not None:
            return temp_report.get("target_hotbed_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("target_hotbed_temp")

    async def async_set_native_value(self, value):
        # Example MQTT publish logic (adjust topic and payload as needed)
        payload = {
            "type": "tempature",
            "action": "set",
            "target_hotbed_temp": int(value),
        }
        topic = f"anycubic/anycubicCloud/v1/printer/public/{{printer_id}}/{{serial}}/tempature/set"
        printer_id = self.coordinator.data.get("info", {}).get("data", {}).get("printer_id", "")
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "")
        topic = topic.replace("{printer_id}", str(printer_id)).replace("{serial}", str(serial))
        if getattr(self.coordinator, "mqtt", None):
            self.coordinator.mqtt.publish_json(topic, payload)
        else:
            import logging
            logging.getLogger(__name__).warning("No mqtt instance found on coordinator")

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

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entities = [
        AnycubicTargetNozzleTempNumber(coordinator),
        AnycubicTargetHotbedTempNumber(coordinator),
    ]
    async_add_entities(entities)
