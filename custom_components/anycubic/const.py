"""Constants for the Anycubic integration.

This module centralises all entity definitions and small configuration
constants used by the integration. Keep comments and names concise and in
English for consistency.
"""
DOMAIN = "anycubic"
MANUFACTURER = "Anycubic"
MODEL = "Kobra S1"

# Connection modes
CONNECTION_MODE_LAN = "lan"
CONNECTION_MODE_CLOUD = "cloud"

# Cloud config entry keys
CONF_USER_TOKEN = "user_token"
CONF_USER_AUTH_MODE = "user_auth_mode"
CONF_USER_DEVICE_ID = "user_device_id"
CONF_PRINTER_ID = "printer_id"
CONF_CONNECTION_MODE = "connection_mode"

# Cloud auth mode values stored in config entries
CLOUD_AUTH_MODE_WEB = "web"
CLOUD_AUTH_MODE_SLICER = "slicer"
CLOUD_AUTH_MODE_ANDROID = "android"

# Device type constants
DEVICE_TYPE_PRINTER = "printer"
DEVICE_TYPE_ACE_PRO = "ace_pro"
DEVICE_TYPE_EXTFILBOX = "extfilbox"

ACE_PRO_DEVICE_ID_FORMAT = "{entry_id}_ace_pro_box_{box_id}"
EXTFILBOX_DEVICE_ID_FORMAT = "{entry_id}_extfilbox"

# Top-level keys used in coordinator.data
MULTI_COLOR_BOX_KEY = "multiColorBox"
EXT_FILBOX_KEY = "extfilbox"
VIDEO_KEY = "video"

# Camera default name
CAMERA_NAME = "Printer Camera"

# Filament geometry settings
# Change `FILAMENT_DIAMETER_MM` if you use a different filament diameter
FILAMENT_DIAMETER_MM = 1.75
# Typical material density used for estimates (g/cm^3). Common values:
# PLA ~= 1.24, PETG ~= 1.27, ABS ~= 1.04
FILAMENT_DENSITY_G_CM3 = 1.24

# Base device info pieces to be composed with per-device identifiers
ACE_PRO_DEVICE_BASE = {
    "name": "Anycubic Ace Pro",
    "manufacturer": MANUFACTURER,
    "model": "Ace Pro",
}

EXTFILBOX_DEVICE_BASE = {
    "name": "Anycubic External Filament Rack",
    "manufacturer": MANUFACTURER,
    "model": "External Filament Rack",
}

# Light entity definition for the chamber light
LIGHT_DEFINITION = {
    "name": "Chamber Light",
    "key": "chamber_printer",
    "type_id": 2,
    "icon": "mdi:lightbulb",
}

# Button entities for homing and print control
BUTTON_DEFINITIONS = [
    # Homing buttons
    {
        "name": "Home All",
        "key": "home_all",
        "type": "axis",
        "action": "move",
        "axis": 5,
        "icon": "mdi:axis-arrow",
    },
    {
        "name": "Home XY",
        "key": "home_xy",
        "type": "axis",
        "action": "move",
        "axis": 4,
        "icon": "mdi:axis-arrow",
    },
    {
        "name": "Home Z",
        "key": "home_z",
        "type": "axis",
        "action": "move",
        "axis": 3,
        "icon": "mdi:axis-arrow",
    },
    # Print control buttons
    {
        "name": "Print Stop",
        "key": "print_stop",
        "type": "print",
        "action": "stop",
        "icon": "mdi:stop",
    },
    # Separate pause and resume buttons
    {
        "name": "Print Pause",
        "key": "print_pause",
        "type": "print",
        "action": "pause",
        "icon": "mdi:pause",
    },
    {
        "name": "Print Resume",
        "key": "print_resume",
        "type": "print",
        "action": "resume",
        "icon": "mdi:play",
    },
]

# Select definitions (print speed modes)
SELECT_DEFINITIONS = [
    {
        "name": "Speed",
        "key": "print_speed_mode",
        "icon": "mdi:run",
        "options": ["silent", "standard", "sport"],
        # backend value mapping (index or code expected by device)
        # Note: device uses inverted codes for silent/standard on some firmware
        # Swap 0/1 so selecting 'silent' sends the value the device expects
        "value_map": {"silent": 1, "standard": 0, "sport": 2},
    }
]

# Switch entities for Ace Pro features
SWITCH_DEFINITIONS = [
    {
        "name": "Drying",
        "key": "ace_pro_drying",
        "type": "multiColorBox",
        "action_on": "setDry",
        "action_off": "setDry",
        "data_template_on": {"multi_color_box": [{"id": "{box_id}", "drying_status": {"status": 1, "target_temp": "{target_temp}", "duration": "{duration}"}}]},
        "data_template_off": {"multi_color_box": [{"id": "{box_id}", "drying_status": {"status": 0}}]},
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
    },
    {
        "name": "Auto Feed",
        "key": "ace_pro_auto_feed",
        "type": "multiColorBox",
        "action_on": "setAutoFeed",
        "action_off": "setAutoFeed",
        "data_template_on": {"multi_color_box": [{"id": "{box_id}", "auto_feed": 1}]},
        "data_template_off": {"multi_color_box": [{"id": "{box_id}", "auto_feed": 0}]},
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
    },
]

# Fan entities (definitions drive the single generic FanEntity)
FAN_DEFINITIONS = [
    {
        "name": "Main Fan",
        "key": "main",
        "icon": "mdi:fan",
        "data_key": "fan_speed_pct",
    },
    {
        "name": "Aux Fan",
        "key": "aux",
        "icon": "mdi:fan",
        "data_key": "aux_fan_speed_pct",
    },
    {
        "name": "Box Fan",
        "key": "box",
        "icon": "mdi:fan",
        "data_key": "box_fan_level",
    },
]

# Number entities for target temperatures (definitions drive the single generic NumberEntity)
NUMBER_DEFINITIONS = [
    {
        "name": "Target Nozzle Temperature",
        "key": "target_nozzle_temp",
        "data_key": "target_nozzle_temp",
        "min": 185,
        "max": 320,
        "icon": "mdi:printer-3d-nozzle",
    },
    {
        "name": "Target Hotbed Temperature",
        "key": "target_hotbed_temp",
        "data_key": "target_hotbed_temp",
        "min": 35,
        "max": 120,
        "icon": "mdi:heating-coil",
    },
    # Ace Pro box drying controls: template definitions. These will be
    # expanded per detected box by the coordinator (placeholders like
    # {box_id} are replaced with the real box id at runtime).
    {
        "name": "Drying Target",
        "key": "ace_pro_drying_target",
        "min": 35,
        "max": 55,
        "unit": "°C",
        "kind": "drying_target",
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
    },
    {
        "name": "Drying Duration",
        "key": "ace_pro_drying_duration",
        "min": 1,
        "max": 1440,
        "unit": "min",
        "kind": "drying_duration",
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
    },
]

# Sensor entity definitions
SENSOR_DEFINITIONS = [
    {
        "name": "Printer Info",
        "key": "printer_info",
        "data_path": ("info", "data", "state"),
        "icon": "mdi:information-outline",
    },
    {
        "name": "Nozzle Temperature",
        "key": "nozzle_temp",
        "data_path": ("tempature", "data", "curr_nozzle_temp"),
        "unit": "°C",
        "icon": "mdi:thermometer",
    },
    {
        "name": "Hotbed Temperature",
        "key": "hotbed_temp",
        "data_path": ("tempature", "data", "curr_hotbed_temp"),
        "unit": "°C",
        "icon": "mdi:thermometer",
    },
    {
        "name": "Print Status",
        "key": "print_status",
        "data_path": ("info", "data", "project", "state"),
        "icon": "mdi:printer-3d",
    },
    {
        "name": "Print Progress",
        "key": "print_progress",
        "data_path": ("info", "data", "project", "progress"),
        "unit": "%",
        "icon": "mdi:progress-clock",
    },
    {
        "name": "Print Current Layer",
        "key": "print_curr_layer",
        "data_path": ("print", "data", "curr_layer"),
        "icon": "mdi:layers",
    },
    {
        "name": "Print Filename",
        "key": "print_filename",
        "data_path": ("print", "data", "filename"),
        "icon": "mdi:file-document",
    },
    {
        "name": "Print Time",
        "key": "print_time",
        "data_path": ("print", "data", "print_time"),
        "icon": "mdi:timer",
        "formatter": "_minutes_to_hhmm",
    },
    {
        "name": "Print Remaining Time",
        "key": "print_remain_time",
        "data_path": ("print", "data", "remain_time"),
        "icon": "mdi:timer-off",
        "formatter": "_minutes_to_hhmm",
    },
    {
        "name": "Print ETA",
        "key": "job_eta",
        "data_path": ("print", "data", "remain_time"),
        "icon": "mdi:timer-outline",
        "formatter": "_minutes_to_hhmm",
    },
    {
        "name": "Print Z Thickness",
        "key": "job_z_thickness",
        "data_path": ("print", "data", "z_thickness"),
        "unit": "mm",
        "icon": "mdi:axis-z-arrow",
    },
    {
        "name": "Print Model Name",
        "key": "print_model_name",
        "data_path": ("print", "data", "source_info", "models", 0, "name"),
        "icon": "mdi:file-outline",
    },
    {
        "name": "Print Supplies Usage",
        "key": "print_supplies_usage",
        "data_path": ("print", "data", "supplies_usage"),
        "icon": "mdi:cube-scan",
        "unit": "g",
    },
    {
        "name": "Print Total Layers",
        "key": "print_total_layers",
        "data_path": ("print", "data", "total_layers"),
        "icon": "mdi:layers",
    },
    # Ace Pro box sensors (templates expanded per detected box)
    {
        "name": "Temperature",
        "key": "{box_id}_temp",
        "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"),
        "data_field": "temp",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
        },
        {
        "name": "Loaded",
        "key": "ace_pro_box_{box_id}_loaded",
        "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"),
        "data_field": "loaded_slot",
        "icon": "mdi:folder-arrow-right",
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
        },
        {
        "name": "Slot {slot_index}",
        "key": "ace_pro_box_{box_id}_slot_{slot_index}",
        "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"),
        "slot_index": "{slot_index}",
        "icon": "mdi:tray",
        "device_type": DEVICE_TYPE_ACE_PRO,
        "per_box": True,
        "per_slot": True,
        },
    # External Filament Rack 
    {
        "name": "Loaded",
        "key": "extfilbox_loaded",
        "data_path": (EXT_FILBOX_KEY, "data", "loaded"),
        "icon": "mdi:package-variant-closed",
        "device_type": DEVICE_TYPE_EXTFILBOX,
    },
    {
        "name": "Slot",
        "key": "extfilbox_slot",
        "data_path": (EXT_FILBOX_KEY, "data", "multi_color_box", 0),
        "icon": "mdi:tray",
        "device_type": DEVICE_TYPE_EXTFILBOX,
        "per_box": False,
        "per_slot": False,
    },
]


# Binary sensor entity definitions
BINARY_DEFINITIONS = [
    {
        "name": "Printer Online",
        "key": "printer_online",
        "type": "printer_online",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
    },
    {
        "name": "Print Failed",
        "key": "job_failed",
        "type": "job_failed",
        "device_class": "problem",
        "entity_category": "diagnostic",
    },
    {
        "name": "Print Problem",
        "key": "print_problem",
        "type": "print_problem",
        "device_class": "problem",
        "entity_category": "diagnostic",
    },
    {
        "name": "Nozzle Heating",
        "key": "nozzle_heating",
        "type": "nozzle_heating",
        "device_class": "heat",
        "icon": "mdi:printer-3d-nozzle-heat",
    },
    {
        "name": "Bed Heating",
        "key": "bed_heating",
        "type": "bed_heating",
        "device_class": "heat",
    },
]

# Short, local translation table for common non-ASCII device messages.
# Keep this small and local to avoid network calls; add entries as needed.
MSG_TRANSLATIONS = {
    # Chinese -> English
    "耗材不足": "Insufficient supplies",
    "设备忙": "Device busy",
    "温度过高": "Temperature too high",
    "用户发起": "User initiated"
}
