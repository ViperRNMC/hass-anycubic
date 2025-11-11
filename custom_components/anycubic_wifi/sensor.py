"""Anycubic sensor platform for Home Assistant."""

import logging
from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLA_COLOR_MAP = {
    (33, 39, 33): "Dark Green",
    (135, 206, 235): "Sky Blue",
    (0, 0, 0): "Black",
    (255, 255, 255): "White",
    (255, 0, 0): "Red",
    (0, 255, 0): "Green",
    (0, 0, 255): "Blue",
    (255, 255, 0): "Yellow",
    (255, 165, 0): "Orange",
    (128, 0, 128): "Purple",
    (255, 192, 203): "Pink",
    (165, 42, 42): "Brown",
    (192, 192, 192): "Silver",
    (255, 215, 0): "Gold",
}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic sensor entities from config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    entities = [
        AnycubicPrinterInfoSensor(coordinator),
        AnycubicNozzleTempSensor(coordinator),
        AnycubicHotbedTempSensor(coordinator),
        AnycubicPrintJobSensor(coordinator),
        AnycubicModelSensor(coordinator),
        AnycubicIpSensor(coordinator),
        AnycubicFirmwareSensor(coordinator),
        AnycubicPrintProgressSensor(coordinator),
        AnycubicPrintTimeSensor(coordinator),
    ]
    # Add Ace Pro Box sensors if present
    boxes = coordinator.data.get("multiColorBox", {}).get("data", {}).get("multi_color_box", [])
    for box in boxes:
        entities.append(AceProBoxTempSensor(coordinator, box))
        entities.append(AceProBoxDryingSensor(coordinator, box))
        entities.append(AceProBoxAutoFeedSensor(coordinator, box))
        entities.append(AceProBoxFeedStatusSensor(coordinator, box))
        entities.append(AceProBoxLoadedSlotSensor(coordinator, box))
        entities.append(AceProBoxModelIdSensor(coordinator, box))
        entities.append(AceProBoxStatusSensor(coordinator, box))
        # Add Ace Pro Box Slot sensors (0-3)
        for i in range(4):
            entities.append(AceProBoxSlotSensor(coordinator, box, i))
    async_add_entities(entities)

# Helper function to convert minutes to HH:MM
def minutes_to_hhmm(minutes):
    """Convert minutes to HH:MM format, or 'Onbekend' if not valid."""
    if minutes is None:
        return "Onbekend"
    try:
        minutes = int(minutes)
    except Exception:
        return str(minutes)
    if minutes < 1:
        return "Onbekend"
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}"

# Printer sensors
class AnycubicPrinterInfoSensor(CoordinatorEntity, SensorEntity):
    """Printer info sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Printer Info"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_printer_info_{serial}"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self):
        return self.coordinator.data.get("info", {}).get("data", {}).get("state")

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

class AnycubicModelSensor(CoordinatorEntity, SensorEntity):
    """Printer model sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Model"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_printer_model_{serial}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:printer-3d"

    @property
    def native_value(self):
        return self.coordinator.data.get("info", {}).get("data", {}).get("model")

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

class AnycubicIpSensor(CoordinatorEntity, SensorEntity):
    """Printer IP sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "IP"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_printer_ip_{serial}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:ip-network"

    @property
    def native_value(self):
        return self.coordinator.data.get("info", {}).get("data", {}).get("ip")

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

class AnycubicFirmwareSensor(CoordinatorEntity, SensorEntity):
    """Printer firmware sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Firmware"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_printer_firmware_{serial}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:chip"

    @property
    def native_value(self):
        return self.coordinator.data.get("info", {}).get("data", {}).get("version")

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
    """Nozzle temperature sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Nozzle Temperature"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_nozzle_temperature_{serial}"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("curr_nozzle_temp") is not None:
            return temp_report.get("curr_nozzle_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("curr_nozzle_temp")

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
    """Hotbed temperature sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Hotbed Temperature"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_hotbed_temperature_{serial}"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("curr_hotbed_temp") is not None:
            return temp_report.get("curr_hotbed_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("curr_hotbed_temp")

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

class AnycubicTargetNozzleTempSensor(CoordinatorEntity, SensorEntity):
    """Target nozzle temperature sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Target Nozzle Temperature"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_target_nozzle_temperature_{serial}"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("target_nozzle_temp") is not None:
            return temp_report.get("target_nozzle_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("target_nozzle_temp")

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

class AnycubicTargetHotbedTempSensor(CoordinatorEntity, SensorEntity):
    """Target hotbed temperature sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Target Hotbed Temperature"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_target_hotbed_temperature_{serial}"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self):
        temp_report = self.coordinator.data.get("tempature", {}).get("data", {})
        if temp_report.get("target_hotbed_temp") is not None:
            return temp_report.get("target_hotbed_temp")
        temp_info = self.coordinator.data.get("info", {}).get("data", {}).get("temp", {})
        return temp_info.get("target_hotbed_temp")

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
    """Print job status sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Print Status"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_print_status_{serial}"
        self._attr_icon = "mdi:printer-3d"

    @property
    def native_value(self):
        info_data = self.coordinator.data.get("info", {}).get("data", {})
        project = info_data.get("project", {})
        state = project.get("state")
        if state:
            return state
        return None

    @property
    def extra_state_attributes(self):
        print_data = self.coordinator.data.get("print", {}).get("data", {})
        return {
            # "progress": print_data.get("progress"),
            "curr_layer": print_data.get("curr_layer"),
            "total_layers": print_data.get("total_layers"),
            # "remain_time": print_data.get("remain_time"),
            # "print_time": print_data.get("print_time"),
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

class AnycubicPrintProgressSensor(CoordinatorEntity, SensorEntity):
    """Print progress sensor."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Print Progress"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_print_progress_{serial}"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:progress-clock"

    @property
    def native_value(self):
        project = self.coordinator.data.get("info", {}).get("data", {}).get("project", {})
        progress = project.get("progress")
        if progress is not None:
            return progress
        return None

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

# Print time sensor for print_time and remain_time
class AnycubicPrintTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for print_time and remain_time in HH:MM format."""
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Print Time"
        serial = self.coordinator.data.get("info", {}).get("data", {}).get("serial", "default")
        self._attr_unique_id = f"anycubic_print_time_{serial}"
        self._attr_icon = "mdi:clock-outline"

    @property
    def native_value(self):
        project = self.coordinator.data.get("info", {}).get("data", {}).get("project", {})
        print_time = project.get("print_time")
        remain_time = project.get("remain_time")
        # Show as "print_time / remain_time" in HH:MM
        return f"{minutes_to_hhmm(print_time)} / {minutes_to_hhmm(remain_time)}"

    @property
    def extra_state_attributes(self):
        project = self.coordinator.data.get("info", {}).get("data", {}).get("project", {})
        return {
            "print_time": minutes_to_hhmm(project.get("print_time")),
            "remain_time": minutes_to_hhmm(project.get("remain_time")),
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

# Box sensors
class AceProBoxTempSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box temperature sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Temperature"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_temp_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:thermometer"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        return self._box.get("temp")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

class AceProBoxDryingSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box drying status sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Drying Status"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_drying_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:weather-windy"


    @property
    def native_value(self):
        ds = self._box.get("drying_status", {})
        status = ds.get("status")
        target_temp = ds.get("target_temp")
        status_map = {
            0: "Not active",
            1: "Drying",
            2: "Completed",
            3: "Error",
            4: "Paused",
        }
        # Always map state from status code
        return status_map.get(status, f"Unknown ({status})")

    @property
    def extra_state_attributes(self):
            ds = self._box.get("drying_status", {})
            target_temp = ds.get("target_temp")
            duration = ds.get("duration")
            remain_time = ds.get("remain_time")

            attrs = {
                "target_temp": target_temp if target_temp else "No target",
            }
            if duration is not None:
                attrs["total_drying_time"] = minutes_to_hhmm(duration)
            if remain_time is not None:
                attrs["remaining_drying_time"] = minutes_to_hhmm(remain_time)
            return attrs

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

class AceProBoxAutoFeedSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box auto feed sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Auto Feed"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_autofeed_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:autorenew"

    @property
    def native_value(self):
        return self._box.get("auto_feed")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

# --- Box extra sensors ---
class AceProBoxFeedStatusSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box Feed Status sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Feed Status"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_feedstatus_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:progress-check"

    @property
    def native_value(self):
        return self._box.get("feed_status", {}).get("current_status")

    @property
    def extra_state_attributes(self):
        fs = self._box.get("feed_status", {})
        return {
            "code": fs.get("code"),
            "type": fs.get("type"),
            "slot_index": fs.get("slot_index"),
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

class AceProBoxLoadedSlotSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box Loaded Slot sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Loaded Slot"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_loadedslot_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:tray"

    @property
    def native_value(self):
        return self._box.get("loaded_slot")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

class AceProBoxModelIdSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box Model ID sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Model ID"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_modelid_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:identifier"

    @property
    def native_value(self):
        return self._box.get("model_id")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }

class AceProBoxStatusSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box Status sensor."""
    def __init__(self, coordinator, box):
        super().__init__(coordinator)
        self._box = box
        self._attr_name = "Ace Pro Box Status"
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_unique_id = f"ace_pro_box_status_{serial}_{box.get('id', 0)}"
        self._attr_icon = "mdi:checkbox-marked-circle"

    @property
    def native_value(self):
        return self._box.get("status")

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }


# Ace Pro Box Slot sensor for filament and color
class AceProBoxSlotSensor(CoordinatorEntity, SensorEntity):
    """Ace Pro Box Slot sensor for filament and color."""
    def __init__(self, coordinator, box, index):
        super().__init__(coordinator)
        self._box = box
        self._index = index
        serial = coordinator.data.get("info", {}).get("data", {}).get("serial", box.get('id', 0))
        self._attr_name = f"Slot {index}"
        self._attr_unique_id = f"ace_pro_box_slot_{index}_{serial}_{box.get('id', 0)}"
        # Icon will be set dynamically in property
        self._icon_loaded = "mdi:tray-full"
        self._icon_empty = "mdi:tray"

    @property
    def icon(self):
        slot = self._get_slot()
        if slot:
            if slot.get("status") == 5:
                return self._icon_loaded
            if slot.get("status") == 4:
                return self._icon_empty
        return self._icon_empty

    @property
    def native_value(self):
        slot = self._get_slot()
        if slot:
            if slot.get("status") == 4:
                return "Empty"
            slot_type = slot.get("type", "Unknown")
            rgb = tuple(slot.get("color", [0,0,0]))
            color_name = PLA_COLOR_MAP.get(rgb, str(rgb))
            return f"{slot_type} ({color_name})"
        return None

    @property
    def extra_state_attributes(self):
        slot = self._get_slot()
        attrs = {}
        if slot:
            status = slot.get("status")
            status_map = {
                0: "Unknown",
                1: "Inserting",
                2: "Removing",
                3: "Error",
                4: "Empty",
                5: "Loaded",
            }
            attrs["status"] = status_map.get(status, f"Unknown ({status})")
            attrs["sku"] = slot.get("sku", "")
            if status == 5:
                rgb = tuple(slot.get("color", [0,0,0]))
                color_name = PLA_COLOR_MAP.get(rgb, str(rgb))
                attrs["color"] = color_name
            else:
                attrs["color"] = None
        return attrs

    def _get_slot(self):
        for slot in self._box.get("slots", []):
            if slot.get("index") == self._index:
                return slot
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "anycubic_ace_pro")},
            "name": "Ace Pro",
            "manufacturer": "Anycubic",
            "model": "Ace Pro",
        }