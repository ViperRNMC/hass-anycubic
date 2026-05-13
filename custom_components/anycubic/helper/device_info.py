"""Shared device registry metadata helpers for Anycubic entities."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers import device_registry as dr

from ..const import (
    CONNECTION_MODE_CLOUD,
    DOMAIN,
    EXTFILBOX_DEVICE_BASE,
    ACE_PRO_DEVICE_BASE,
    MANUFACTURER,
    MODEL,
)


def build_main_device_info(coordinator) -> dict[str, Any]:
    """Build rich device metadata for the primary printer device."""
    entry = coordinator.config_entry
    info_data = (coordinator.data.get("info") or {}).get("data") or {}
    model = info_data.get("model") or entry.data.get("modelName") or MODEL
    printer_name = (
        info_data.get("name")
        or info_data.get("device_name")
        or entry.data.get("name")
    )
    if not printer_name:
        model_text = str(model).strip() if model is not None else ""
        if model_text.lower().startswith(MANUFACTURER.lower()):
            printer_name = model_text
        else:
            printer_name = f"{MANUFACTURER} {model_text}".strip()
    sw_version = (
        info_data.get("version")
        or entry.data.get("version")
        or entry.data.get("firmware")
    )

    printer_id = (
        info_data.get("printer_id")
        or entry.data.get("printer_id")
        or entry.data.get("deviceId")
        or entry.data.get("cloud_device_id")
    )
    serial_number = (
        info_data.get("serial_number")
        or entry.data.get("serial_number")
    )
    if serial_number is not None:
        serial_number = str(serial_number)

    mac_address = (
        info_data.get("machine_mac")
        or info_data.get("mac")
        or entry.data.get("machine_mac")
        or entry.data.get("mac")
        or entry.data.get("macAddress")
        or entry.data.get("wifiMac")
    )
    if mac_address is not None:
        mac_address = dr.format_mac(str(mac_address)) or str(mac_address)

    ip_address = (
        info_data.get("ip")
        or info_data.get("ip_address")
        or entry.data.get("host")
    )
    if ip_address is not None:
        ip_address = str(ip_address)

    hardware_version = (
        info_data.get("hardware_version")
        or info_data.get("machine_version")
        or info_data.get("printer_type")
        or entry.data.get("hardware")
        or entry.data.get("hardware_version")
    )
    if not hardware_version and printer_id:
        hardware_version = str(printer_id)

    configuration_url = None
    if entry.data.get("connection_mode") != CONNECTION_MODE_CLOUD:
        config_host = entry.data.get("host") or ip_address
        if config_host:
            configuration_url = f"http://{config_host}"

    device_info: dict[str, Any] = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": str(printer_name),
        "manufacturer": MANUFACTURER,
        "model": model,
    }
    if sw_version:
        device_info["sw_version"] = str(sw_version)
    if hardware_version:
        device_info["hw_version"] = str(hardware_version)
    if mac_address:
        device_info["connections"] = {(dr.CONNECTION_NETWORK_MAC, mac_address)}
    if configuration_url:
        device_info["configuration_url"] = configuration_url
    return device_info


def build_ace_device_info(coordinator, box_id: int, firmware: str | None = None) -> dict[str, Any]:
    """Build device metadata for an ACE Pro box."""
    entry_id = getattr(coordinator.config_entry, "entry_id", "unknown")
    device_info: dict[str, Any] = {
        "identifiers": {(DOMAIN, f"{entry_id}_ace_pro_box_{box_id}")},
        "name": f"ACE Pro Box {box_id}",
        "via_device": (DOMAIN, entry_id),
        "manufacturer": ACE_PRO_DEVICE_BASE["manufacturer"],
        "model": ACE_PRO_DEVICE_BASE["model"],
    }
    if firmware:
        device_info["sw_version"] = str(firmware)
    return device_info


def build_extfilbox_device_info(coordinator) -> dict[str, Any]:
    """Build device metadata for the external filament rack."""
    entry_id = getattr(coordinator.config_entry, "entry_id", "unknown")
    return {
        "identifiers": {(DOMAIN, f"{entry_id}_extfilbox")},
        "via_device": (DOMAIN, entry_id),
        **EXTFILBOX_DEVICE_BASE,
    }