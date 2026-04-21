"""Flat entity definitions for the Anycubic integration."""

LIGHT_DEFINITION = {"name": "Chamber Light", "key": "chamber_printer", "type_id": 2, "icon": "mdi:lightbulb"}

BUTTON_DEFINITIONS = [
    {"name": "Home All", "key": "home_all", "type": "axis", "action": "move", "axis": 5, "icon": "mdi:axis-arrow"},
    {"name": "Home XY", "key": "home_xy", "type": "axis", "action": "move", "axis": 4, "icon": "mdi:axis-arrow"},
    {"name": "Home Z", "key": "home_z", "type": "axis", "action": "move", "axis": 3, "icon": "mdi:axis-arrow"},
    {"name": "Print Stop", "key": "print_stop", "type": "print", "action": "stop", "icon": "mdi:stop"},
    {"name": "Print Pause", "key": "print_pause", "type": "print", "action": "pause", "icon": "mdi:pause"},
    {"name": "Print Resume", "key": "print_resume", "type": "print", "action": "resume", "icon": "mdi:play"},
    {"name": "Nozzle Heater Off", "key": "nozzle_heater_off", "type": "temperature", "action": "setNozzleTemp", "data": {"target_nozzle_temp": 0}, "icon": "mdi:printer-3d-nozzle-off"},
    {"name": "Bed Heater Off", "key": "bed_heater_off", "type": "temperature", "action": "setHotbedTemp", "data": {"target_hotbed_temp": 0}, "icon": "mdi:heating-coil"},
]

SELECT_DEFINITIONS = [
    {"name": "Speed", "key": "print_speed_mode", "icon": "mdi:run", "options": ["silent", "standard", "sport"], "value_map": {"silent": 1, "standard": 0, "sport": 2}},
]

SWITCH_DEFINITIONS = [
    {"name": "Drying", "key": "ace_pro_drying", "type": "multiColorBox", "action_on": "setDry", "action_off": "setDry", "data_template_on": {"multi_color_box": [{"id": "{box_id}", "drying_status": {"status": 1, "target_temp": "{target_temp}", "duration": "{duration}"}}]}, "data_template_off": {"multi_color_box": [{"id": "{box_id}", "drying_status": {"status": 0}}]}, "device_type": "ace_pro", "per_box": True},
    {"name": "Auto Feed", "key": "ace_pro_auto_feed", "type": "multiColorBox", "action_on": "setAutoFeed", "action_off": "setAutoFeed", "data_template_on": {"multi_color_box": [{"id": "{box_id}", "auto_feed": 1}]}, "data_template_off": {"multi_color_box": [{"id": "{box_id}", "auto_feed": 0}]}, "device_type": "ace_pro", "per_box": True},
]

FAN_DEFINITIONS = [
    {"name": "Main Fan", "key": "main", "icon": "mdi:fan", "data_key": "fan_speed_pct"},
    {"name": "Aux Fan", "key": "aux", "icon": "mdi:fan", "data_key": "aux_fan_speed_pct"},
    {"name": "Box Fan", "key": "box", "icon": "mdi:fan", "data_key": "box_fan_level"},
]

NUMBER_DEFINITIONS = [
    {"name": "Target Nozzle Temperature", "key": "target_nozzle_temp", "data_key": "target_nozzle_temp", "min": 0, "max": 320, "icon": "mdi:printer-3d-nozzle"},
    {"name": "Target Hotbed Temperature", "key": "target_hotbed_temp", "data_key": "target_hotbed_temp", "min": 0, "max": 120, "icon": "mdi:heating-coil"},
    {"name": "Drying Target", "key": "ace_pro_drying_target", "min": 35, "max": 55, "unit": "°C", "kind": "drying_target", "device_type": "ace_pro", "per_box": True},
    {"name": "Drying Duration", "key": "ace_pro_drying_duration", "min": 1, "max": 1440, "unit": "min", "kind": "drying_duration", "device_type": "ace_pro", "per_box": True},
]

SENSOR_DEFINITIONS = [
    {"name": "Printer Info", "key": "printer_info", "data_path": ("info", "data", "state"), "icon": "mdi:information-outline"},
    {"name": "Nozzle Temperature", "key": "nozzle_temp", "data_path": ("tempature", "data", "curr_nozzle_temp"), "unit": "°C", "icon": "mdi:thermometer"},
    {"name": "Hotbed Temperature", "key": "hotbed_temp", "data_path": ("tempature", "data", "curr_hotbed_temp"), "unit": "°C", "icon": "mdi:thermometer"},
    {"name": "Print Status", "key": "print_status", "data_path": ("info", "data", "project", "state"), "icon": "mdi:printer-3d"},
    {"name": "Print Progress", "key": "print_progress", "data_path": ("info", "data", "project", "progress"), "unit": "%", "icon": "mdi:progress-clock"},
    {"name": "Print Current Layer", "key": "print_curr_layer", "data_path": ("print", "data", "curr_layer"), "icon": "mdi:layers"},
    {"name": "Print Filename", "key": "print_filename", "data_path": ("print", "data", "filename"), "icon": "mdi:file-document"},
    {"name": "Print Time", "key": "print_time", "data_path": ("print", "data", "print_time"), "icon": "mdi:timer", "formatter": "_minutes_to_hhmm"},
    {"name": "Print Remaining Time", "key": "print_remain_time", "data_path": ("print", "data", "remain_time"), "icon": "mdi:timer-off", "formatter": "_minutes_to_hhmm"},
    {"name": "Print ETA", "key": "job_eta", "data_path": ("print", "data", "remain_time"), "icon": "mdi:timer-outline", "formatter": "_minutes_to_hhmm"},
    {"name": "Print Z Thickness", "key": "job_z_thickness", "data_path": ("print", "data", "z_thickness"), "unit": "mm", "icon": "mdi:axis-z-arrow"},
    {"name": "Print Model Name", "key": "print_model_name", "data_path": ("print", "data", "source_info", "models", 0, "name"), "icon": "mdi:file-outline"},
    {"name": "Print Supplies Usage", "key": "print_supplies_usage", "data_path": ("print", "data", "supplies_usage"), "icon": "mdi:cube-scan", "unit": "g"},
    {"name": "Print Total Layers", "key": "print_total_layers", "data_path": ("print", "data", "total_layers"), "icon": "mdi:layers"},
    {"name": "Temperature", "key": "{box_id}_temp", "data_path": ("multiColorBox", "data", "multi_color_box"), "data_field": "temp", "unit": "°C", "icon": "mdi:thermometer", "device_type": "ace_pro", "per_box": True},
    {"name": "Loaded", "key": "ace_pro_box_{box_id}_loaded", "data_path": ("multiColorBox", "data", "multi_color_box"), "data_field": "loaded_slot", "icon": "mdi:folder-arrow-right", "device_type": "ace_pro", "per_box": True},
    {"name": "Slot {slot_index}", "key": "ace_pro_box_{box_id}_slot_{slot_index}", "data_path": ("multiColorBox", "data", "multi_color_box"), "slot_index": "{slot_index}", "icon": "mdi:tray", "device_type": "ace_pro", "per_box": True, "per_slot": True},
    {"name": "Loaded", "key": "extfilbox_loaded", "data_path": ("extfilbox", "data", "loaded"), "icon": "mdi:package-variant-closed", "device_type": "extfilbox"},
    {"name": "Slot", "key": "extfilbox_slot", "data_path": ("extfilbox", "data", "multi_color_box", 0), "icon": "mdi:tray", "device_type": "extfilbox", "per_box": False, "per_slot": False},
]

BINARY_DEFINITIONS = [
    {"name": "Printer Online", "key": "printer_online", "type": "printer_online", "device_class": "connectivity", "entity_category": "diagnostic"},
    {"name": "Print Failed", "key": "job_failed", "type": "job_failed", "device_class": "problem", "entity_category": "diagnostic"},
    {"name": "Print Problem", "key": "print_problem", "type": "print_problem", "device_class": "problem", "entity_category": "diagnostic"},
    {"name": "Nozzle Heating", "key": "nozzle_heating", "type": "nozzle_heating", "device_class": "heat", "icon": "mdi:printer-3d-nozzle-heat"},
    {"name": "Bed Heating", "key": "bed_heating", "type": "bed_heating", "device_class": "heat"},
]
