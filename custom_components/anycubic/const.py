"""Constants for the Anycubic integration.

This module centralises all entity definitions and small configuration
constants used by the integration. Keep comments and names concise and in
English for consistency.
"""
DOMAIN = "anycubic"
COORDINATOR = "coordinator"
MANUFACTURER = "Anycubic"
MODEL = "Kobra S1"
UNIT_LAYERS = "Layers"

# Connection mode — stored in config entry data
CONF_CONNECTION_MODE = "connection_mode"
CONNECTION_MODE_LAN = "lan"
CONNECTION_MODE_CLOUD = "cloud"

# Cloud-specific config entry keys
CONF_USER_TOKEN = "user_token"
CONF_USER_AUTH_MODE = "user_auth_mode"
CONF_USER_DEVICE_ID = "user_device_id"
CONF_PRINTER_ID_LIST = "printer_id_list"

# Cloud storage
STORAGE_KEY = "anycubic_cloud_tokens"
STORAGE_VERSION = 1

# Cloud options keys
CONF_MQTT_CONNECT_MODE = "mqtt_connect_mode"
CONF_DEBUG_DEPRECATED = "debug"
CONF_DEBUG_MQTT_MSG = "debug_mqtt_msg"
CONF_DEBUG_API_CALLS = "debug_api_calls"
CONF_DRYING_PRESET_DURATION_ = "drying_preset_duration_"
CONF_DRYING_PRESET_TEMPERATURE_ = "drying_preset_temperature_"
ENTITY_ID_DRYING_START_PRESET_ = "drying_start_preset_"
MAX_DRYING_PRESETS = 4

# Cloud update loop timing
API_SETUP_RETRIES = 3
API_SETUP_RETRY_INTERVAL_SECONDS = 10
DEFAULT_SCAN_INTERVAL = 60
MQTT_SCAN_INTERVAL = 15
FAILED_UPDATE_DELAY = DEFAULT_SCAN_INTERVAL * 4
MAX_FAILED_UPDATES = 3
MQTT_IDLE_DISCONNECT_SECONDS = 60 * 15
MQTT_ACTION_RESPONSE_ALIVE_SECONDS = 60 * 5
MQTT_REFRESH_INTERVAL = 60 * 5
PRINT_JOB_STARTED_UPDATE_DELAY = 5

import logging
from enum import IntEnum

LOGGER = logging.getLogger(__package__)


class PrinterEntityType(IntEnum):
    GLOBAL = 1
    PRINTER = 2
    FDM = 3
    LCD = 4
    ACE_PRIMARY = 5
    ACE_SECONDARY = 6
    DRY_PRESET_PRIMARY = 7
    DRY_PRESET_SECONDARY = 8


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
    "name": "External Filament Rack",
    "manufacturer": MANUFACTURER,
    "model": "External Filament Rack",
}

# Short, local translation table for common non-ASCII device messages.
# Keep this small and local to avoid network calls; add entries as needed.
MSG_TRANSLATIONS = {
    # Chinese -> English
    "耗材不足": "Insufficient supplies",
    "设备忙": "Device busy",
    "温度过高": "Temperature too high",
    "用户发起": "User initiated"
}
