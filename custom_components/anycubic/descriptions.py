"""Centralized description definitions organized by mode and platform."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.update import UpdateDeviceClass
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature, UnitOfTime

from .const import (
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LAN,
    DEVICE_TYPE_ACE_PRO,
    DEVICE_TYPE_EXTFILBOX,
    DEVICE_TYPE_PRINTER,
    ENTITY_ID_DRYING_START_PRESET_,
    EXT_FILBOX_KEY,
    MAX_DRYING_PRESETS,
    MULTI_COLOR_BOX_KEY,
    PrinterEntityType,
    UNIT_LAYERS,
)


def _humanize_description_key(value: str) -> str:
    text = value.replace("_", " ").strip()
    for prefix in ["ace pro 1 ", "ace pro 2 ", "secondary "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.replace("job ", "print ")
    text = text.replace("curr ", "current ")
    text = text.replace("fw ", "firmware ")
    return text.title()


def _normalize_description_entry(entry: dict[str, Any]) -> dict[str, Any]:
    key = entry.get("key")
    if not key:
        return entry

    if "translation_key" not in entry:
        entry["translation_key"] = str(key)

    return entry


_DEVICE_TYPE_TO_PRINTER_ENTITY_TYPE: dict[str, PrinterEntityType] = {
    DEVICE_TYPE_PRINTER: PrinterEntityType.PRINTER,
    "fdm": PrinterEntityType.FDM,
    "ace_primary": PrinterEntityType.ACE_PRIMARY,
    "ace_secondary": PrinterEntityType.ACE_SECONDARY,
    "dry_preset_primary": PrinterEntityType.DRY_PRESET_PRIMARY,
    "dry_preset_secondary": PrinterEntityType.DRY_PRESET_SECONDARY,
    "global": PrinterEntityType.GLOBAL,
}


def _normalize_descriptions_tree(node: Any) -> Any:
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            if isinstance(item, dict):
                out.append(_normalize_description_entry(item))
            else:
                out.append(_normalize_descriptions_tree(item))
        return out

    if isinstance(node, dict):
        return {k: _normalize_descriptions_tree(v) for k, v in node.items()}

    return node


def _normalize_printer_entity_types(tree: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for mode_data in tree.values():
        if not isinstance(mode_data, dict):
            continue
        for entries in mode_data.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if "printer_entity_type" not in entry:
                    pet = _DEVICE_TYPE_TO_PRINTER_ENTITY_TYPE.get(entry.get("device_type"))
                    if pet is not None:
                        entry["printer_entity_type"] = pet
    return tree


def get_descriptions(
    mode: str,
    platform: str,
    *,
    device_type: str | None = None,
) -> list[dict[str, Any]]:
    platform_data = (DESCRIPTIONS_BY_MODE.get(mode) or {}).get(platform) or []
    if not isinstance(platform_data, list):
        return []

    if device_type is None:
        return platform_data

    return [item for item in platform_data if item.get("device_type") == device_type]

DESCRIPTIONS_BY_MODE: dict[str, dict[str, Any]] = {
    CONNECTION_MODE_LAN: {
        "binary_sensor": [
            {"key": "print_problem", "device_type": DEVICE_TYPE_PRINTER, "type": "print_problem", "device_class": "problem", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "nozzle_heating", "device_type": DEVICE_TYPE_PRINTER, "type": "nozzle_heating", "device_class": "heat", "icon": "mdi:printer-3d-nozzle-heat"},
            {"key": "bed_heating", "device_type": DEVICE_TYPE_PRINTER, "type": "bed_heating", "device_class": "heat"},
        ],
        "button": [
            {"key": "home_all", "device_type": DEVICE_TYPE_PRINTER, "type": "axis", "action": "move", "axis": 5, "icon": "mdi:axis-arrow"},
            {"key": "home_xy", "device_type": DEVICE_TYPE_PRINTER, "type": "axis", "action": "move", "axis": 4, "icon": "mdi:axis-arrow"},
            {"key": "home_z", "device_type": DEVICE_TYPE_PRINTER, "type": "axis", "action": "move", "axis": 3, "icon": "mdi:axis-arrow"},
            {"key": "cancel_print", "device_type": DEVICE_TYPE_PRINTER, "type": "print", "action": "stop", "icon": "mdi:stop"},
            {"key": "pause_print", "device_type": DEVICE_TYPE_PRINTER, "type": "print", "action": "pause", "icon": "mdi:pause"},
            {"key": "resume_print", "device_type": DEVICE_TYPE_PRINTER, "type": "print", "action": "resume", "icon": "mdi:play"},
        ],
        "fan": [
            {"key": "main", "device_type": DEVICE_TYPE_PRINTER, "icon": "mdi:fan", "data_key": "fan_speed_pct"},
            {"key": "aux", "device_type": DEVICE_TYPE_PRINTER, "icon": "mdi:fan", "data_key": "aux_fan_speed_pct"},
            {"key": "box", "device_type": DEVICE_TYPE_PRINTER, "icon": "mdi:fan", "data_key": "box_fan_level"},
        ],
        "image": [],
        "light": [
            {"key": "chamber_printer", "device_type": DEVICE_TYPE_PRINTER, "type_id": 2, "icon": "mdi:lightbulb"},
        ],
        "number": [
            {"key": "target_nozzle_temp", "device_type": DEVICE_TYPE_PRINTER, "data_key": "target_nozzle_temp", "min": 185, "max": 320, "icon": "mdi:printer-3d-nozzle"},
            {"key": "target_hotbed_temp", "device_type": DEVICE_TYPE_PRINTER, "data_key": "target_hotbed_temp", "min": 35, "max": 120, "icon": "mdi:heating-coil"},
            {"key": "ace_pro_drying_target", "device_type": DEVICE_TYPE_ACE_PRO, "min": 35, "max": 55, "unit": "°C", "kind": "drying_target", "per_box": True},
            {"key": "ace_pro_drying_duration", "device_type": DEVICE_TYPE_ACE_PRO, "min": 1, "max": 1440, "unit": "min", "kind": "drying_duration", "per_box": True},
        ],
        "select": [
            {"key": "print_speed_mode", "device_type": DEVICE_TYPE_PRINTER, "icon": "mdi:run", "options": ["silent", "standard", "sport"], "value_map": {"silent": 1, "standard": 0, "sport": 2}},
        ],
        "sensor": [
            {"key": "printer_info", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "state"), "icon": "mdi:information-outline"},
            {"key": "printer_model", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "model"), "icon": "mdi:printer-3d", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "printer_ip", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "ip"), "icon": "mdi:ip-network", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "printer_firmware", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "version"), "icon": "mdi:chip", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "nozzle_temp", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("tempature", "data", "curr_nozzle_temp"), "unit": "°C", "icon": "mdi:thermometer"},
            {"key": "hotbed_temp", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("tempature", "data", "curr_hotbed_temp"), "unit": "°C", "icon": "mdi:thermometer"},
            {"key": "print_status", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "project", "state"), "icon": "mdi:printer-3d"},
            {"key": "print_progress", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("info", "data", "project", "progress"), "unit": "%", "icon": "mdi:progress-clock"},
            {"key": "print_curr_layer", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "curr_layer"), "icon": "mdi:layers"},
            {"key": "print_filename", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "filename"), "icon": "mdi:file-document"},
            {"key": "print_time", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "print_time"), "icon": "mdi:timer", "formatter": "_minutes_to_hhmm"},
            {"key": "print_remain_time", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "remain_time"), "icon": "mdi:timer-sand-complete", "formatter": "_minutes_to_hhmm"},
            {"key": "print_model_name", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "source_info", "models", 0, "name"), "icon": "mdi:file-outline"},
            {"key": "print_supplies_usage", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "supplies_usage"), "icon": "mdi:cube-scan", "unit": "g"},
            {"key": "print_total_layers", "device_type": DEVICE_TYPE_PRINTER, "data_path": ("print", "data", "total_layers"), "icon": "mdi:layers"},
            {"key": "{box_id}_temp", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "temp", "unit": "°C", "icon": "mdi:thermometer", "per_box": True},
            {"key": "ace_pro_box_{box_id}_loaded", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "loaded_slot", "icon": "mdi:folder-arrow-right", "per_box": True},
            {"key": "ace_pro_box_{box_id}_slot_{slot_index}", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "slot_index": "{slot_index}", "icon": "mdi:tray", "per_box": True, "per_slot": True},
            {"key": "ace_pro_box_{box_id}_firmware", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "firmware", "icon": "mdi:chip", "entity_category": EntityCategory.DIAGNOSTIC, "per_box": True},
            {"key": "ace_pro_box_{box_id}_model", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "model", "icon": "mdi:package-variant", "entity_category": EntityCategory.DIAGNOSTIC, "per_box": True},
            {"key": "ace_pro_box_{box_id}_dryer_status", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "dryer_status.status", "icon": "mdi:air-filter", "per_box": True},
            {"key": "ace_pro_box_{box_id}_dryer_target", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "dryer_status.target_temp", "unit": "°C", "icon": "mdi:thermometer-high", "per_box": True},
            {"key": "ace_pro_box_{box_id}_dryer_duration", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "dryer_status.duration", "unit": "min", "icon": "mdi:timer", "per_box": True},
            {"key": "ace_pro_box_{box_id}_dryer_remain", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "multi_color_box"), "data_field": "dryer_status.remain_time", "unit": "min", "icon": "mdi:timer-sand", "per_box": True},
            {"key": "ace_pro_auto_refill", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "auto_refill"), "icon": "mdi:reload"},
            {"key": "ace_pro_cutter_state", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "cutter_state"), "icon": "mdi:content-cut"},
            {"key": "ace_pro_current_filament", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "current_filament"), "icon": "mdi:printer-3d-nozzle"},
            {"key": "ace_pro_ext_spool", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "ext_spool"), "icon": "mdi:package-variant"},
            {"key": "ace_pro_ext_spool_status", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "ext_spool_status"), "icon": "mdi:package-check"},
            {"key": "ace_pro_filament_present", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "filament_present"), "icon": "mdi:checkbox-marked-circle"},
            {"key": "ace_pro_tracker_length", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "tracker_detection_length"), "unit": "mm", "icon": "mdi:ruler"},
            {"key": "ace_pro_tracker_present", "device_type": DEVICE_TYPE_ACE_PRO, "data_path": (MULTI_COLOR_BOX_KEY, "data", "tracker_filament_present"), "icon": "mdi:checkbox-marked-circle-outline"},
            {"key": "extfilbox_loaded", "device_type": DEVICE_TYPE_EXTFILBOX, "data_path": (EXT_FILBOX_KEY, "data", "loaded"), "icon": "mdi:package-variant-closed"},
            {"key": "extfilbox_slot", "device_type": DEVICE_TYPE_EXTFILBOX, "data_path": (EXT_FILBOX_KEY, "data", "multi_color_box", 0), "icon": "mdi:tray", "per_box": False, "per_slot": False},
        ],
        "switch": [
            {"key": "ace_pro_box_{box_id}_drying", "device_type": DEVICE_TYPE_ACE_PRO, "per_box": True},
            {"key": "ace_pro_box_{box_id}_auto_feed", "device_type": DEVICE_TYPE_ACE_PRO, "per_box": True},
            {"key": "manual_mqtt_connection_enabled", "device_type": "global", "entity_category": EntityCategory.DIAGNOSTIC},
        ],
        "update": [],
    },
    CONNECTION_MODE_CLOUD: {
        "binary_sensor": [
            {"key": "job_in_progress", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "job_complete", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "job_failed", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "job_is_paused", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "printer_online", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "is_busy", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "is_available", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "dry_status_is_drying", "device_type": "ace_primary"},
            {"key": "secondary_dry_status_is_drying", "device_type": "ace_secondary"},
        ],
        "button": [
            {"key": "pause_print", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "resume_print", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "cancel_print", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "request_file_list_local", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "request_file_list_udisk", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "drying_stop", "device_type": "ace_primary"},
            {"key": "secondary_drying_stop", "device_type": "ace_secondary"},
            *[{"key": f"{ENTITY_ID_DRYING_START_PRESET_}{x + 1}", "device_type": "dry_preset_primary"} for x in range(MAX_DRYING_PRESETS)],
            *[{"key": f"secondary_{ENTITY_ID_DRYING_START_PRESET_}{x + 1}", "device_type": "dry_preset_secondary"} for x in range(MAX_DRYING_PRESETS)],
            {"key": "request_file_list_cloud", "device_type": "global"},
        ],
        "fan": [
            {"key": "fan_speed_pct", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "aux_fan_speed_pct", "device_type": DEVICE_TYPE_PRINTER},
            {"key": "box_fan_level", "device_type": DEVICE_TYPE_PRINTER},
        ],
        "image": [
            {"key": "job_image_url", "device_type": DEVICE_TYPE_PRINTER},
        ],
        "sensor": [
            {"key": "current_status", "device_type": DEVICE_TYPE_PRINTER, "not_measured": True},
            {"key": "job_name", "device_type": DEVICE_TYPE_PRINTER, "not_measured": True},
            {"key": "job_progress", "device_type": DEVICE_TYPE_PRINTER, "native_unit_of_measurement": PERCENTAGE},
            {"key": "job_time_elapsed", "device_type": DEVICE_TYPE_PRINTER, "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "job_time_remaining", "device_type": DEVICE_TYPE_PRINTER, "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "job_state", "device_type": DEVICE_TYPE_PRINTER, "not_measured": True},
            {"key": "job_eta", "device_type": DEVICE_TYPE_PRINTER, "device_class": SensorDeviceClass.TIMESTAMP, "not_measured": True},
            {"key": "job_current_layer", "device_type": DEVICE_TYPE_PRINTER, "native_unit_of_measurement": UNIT_LAYERS},
            {"key": "job_total_layers", "device_type": DEVICE_TYPE_PRINTER, "native_unit_of_measurement": UNIT_LAYERS},
            {"key": "job_speed_mode", "device_type": "fdm", "not_measured": True},
            {"key": "curr_nozzle_temp", "device_type": "fdm", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "curr_hotbed_temp", "device_type": "fdm", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "target_nozzle_temp", "device_type": "fdm", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "target_hotbed_temp", "device_type": "fdm", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "print_speed_pct", "device_type": "fdm", "native_unit_of_measurement": PERCENTAGE},
            {"key": "ace_current_temperature", "device_type": "ace_primary", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "ace_spools", "device_type": "ace_primary", "not_measured": True},
            {"key": "ace_pro_attributes", "device_type": "ace_primary", "icon": "mdi:information-outline", "entity_category": EntityCategory.DIAGNOSTIC, "not_measured": True},
            {"key": "ace_pro_1_firmware", "device_type": "ace_primary", "entity_category": EntityCategory.DIAGNOSTIC, "not_measured": True},
            {"key": "ace_pro_1_dryer_status", "device_type": "ace_primary", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "ace_pro_1_dryer_target_temp", "device_type": "ace_primary", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "ace_pro_1_dryer_duration", "device_type": "ace_primary", "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "ace_pro_1_dryer_remain_time", "device_type": "ace_primary", "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "ace_pro_1_slot_1", "device_type": "ace_primary", "not_measured": True},
            {"key": "ace_pro_1_slot_2", "device_type": "ace_primary", "not_measured": True},
            {"key": "ace_pro_1_slot_3", "device_type": "ace_primary", "not_measured": True},
            {"key": "ace_pro_1_slot_4", "device_type": "ace_primary", "not_measured": True},
            {"key": "secondary_ace_pro_attributes", "device_type": "ace_secondary", "icon": "mdi:information-outline", "entity_category": EntityCategory.DIAGNOSTIC, "not_measured": True},
            {"key": "ace_pro_2_firmware", "device_type": "ace_secondary", "entity_category": EntityCategory.DIAGNOSTIC, "not_measured": True},
            {"key": "ace_pro_2_dryer_status", "device_type": "ace_secondary", "entity_category": EntityCategory.DIAGNOSTIC},
            {"key": "ace_pro_2_dryer_target_temp", "device_type": "ace_secondary", "native_unit_of_measurement": UnitOfTemperature.CELSIUS},
            {"key": "ace_pro_2_dryer_duration", "device_type": "ace_secondary", "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "ace_pro_2_dryer_remain_time", "device_type": "ace_secondary", "native_unit_of_measurement": UnitOfTime.MINUTES},
            {"key": "ace_pro_2_slot_1", "device_type": "ace_secondary", "not_measured": True},
            {"key": "ace_pro_2_slot_2", "device_type": "ace_secondary", "not_measured": True},
            {"key": "ace_pro_2_slot_3", "device_type": "ace_secondary", "not_measured": True},
            {"key": "ace_pro_2_slot_4", "device_type": "ace_secondary", "not_measured": True},
        ],
        "switch": [
            {"key": "multi_color_box_runout_refill", "device_type": "ace_primary"},
            {"key": "secondary_multi_color_box_runout_refill", "device_type": "ace_secondary"},
            {"key": "manual_mqtt_connection_enabled", "device_type": "global", "entity_category": EntityCategory.DIAGNOSTIC},
        ],
        "update": [
            {"key": "fw_version", "device_type": DEVICE_TYPE_PRINTER, "device_class": UpdateDeviceClass.FIRMWARE, "entity_category": EntityCategory.CONFIG},
            {"key": "multi_color_box_fw_version", "device_type": "ace_primary", "device_class": UpdateDeviceClass.FIRMWARE, "entity_category": EntityCategory.CONFIG},
            {"key": "secondary_multi_color_box_fw_version", "device_type": "ace_secondary", "device_class": UpdateDeviceClass.FIRMWARE, "entity_category": EntityCategory.CONFIG},
        ],
    },
}

DESCRIPTIONS_BY_MODE = _normalize_descriptions_tree(DESCRIPTIONS_BY_MODE)
DESCRIPTIONS_BY_MODE = _normalize_printer_entity_types(DESCRIPTIONS_BY_MODE)
