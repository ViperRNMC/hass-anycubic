import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entities = [
        AnycubicPrinterInfoSensor(coordinator),
        AnycubicNozzleTempSensor(coordinator),
        AnycubicHotbedTempSensor(coordinator),
        AnycubicPrintJobSensor(coordinator),
        AnycubicSlotsSensor(coordinator),
    ]
    async_add_entities(entities)


class AnycubicPrinterInfoSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic Printer Info"
        self._attr_unique_id = "anycubic_printer_info"

    @property
    def native_value(self):
        return self.coordinator.data.get("info", {}).get("data", {}).get("state")

    @property
    def extra_state_attributes(self):
        info = self.coordinator.data.get("info", {}).get("data", {})
        return {
            "model": info.get("model"),
            "ip": info.get("ip"),
            "version": info.get("version"),
            "fan_speed_pct": info.get("fan_speed_pct"),
            "aux_fan_speed_pct": info.get("aux_fan_speed_pct"),
            "box_fan_level": info.get("box_fan_level"),
        }
    
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


class AnycubicNozzleTempSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic Nozzle Temperature"
        self._attr_unique_id = "anycubic_nozzle_temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        temp = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp.get("curr_nozzle_temp")

    @property
    def extra_state_attributes(self):
        temp = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return {
            "target_nozzle_temp": temp.get("target_nozzle_temp")
        }
    
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


class AnycubicHotbedTempSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic Hotbed Temperature"
        self._attr_unique_id = "anycubic_hotbed_temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        temp = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp.get("curr_hotbed_temp")

    @property
    def extra_state_attributes(self):
        temp = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return {
            "target_hotbed_temp": temp.get("target_hotbed_temp")
        }
    
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


class AnycubicPrintJobSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic Print Status"
        self._attr_unique_id = "anycubic_print_status"

    @property
    def native_value(self):
        return self.coordinator.data.get("print", {}).get("__state__")

    @property
    def extra_state_attributes(self):
        print_data = self.coordinator.data.get("print", {}).get("data", {})
        return {
            "progress": print_data.get("progress"),
            "curr_layer": print_data.get("curr_layer"),
            "total_layers": print_data.get("total_layers"),
            "remain_time": print_data.get("remain_time"),
            "print_time": print_data.get("print_time"),
            "filename": print_data.get("filename"),
            "supplies_usage": print_data.get("supplies_usage"),
        }
    
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


class AnycubicSlotsSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Anycubic Slots"
        self._attr_unique_id = "anycubic_slots"

    @property
    def native_value(self):
        slots = self._get_slots()
        return len(slots) if slots else 0

    @property
    def extra_state_attributes(self):
        return {"slots": self._get_slots()}

    def _get_slots(self):
        boxes = self.coordinator.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
        all_slots = []
        for box in boxes:
            for slot in box.get("slots", []):
                all_slots.append({
                    "index": slot.get("index"),
                    "type": slot.get("type"),
                    "color": slot.get("color"),
                    "sku": slot.get("sku"),
                })
        return all_slots
    
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
