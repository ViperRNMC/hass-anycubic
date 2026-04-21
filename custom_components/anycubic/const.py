"""Constants for the Anycubic integration.

Centralizes all configuration, device, cloud API, and entity constants.
Organized by functional category for maintainability.
"""

from __future__ import annotations

import re
from enum import Enum, IntEnum, StrEnum


class HTTP_METHODS(Enum):
    """HTTP method enum for API endpoints."""
    GET = 1
    POST = 2
    PUT = 3


class AnycubicAPIEndpoint:
    """API endpoint with method and path."""
    __slots__ = ("_method", "_endpoint")

    def __init__(
        self,
        method: HTTP_METHODS,
        endpoint: str,
    ) -> None:
        self._method: HTTP_METHODS = method
        self._endpoint: str = endpoint

    @property
    def method(self) -> HTTP_METHODS:
        return self._method

    @property
    def endpoint(self) -> str:
        return self._endpoint

# ============================================================================
# CORE INTEGRATION
# ============================================================================

DOMAIN = "anycubic"
MANUFACTURER = "Anycubic"
MODEL = "Kobra S1"

# Connection modes
# Use simple canonical values used across the codebase and config flow.
CONNECTION_MODE_LAN = "lan"
CONNECTION_MODE_CLOUD = "cloud"

# ============================================================================
# CONFIG ENTRY KEYS
# ============================================================================
# Note: cloud auth mode option keys are intentionally referenced as literals
# in the config flow to ensure Home Assistant picks up translation keys
# from the `translations/*.json` files. Do not reintroduce these constants
# unless you intend to use them across multiple modules.

# ============================================================================
# DEVICE TYPES & IDENTIFIERS
# ============================================================================

DEVICE_TYPE_ACE_PRO = "ace_pro"
DEVICE_TYPE_EXTFILBOX = "extfilbox"

# Coordinator data keys
MULTI_COLOR_BOX_KEY = "multiColorBox"
VIDEO_KEY = "video"

# Camera default name
CAMERA_NAME = "Printer Camera"

# Device base info for composition
ACE_PRO_DEVICE_BASE = {
    "name": "Ace Pro",
    "manufacturer": MANUFACTURER,
    "model": "Ace Pro",
}

EXTFILBOX_DEVICE_BASE = {
    "name": "External Filament Rack",
    "manufacturer": MANUFACTURER,
    "model": "External Filament Rack",
}

# ============================================================================
# FILAMENT & MATERIAL
# ============================================================================

FILAMENT_DIAMETER_MM = 1.75
FILAMENT_DENSITY_G_CM3 = 1.24

# ============================================================================
# CLOUD API ENDPOINTS
# ============================================================================


class API_ENDPOINT:
    user_store = AnycubicAPIEndpoint(HTTP_METHODS.POST, "/work/index/getUserStore")
    lock_storage_space = AnycubicAPIEndpoint(
        HTTP_METHODS.POST, "/v2/cloud_storage/lockStorageSpace"
    )
    unlock_storage_space = AnycubicAPIEndpoint(
        HTTP_METHODS.POST, "/v2/cloud_storage/unlockStorageSpace"
    )
    new_file_upload = AnycubicAPIEndpoint(
        HTTP_METHODS.POST, "/v2/profile/newUploadFile"
    )
    delete_cloud_file = AnycubicAPIEndpoint(
        HTTP_METHODS.POST, "/work/index/delFiles"
    )
    user_files = AnycubicAPIEndpoint(HTTP_METHODS.POST, "/work/index/files")
    user_info = AnycubicAPIEndpoint(HTTP_METHODS.GET, "/user/profile/userInfo")
    auth_sig_token = AnycubicAPIEndpoint(HTTP_METHODS.POST, "/v3/public/loginWithAccessToken")
    printer_info = AnycubicAPIEndpoint(HTTP_METHODS.GET, "/v2/printer/info")
    printer_get_printers = AnycubicAPIEndpoint(
        HTTP_METHODS.GET, "/work/printer/getPrinters"
    )
    project_info = AnycubicAPIEndpoint(HTTP_METHODS.GET, "/v2/project/info")
    project_get_projects = AnycubicAPIEndpoint(
        HTTP_METHODS.GET, "/work/project/getProjects"
    )
    project_gcode_info_fdm = AnycubicAPIEndpoint(
        HTTP_METHODS.GET, "/work/gcode/infoFdm"
    )
    send_order = AnycubicAPIEndpoint(HTTP_METHODS.POST, "/work/operation/sendOrder")


# ============================================================================
# CLOUD API ENUMS
# ============================================================================


class AnycubicFeedType(IntEnum):
    Feed = 1
    Retract = 2
    Finish = 3


class AnycubicPrintStatus(IntEnum):
    Printing = 1
    Complete = 2
    Cancelled = 3
    Downloading = 4
    Checking = 5
    Preheating = 6
    Slicing = 7


class AnycubicOrderID(IntEnum):
    START_PRINT = 1
    PAUSE_PRINT = 2
    RESUME_PRINT = 3
    STOP_PRINT = 4
    PRINT_SETTINGS = 6
    IGNORE = 11
    DETECT = 12
    STOP_PRINT_FORCE = 44
    LIST_UDISK_FILES = 101
    DELETE_UDISK_FILE = 102
    LIST_LOCAL_FILES = 103
    DELETE_LOCAL_FILE = 104
    MOVE_AXLE = 201
    MOVE_AXLE_TO_COORDINATES = 202
    START_EXPOSURE = 301
    CANCEL_EXPOSURE = 302
    START_RESIDUAL = 501
    CANCEL_RESIDUAL = 502
    SET_DEVICE_SELF_TEST = 601
    GET_DEVICE_SELF_TEST = 602
    SET_AUTO_OPERATION = 701
    GET_AUTO_OPERATION = 702
    RESET_RELEASE_FILM = 801
    GET_RELEASE_FILM = 802
    SET_PRINT_STATUS_FREE = 901
    CAMERA_CLOSE = 1002
    MULTI_COLOR_BOX_DRY = 1207
    FEED_FILAMENT = 1208
    FEED_FILAMENT_FINISH = 1209
    MULTI_COLOR_BOX_REFRESH_SLOT = 1210
    MULTI_COLOR_BOX_SET_SLOT = 1211
    MULTI_COLOR_BOX_AUTO_FEED = 1212
    MOVE_AXLE_TURN_OFF = 1213
    FILAMENT_CONTROL = 1215
    FEED_RESIN = 1224
    M7_AUTO_OPERATION = 1225
    CYCLIC_CLEANING = 1226
    SET_AUTO_FEED_INFO = 1227
    GET_M7_AUTO_OPERATION = 1228
    EXTFILBOX = 1229
    GET_EXTFILBOX_INFO = 1230
    QUERY_PERIPHERALS = 1231
    GET_LIGHT_STATUS = 1232
    SET_LIGHT_STATUS = 1233


class AnycubicFunctionID(IntEnum):
    AXLE_MOVEMENT = 1
    FILE_MANAGER = 2
    EXPOSURE_TEST = 3
    LCD_PEER_VIDEO = 7
    FDM_AXIS_MOVE = 13
    FDM_PEER_VIDEO = 22
    DEVICE_STARTUP_SELF_TEST = 26
    PRINT_STARTUP_SELF_TEST = 27
    AUTOMATIC_OPERATION = 28
    RESIDUE_CLEAN = 29
    NOVICE_GUIDE = 30
    RELEASE_FILM = 31
    TASK_MODE = 32
    LCD_INTELLIGENT_MATERIALS_BOX = 33
    LCD_AUTO_OUT_IN_MATERIALS = 34
    M7PRO_AUTOMATIC_OPERATION = 35
    AI_DETECTION = 36
    AUTO_LEVELER = 37
    VIBRATION_COMPENSATION = 38
    TIME_LAPSE = 39
    VIDEO_LIGHT = 40
    BOX_LIGHT = 41
    MULTI_COLOR_BOX = 2006


class AnycubicPrinterMaterialType(StrEnum):
    FILAMENT = "Filament"
    RESIN = "Resin"


class AnycubicServerMessage:
    FILE_NOT_FOUND = "No file found"


# ============================================================================
# MQTT CONFIGURATION
# ============================================================================

MQTT_HOST = "mqtt-universe.anycubic.com"
MQTT_PORT = 8883
MQTT_TIMEOUT = 60 * 20

# MQTT topic hierarchy
MQTT_TOPIC_PREFIX = "anycubic/anycubicCloud/v1"
MQTT_ROOT_TOPIC_PLUS = f"{MQTT_TOPIC_PREFIX}/+/public/"
MQTT_ROOT_TOPIC_PRINTER = f"{MQTT_TOPIC_PREFIX}/printer/app/"
MQTT_ROOT_TOPIC_PUBLISH_PRINTER = f"{MQTT_TOPIC_PREFIX}/printer/public/"
MQTT_ROOT_TOPIC_PUBLISH_PRINTER_SLICER = f"{MQTT_TOPIC_PREFIX}/pc/printer/"
MQTT_ROOT_TOPIC_SERVER = f"{MQTT_TOPIC_PREFIX}/server/app/"

# ============================================================================
# CLOUD API CONFIGURATION
# ============================================================================

BASE_DOMAIN = "cloud-universe.anycubic.com"
API_DOMAIN = f"https://{BASE_DOMAIN}/"
AUTH_DOMAIN = "uc.makeronline.com"
PUBLIC_API_ENDPOINT = "p/p/workbench/api"
PROJECT_IMAGE_URL_BASE = "https://workbentch.s3.us-east-2.amazonaws.com/"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 "
    "Safari/537.36"
)

# ============================================================================
# CLOUD AUTHENTICATION CREDENTIALS
# ============================================================================

AC_KNOWN_CID_APP = "ca4c8416cced85a1dc02"
AC_KNOWN_AID = "f9b3528877c94d5c9c5af32245db46ef"
AC_KNOWN_VID_APP = "1.4.8"
AC_KNOWN_VID_SLICER_NEXT = "1.3.9.4"
AC_KNOWN_SEC = "0cf75926606049a3937f56b0373b99fb"

ACCESS_TOKEN_LOGIN_RETRIES = 2
ACCESS_TOKEN_LOGIN_RETRY_INTERVAL = 2

# ============================================================================
# API & MQTT LIMITS
# ============================================================================

MAX_PROJECT_LIST_RESULTS = 2000
MAX_PROJECT_IMAGE_SEARCH_COUNT = 200
MAX_API_FETCH_TIME_WARN = 20
WARN_INTERVAL_API_DURATION = 60 * 10

# ============================================================================
# GCODE PATTERNS
# ============================================================================

REX_GCODE_EXT = re.compile(r"\.gcode$")

# ============================================================================
# ENTITY DEFINITIONS & TRANSLATIONS
# ============================================================================

# Entity definitions - intentionally kept in separate flat module
from .definitions import (  # noqa: E402, F401
    BINARY_DEFINITIONS,
    BUTTON_DEFINITIONS,
    FAN_DEFINITIONS,
    LIGHT_DEFINITION,
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    SENSOR_DEFINITIONS,
    SWITCH_DEFINITIONS,
)

# NOTE: Message translations moved to translations/*.json (en/nl).

# ============================================================================
# PUBLIC EXPORTS
# ============================================================================

__all__ = [
    # Core
    "DOMAIN",
    "MANUFACTURER",
    "MODEL",
    # Connection
    "CONNECTION_MODE_LAN",
    "CONNECTION_MODE_CLOUD",
    # (config-entry keys moved into the config flow as literals)
    # Auth modes (referenced as literals in config flow)
    # Device types
    "DEVICE_TYPE_ACE_PRO",
    "DEVICE_TYPE_EXTFILBOX",
    # Coordinator keys
    "MULTI_COLOR_BOX_KEY",
    "VIDEO_KEY",
    # Camera
    "CAMERA_NAME",
    # Device base info
    "ACE_PRO_DEVICE_BASE",
    "EXTFILBOX_DEVICE_BASE",
    # Filament
    "FILAMENT_DIAMETER_MM",
    "FILAMENT_DENSITY_G_CM3",
    # Cloud API endpoints
    "API_ENDPOINT",
    # Enums
    "AnycubicFeedType",
    "AnycubicPrintStatus",
    "AnycubicOrderID",
    "AnycubicFunctionID",
    "AnycubicPrinterMaterialType",
    "AnycubicServerMessage",
    # MQTT
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_TIMEOUT",
    "MQTT_TOPIC_PREFIX",
    "MQTT_ROOT_TOPIC_PLUS",
    "MQTT_ROOT_TOPIC_PRINTER",
    "MQTT_ROOT_TOPIC_PUBLISH_PRINTER",
    "MQTT_ROOT_TOPIC_PUBLISH_PRINTER_SLICER",
    "MQTT_ROOT_TOPIC_SERVER",
    # Cloud API
    "BASE_DOMAIN",
    "API_DOMAIN",
    "AUTH_DOMAIN",
    "PUBLIC_API_ENDPOINT",
    "PROJECT_IMAGE_URL_BASE",
    "DEFAULT_USER_AGENT",
    # Credentials
    "AC_KNOWN_CID_APP",
    "AC_KNOWN_AID",
    "AC_KNOWN_VID_APP",
    "AC_KNOWN_VID_SLICER_NEXT",
    "AC_KNOWN_SEC",
    # Limits
    "MAX_PROJECT_LIST_RESULTS",
    "MAX_PROJECT_IMAGE_SEARCH_COUNT",
    "MAX_API_FETCH_TIME_WARN",
    "WARN_INTERVAL_API_DURATION",
    # Patterns
    "REX_GCODE_EXT",
    # Definitions & translations
    "BINARY_DEFINITIONS",
    "BUTTON_DEFINITIONS",
    "FAN_DEFINITIONS",
    "LIGHT_DEFINITION",
    "NUMBER_DEFINITIONS",
    "SELECT_DEFINITIONS",
    "SENSOR_DEFINITIONS",
    "SWITCH_DEFINITIONS",
    # message translations moved to translations/*.json
]
