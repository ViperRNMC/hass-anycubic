from __future__ import annotations

import re
from enum import IntEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from ..cloud.const.enums import AnycubicPrinterMaterialType
from ..const import (
    ENTITY_ID_DRYING_START_PRESET_,
    MAX_DRYING_PRESETS,
    CONF_DRYING_PRESET_DURATION_,
    CONF_DRYING_PRESET_TEMPERATURE_,
    DOMAIN,
    MANUFACTURER,
    PrinterEntityType,
)

if TYPE_CHECKING:
    from ..coordinator import AnycubicBackendCoordinator
    from ..entity import AnycubicEntityDescription
    from ..cloud.data_models.printer import AnycubicPrinter


class AnycubicMQTTConnectMode(IntEnum):
    Printing_Only = 1
    Printing_Drying = 2
    Device_Online = 3
    Always = 4
    Never_Connect = 5


def build_printer_device_info(
    coordinator_data: dict[str, Any],
    printer_id: int,
) -> DeviceInfo:
    printer_data = coordinator_data['printers'][printer_id]['states']
    user_data = coordinator_data['user_info']
    return DeviceInfo(
        identifiers={(DOMAIN, f"{user_data['id']}-{printer_data['id']}")},
        manufacturer=MANUFACTURER,
        model=printer_data["machine_name"],
        name=printer_data["name"],
        connections={(CONNECTION_NETWORK_MAC, printer_data["machine_mac"])},
        sw_version=printer_data["fw_version"],
        hw_version=f"Printer ID: {printer_id}",
        serial_number=f"{printer_id}",
    )


def build_cloud_entity_device_info(
    coordinator_data: dict[str, Any],
    printer_id: int,
    printer_entity_type: PrinterEntityType | None,
) -> DeviceInfo:
    printer_data = coordinator_data['printers'][printer_id]['states']
    user_data = coordinator_data['user_info']

    printer_identifier = (DOMAIN, f"{user_data['id']}-{printer_data['id']}")

    if printer_entity_type in [PrinterEntityType.ACE_PRIMARY, PrinterEntityType.DRY_PRESET_PRIMARY]:
        fw_version = printer_data.get("multi_color_box_fw_version")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{user_data['id']}-{printer_data['id']}-ace-pro-1")},
            manufacturer=MANUFACTURER,
            model="Ace Pro",
            name="Ace Pro 1",
            sw_version=fw_version,
            hw_version="ACE Unit: 1",
            serial_number=f"{printer_id}-ace1",
            via_device=printer_identifier,
        )

    if printer_entity_type in [PrinterEntityType.ACE_SECONDARY, PrinterEntityType.DRY_PRESET_SECONDARY]:
        fw_version = printer_data.get("secondary_multi_color_box_fw_version")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{user_data['id']}-{printer_data['id']}-ace-pro-2")},
            manufacturer=MANUFACTURER,
            model="Ace Pro",
            name="Ace Pro 2",
            sw_version=fw_version,
            hw_version="ACE Unit: 2",
            serial_number=f"{printer_id}-ace2",
            via_device=printer_identifier,
        )

    return build_printer_device_info(coordinator_data, printer_id)


def get_drying_preset_from_entry_options(
    entry_options: MappingProxyType[str, Any],
    preset_number: int | str,
) -> tuple[int | None, int | None]:
    preset_duration = entry_options.get(f"{CONF_DRYING_PRESET_DURATION_}{preset_number}")
    preset_temperature = entry_options.get(f"{CONF_DRYING_PRESET_TEMPERATURE_}{preset_number}")

    return (
        preset_duration,
        preset_temperature,
    )


def printer_state_for_key(
    coordinator: AnycubicBackendCoordinator,
    printer_id: int,
    state_key: str,
) -> Any:
    return coordinator.data['printers'][printer_id]['states'][state_key]


def printer_attributes_for_key(
    coordinator: AnycubicBackendCoordinator,
    printer_id: int,
    attribute_key: str,
) -> dict[str, Any] | None:
    attr: dict[str, Any] | None = coordinator.data['printers'][printer_id]['attributes'].get(attribute_key)
    return attr


def printer_state_connected_ace_units(
    coordinator: AnycubicBackendCoordinator,
    printer_id: int,
) -> int:
    return int(
        printer_state_for_key(
            coordinator,
            printer_id,
            'connected_ace_units',
        )
    )


def printer_state_supports_ace(
    coordinator: AnycubicBackendCoordinator,
    printer_id: int,
) -> bool:
    return bool(
        printer_state_for_key(
            coordinator,
            printer_id,
            'supports_function_multi_color_box',
        )
    )


def check_descriptor_status_not_lcd(
    description: AnycubicEntityDescription,
    material_type: AnycubicPrinterMaterialType,
) -> bool:
    return (
        description.printer_entity_type == PrinterEntityType.LCD
        and material_type != AnycubicPrinterMaterialType.RESIN
    )


def check_descriptor_status_not_fdm(
    description: AnycubicEntityDescription,
    material_type: AnycubicPrinterMaterialType,
) -> bool:
    return (
        description.printer_entity_type == PrinterEntityType.FDM
        and material_type != AnycubicPrinterMaterialType.FILAMENT
    )


def check_descriptor_state_ace_not_supported(
    description: AnycubicEntityDescription,
    supports_ace: bool,
) -> bool:
    return (
        description.printer_entity_type in [
            PrinterEntityType.ACE_PRIMARY,
            PrinterEntityType.ACE_SECONDARY,
            PrinterEntityType.DRY_PRESET_PRIMARY,
            PrinterEntityType.DRY_PRESET_SECONDARY,
        ]
        and not supports_ace
    )


def check_descriptor_state_ace_primary_unavailable(
    description: AnycubicEntityDescription,
    supports_ace: bool,
    connected_ace_units: int,
) -> bool:
    return (
        description.printer_entity_type in [
            PrinterEntityType.ACE_PRIMARY,
            PrinterEntityType.DRY_PRESET_PRIMARY,
        ]
        and supports_ace
        and connected_ace_units < 1
    )


def check_descriptor_state_ace_secondary_unavailable(
    description: AnycubicEntityDescription,
    supports_ace: bool,
    connected_ace_units: int,
) -> bool:
    return (
        description.printer_entity_type in [
            PrinterEntityType.ACE_SECONDARY,
            PrinterEntityType.DRY_PRESET_SECONDARY,
        ]
        and supports_ace
        and connected_ace_units < 2
    )


def check_descriptor_state_drying_available(
    description: AnycubicEntityDescription,
    supports_ace: bool,
    connected_ace_units: int,
) -> bool:
    return (
        supports_ace
        and (
            description.printer_entity_type == PrinterEntityType.DRY_PRESET_PRIMARY
            and connected_ace_units >= 1
        ) or (
            description.printer_entity_type == PrinterEntityType.DRY_PRESET_SECONDARY
            and connected_ace_units >= 2
        )
    )


def check_descriptor_state_drying_unavailable(
    description: AnycubicEntityDescription,
    supports_ace: bool,
    connected_ace_units: int,
    entry_options: MappingProxyType[str, Any],
) -> bool:
    drying_available = check_descriptor_state_drying_available(
        description,
        supports_ace,
        connected_ace_units,
    )

    if not drying_available:
        return False

    preset_duration, preset_temperature = get_drying_preset_from_entry_options(
        entry_options,
        description.key[-1],
    )

    return (
        not preset_duration
        or not preset_temperature
        or int(preset_temperature) <= 0
        or int(preset_duration) <= 0
    )


def printer_entity_unique_id(
    coordinator: AnycubicBackendCoordinator,
    printer_id: int,
    entity_suffix: str,
) -> str:
    shared_lan_cloud_keys = {
        "target_nozzle_temp",
        "target_hotbed_temp",
    }
    if entity_suffix in shared_lan_cloud_keys:
        entry = getattr(coordinator, "entry", None)
        entry_id = getattr(entry, "entry_id", None)
        if entry_id:
            configured_printers = entry.data.get("printer_id_list", []) if getattr(entry, "data", None) else []
            if len(configured_printers) <= 1:
                return f"{entry_id}_{entity_suffix}"
            return f"{entry_id}_{printer_id}_{entity_suffix}"

    return f"{printer_state_for_key(coordinator, printer_id, 'machine_mac')}-{entity_suffix}"


def state_string_active(state: Any) -> str:
    return "active" if state is not None else "inactive"


def state_string_loaded(state: Any) -> str:
    return "loaded" if state is not None else "not loaded"


REGEX_NOQUOTE_STRING = re.compile(r"^['\"]?([^'\"]+)['\"]?$")


def remove_quotes_from_string(input_string: str) -> str:
    matches = REGEX_NOQUOTE_STRING.findall(input_string)

    if len(matches) == 1:
        return str(matches[0])

    raise TypeError("Unexpected quotes in string.")


def validate_value_is_type[_T: Any](
    value: Any,
    value_type: type[_T],
    allow_lists: bool = False,
) -> _T | list[_T] | None:
    if allow_lists and isinstance(value, list):
        for v in value:
            if not isinstance(v, value_type):
                return None
        return value
    elif isinstance(value, value_type):
        return value

    return None


def get_value_from_dict_if_type[_T: Any](
    input_dict: dict[str, Any],
    key: str,
    value_type: type[_T],
    allow_lists: bool = False,
) -> _T | list[_T] | None:
    if (
        key in input_dict
        and (
            val := validate_value_is_type(
                input_dict[key],
                value_type,
                allow_lists,
            )
        )
    ):
        return val

    return None


def update_dict_and_validate(
    output_dict: dict[str, Any],
    input_dict: dict[str, Any],
    key: str,
    value_type: Any,
    allow_lists: bool = False,
) -> None:
    if val := get_value_from_dict_if_type(input_dict, key, value_type, allow_lists):
        output_dict[key] = val


def extract_panel_card_config(
    input_conf: dict[str, Any],
) -> dict[str, Any]:
    card_conf: dict[str, Any] = {}

    if len(input_conf) == 0:
        return card_conf

    update_dict_and_validate(card_conf, input_conf, 'vertical', bool)
    update_dict_and_validate(card_conf, input_conf, 'round', bool)
    update_dict_and_validate(card_conf, input_conf, 'use_24hr', bool)
    update_dict_and_validate(card_conf, input_conf, 'temperatureUnit', str)
    update_dict_and_validate(card_conf, input_conf, 'lightEntityId', str)
    update_dict_and_validate(card_conf, input_conf, 'powerEntityId', str)
    update_dict_and_validate(card_conf, input_conf, 'cameraEntityId', str)
    update_dict_and_validate(card_conf, input_conf, 'monitoredStats', str, allow_lists=True)
    update_dict_and_validate(card_conf, input_conf, 'scaleFactor', float)
    update_dict_and_validate(card_conf, input_conf, 'slotColors', str, allow_lists=True)
    update_dict_and_validate(card_conf, input_conf, 'showSettingsButton', bool)
    update_dict_and_validate(card_conf, input_conf, 'alwaysShow', bool)

    return card_conf


def _slot_material(spool_list: list[dict[str, Any]] | None, index: int) -> str:
    if not spool_list or index < 0 or index >= len(spool_list):
        return "unknown"
    slot = spool_list[index] or {}
    if not slot.get("spool_loaded"):
        return "empty"
    return str(slot.get("material_type") or "unknown")


def build_lan_printer_payload(raw_data: dict[str, Any] | None) -> dict[str, Any]:
    """Build normalized payload for LAN mode."""
    return {
        "states": dict(raw_data or {}),
        "attributes": {},
    }


def build_cloud_printer_payload(
    printer: AnycubicPrinter,
    cloud_file_list: list[dict[str, Any]] | None,
    mqtt_manually_connected: bool,
    mqtt_supports_login: bool,
    entry_options: dict[str, Any],
) -> dict[str, Any]:
    """Build normalized payload for Cloud mode from AnycubicPrinter object."""
    primary_ace_spool_info = printer.primary_multi_color_box_spool_info_object
    secondary_ace_spool_info = printer.secondary_multi_color_box_spool_info_object

    file_list_local = printer.local_file_list_object
    file_list_udisk = printer.udisk_file_list_object
    file_list_cloud = cloud_file_list

    states = {
        "id": printer.id,
        "name": printer.name,
        "printer_online": printer.printer_online,
        "is_busy": printer.is_busy,
        "is_available": printer.is_available,
        "current_status": printer.current_status,
        "curr_nozzle_temp": printer.curr_nozzle_temp,
        "curr_hotbed_temp": printer.curr_hotbed_temp,
        "machine_mac": printer.machine_mac,
        "machine_name": printer.machine_name,
        "fw_version": printer.fw_version.firmware_version if printer.fw_version else None,
        "file_list_local": state_string_loaded(file_list_local),
        "file_list_udisk": state_string_loaded(file_list_udisk),
        "file_list_cloud": state_string_loaded(file_list_cloud),
        "supports_function_multi_color_box": printer.supports_function_multi_color_box,
        "connected_ace_units": printer.connected_ace_units,
        "multi_color_box_fw_version": printer.primary_multi_color_box_fw_firmware_version,
        "ace_spools": state_string_active(primary_ace_spool_info),
        "multi_color_box_runout_refill": printer.primary_multi_color_box_auto_feed,
        "ace_current_temperature": printer.primary_multi_color_box_current_temperature,
        "ace_pro_attributes": state_string_active(printer.primary_multi_color_box_fw_firmware_version),
        "ace_pro_1_firmware": printer.primary_multi_color_box_fw_firmware_version,
        "ace_pro_1_dryer_status": printer.primary_drying_status_raw_status_code,
        "ace_pro_1_dryer_target_temp": printer.primary_drying_status_target_temperature,
        "ace_pro_1_dryer_duration": printer.primary_drying_status_total_duration,
        "ace_pro_1_dryer_remain_time": printer.primary_drying_status_remaining_time,
        "ace_pro_1_slot_1": _slot_material(primary_ace_spool_info, 0),
        "ace_pro_1_slot_2": _slot_material(primary_ace_spool_info, 1),
        "ace_pro_1_slot_3": _slot_material(primary_ace_spool_info, 2),
        "ace_pro_1_slot_4": _slot_material(primary_ace_spool_info, 3),
        "secondary_multi_color_box_fw_version": printer.secondary_multi_color_box_fw_firmware_version,
        "secondary_ace_spools": state_string_active(secondary_ace_spool_info),
        "secondary_multi_color_box_runout_refill": printer.secondary_multi_color_box_auto_feed,
        "secondary_ace_current_temperature": printer.secondary_multi_color_box_current_temperature,
        "secondary_ace_pro_attributes": state_string_active(printer.secondary_multi_color_box_fw_firmware_version),
        "ace_pro_2_firmware": printer.secondary_multi_color_box_fw_firmware_version,
        "ace_pro_2_dryer_status": printer.secondary_drying_status_raw_status_code,
        "ace_pro_2_dryer_target_temp": printer.secondary_drying_status_target_temperature,
        "ace_pro_2_dryer_duration": printer.secondary_drying_status_total_duration,
        "ace_pro_2_dryer_remain_time": printer.secondary_drying_status_remaining_time,
        "ace_pro_2_slot_1": _slot_material(secondary_ace_spool_info, 0),
        "ace_pro_2_slot_2": _slot_material(secondary_ace_spool_info, 1),
        "ace_pro_2_slot_3": _slot_material(secondary_ace_spool_info, 2),
        "ace_pro_2_slot_4": _slot_material(secondary_ace_spool_info, 3),
        "dry_status_is_drying": printer.primary_drying_status_is_drying,
        "dry_status_target_temperature": printer.primary_drying_status_target_temperature,
        "dry_status_total_duration": printer.primary_drying_status_total_duration,
        "dry_status_remaining_time": printer.primary_drying_status_remaining_time,
        "secondary_dry_status_is_drying": printer.secondary_drying_status_is_drying,
        "secondary_dry_status_raw_status_code": printer.secondary_drying_status_raw_status_code,
        "secondary_dry_status_target_temperature": printer.secondary_drying_status_target_temperature,
        "secondary_dry_status_total_duration": printer.secondary_drying_status_total_duration,
        "secondary_dry_status_remaining_time": printer.secondary_drying_status_remaining_time,
        "job_name": printer.latest_project_name,
        "job_progress": printer.latest_project_progress_percentage,
        "job_time_elapsed": printer.latest_project_print_time_elapsed_minutes,
        "job_time_remaining": printer.latest_project_print_time_remaining_minutes,
        "job_in_progress": printer.latest_project_print_in_progress,
        "job_complete": printer.latest_project_print_complete,
        "job_failed": printer.latest_project_print_failed,
        "job_is_paused": printer.latest_project_print_is_paused,
        "job_image_url": printer.latest_project_image_url,
        "job_state": printer.latest_project_print_status,
        "job_eta": printer.latest_project_print_approximate_completion_time,
        "job_current_layer": printer.latest_project_print_current_layer,
        "job_total_layers": printer.latest_project_print_total_layers,
        "target_nozzle_temp": printer.latest_project_target_nozzle_temp,
        "target_hotbed_temp": printer.latest_project_target_hotbed_temp,
        "job_speed_mode": printer.latest_project_print_speed_mode_string,
        "print_speed_pct": printer.latest_project_print_speed_pct,
        "job_z_thick": printer.latest_project_z_thick,
        "fan_speed_pct": printer.latest_project_fan_speed_pct,
        "aux_fan_speed_pct": printer.aux_fan_speed_pct,
        "box_fan_level": printer.box_fan_level,
        "job_model_height": printer.latest_project_print_model_height,
        "job_anti_alias_count": printer.latest_project_print_anti_alias_count,
        "job_on_time": printer.latest_project_print_on_time,
        "job_off_time": printer.latest_project_print_off_time,
        "job_bottom_time": printer.latest_project_print_bottom_time,
        "job_bottom_layers": printer.latest_project_print_bottom_layers,
        "job_z_up_height": printer.latest_project_print_z_up_height,
        "job_z_up_speed": printer.latest_project_print_z_up_speed,
        "job_z_down_speed": printer.latest_project_print_z_down_speed,
        "manual_mqtt_connection_enabled": mqtt_manually_connected,
    }

    attributes = {
        "ace_spools": {
            "spool_info": primary_ace_spool_info,
        },
        "ace_pro_attributes": {
            "fw_version": printer.primary_multi_color_box_fw_firmware_version,
            "fw_latest_version": printer.primary_multi_color_box_fw_available_version,
            "fw_update_in_progress": printer.primary_multi_color_box_fw_total_progress,
            "runout_refill": printer.primary_multi_color_box_auto_feed,
            "current_temperature": printer.primary_multi_color_box_current_temperature,
            "spool_info": primary_ace_spool_info,
            "dry_status_is_drying": printer.primary_drying_status_is_drying,
            "dry_status_code": printer.primary_drying_status_raw_status_code,
            "dry_status_target_temperature": printer.primary_drying_status_target_temperature,
            "dry_status_total_duration": printer.primary_drying_status_total_duration,
            "dry_status_remaining_time": printer.primary_drying_status_remaining_time,
            "connected_ace_units": printer.connected_ace_units,
        },
        "ace_pro_1_firmware": {
            "latest_version": printer.primary_multi_color_box_fw_available_version,
            "in_progress": printer.primary_multi_color_box_fw_total_progress,
        },
        "ace_pro_1_dryer_status": {
            "is_drying": printer.primary_drying_status_is_drying,
        },
        "ace_pro_1_slot_1": {
            "spool": primary_ace_spool_info[0] if primary_ace_spool_info and len(primary_ace_spool_info) > 0 else None,
        },
        "ace_pro_1_slot_2": {
            "spool": primary_ace_spool_info[1] if primary_ace_spool_info and len(primary_ace_spool_info) > 1 else None,
        },
        "ace_pro_1_slot_3": {
            "spool": primary_ace_spool_info[2] if primary_ace_spool_info and len(primary_ace_spool_info) > 2 else None,
        },
        "ace_pro_1_slot_4": {
            "spool": primary_ace_spool_info[3] if primary_ace_spool_info and len(primary_ace_spool_info) > 3 else None,
        },
        "secondary_ace_spools": {
            "spool_info": secondary_ace_spool_info,
        },
        "secondary_ace_pro_attributes": {
            "fw_version": printer.secondary_multi_color_box_fw_firmware_version,
            "fw_latest_version": printer.secondary_multi_color_box_fw_available_version,
            "fw_update_in_progress": printer.secondary_multi_color_box_fw_total_progress,
            "runout_refill": printer.secondary_multi_color_box_auto_feed,
            "current_temperature": printer.secondary_multi_color_box_current_temperature,
            "spool_info": secondary_ace_spool_info,
            "dry_status_is_drying": printer.secondary_drying_status_is_drying,
            "dry_status_code": printer.secondary_drying_status_raw_status_code,
            "dry_status_target_temperature": printer.secondary_drying_status_target_temperature,
            "dry_status_total_duration": printer.secondary_drying_status_total_duration,
            "dry_status_remaining_time": printer.secondary_drying_status_remaining_time,
            "connected_ace_units": printer.connected_ace_units,
        },
        "ace_pro_2_firmware": {
            "latest_version": printer.secondary_multi_color_box_fw_available_version,
            "in_progress": printer.secondary_multi_color_box_fw_total_progress,
        },
        "ace_pro_2_dryer_status": {
            "is_drying": printer.secondary_drying_status_is_drying,
        },
        "ace_pro_2_slot_1": {
            "spool": secondary_ace_spool_info[0] if secondary_ace_spool_info and len(secondary_ace_spool_info) > 0 else None,
        },
        "ace_pro_2_slot_2": {
            "spool": secondary_ace_spool_info[1] if secondary_ace_spool_info and len(secondary_ace_spool_info) > 1 else None,
        },
        "ace_pro_2_slot_3": {
            "spool": secondary_ace_spool_info[2] if secondary_ace_spool_info and len(secondary_ace_spool_info) > 2 else None,
        },
        "ace_pro_2_slot_4": {
            "spool": secondary_ace_spool_info[3] if secondary_ace_spool_info and len(secondary_ace_spool_info) > 3 else None,
        },
        "file_list_local": {
            "file_info": file_list_local,
        },
        "file_list_udisk": {
            "file_info": file_list_udisk,
        },
        "file_list_cloud": {
            "file_info": file_list_cloud,
        },
        "target_nozzle_temp": {
            "limit_min": printer.latest_project_temp_min_nozzle,
            "limit_max": printer.latest_project_temp_max_nozzle,
        },
        "target_hotbed_temp": {
            "limit_min": printer.latest_project_temp_min_hotbed,
            "limit_max": printer.latest_project_temp_max_hotbed,
        },
        "job_speed_mode": {
            "available_modes": printer.latest_project_available_print_speed_modes_data_object,
            "print_speed_mode_code": printer.latest_project_print_speed_mode,
        },
        "current_status": {
            "model": printer.model,
            "machine_type": printer.machine_type,
            "supported_functions": printer.supported_function_strings,
            "material_type": printer.material_type,
            "device_status_code": printer.device_status,
            "is_printing_code": printer.is_printing,
            "print_status_code": printer.latest_project_raw_print_status,
            "peripherals": printer.connected_peripherals,
            "total_material_used": printer.material_used,
            "total_print_time_hrs": printer.total_print_time_hrs,
            "total_print_time_dhm": printer.total_print_time_dhm_str,
            "job_download_progress": printer.latest_project_download_progress_percentage,
        },
        "dry_status_is_drying": {
            "dry_status_code": printer.primary_drying_status_raw_status_code,
        },
        "secondary_dry_status_is_drying": {
            "secondary_dry_status_code": printer.secondary_drying_status_raw_status_code,
        },
        "job_name": {
            "created_timestamp": printer.latest_project_created_timestamp,
            "finished_timestamp": printer.latest_project_finished_timestamp,
            "print_total_time": printer.latest_project_print_total_time,
            "print_total_time_minutes": printer.latest_project_print_total_time_minutes,
            "print_total_time_dhm": printer.latest_project_print_total_time_dhm_str,
            "print_supplies_usage": printer.latest_project_print_supplies_usage,
            "print_status_message": printer.latest_project_print_status_message,
        },
        "fw_version": {
            "latest_version": printer.fw_version.available_version if printer.fw_version else None,
            "in_progress": printer.fw_version.total_progress if printer.fw_version else None,
        },
        "multi_color_box_fw_version": {
            "latest_version": printer.primary_multi_color_box_fw_available_version,
            "in_progress": printer.primary_multi_color_box_fw_total_progress,
        },
        "secondary_multi_color_box_fw_version": {
            "latest_version": printer.secondary_multi_color_box_fw_available_version,
            "in_progress": printer.secondary_multi_color_box_fw_total_progress,
        },
    }

    for x in range(MAX_DRYING_PRESETS):
        preset_duration, preset_temperature = get_drying_preset_from_entry_options(
            entry_options,
            x + 1,
        )
        attributes[f"{ENTITY_ID_DRYING_START_PRESET_}{x + 1}"] = {
            "duration": preset_duration,
            "temperature": preset_temperature,
        }
        attributes[f"secondary_{ENTITY_ID_DRYING_START_PRESET_}{x + 1}"] = {
            "duration": preset_duration,
            "temperature": preset_temperature,
        }

    return {
        "states": states,
        "attributes": attributes,
    }
