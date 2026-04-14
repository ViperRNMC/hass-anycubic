"""The Anycubic integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONNECTION_MODE_CLOUD
from .helper.connection_mode import get_entry_connection_mode
from .coordinator import AnycubicRuntimeCoordinator

_LOGGER = logging.getLogger(__name__)


def _cleanup_broken_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stale entities created with UndefinedType sentinel names.

    Those entries have object IDs containing `undefinedtype_singleton` and should
    be recreated from current descriptors with proper names.
    """
    entity_registry = er.async_get(hass)
    stale_entries = [
        registry_entry
        for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if "undefinedtype_singleton" in registry_entry.entity_id
    ]

    for stale_entry in stale_entries:
        _LOGGER.warning("Removing stale entity with invalid name: %s", stale_entry.entity_id)
        entity_registry.async_remove(stale_entry.entity_id)


async def _async_options_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. mode switch)."""
    await hass.config_entries.async_reload(entry.entry_id)

# Platforms for LAN mode
PLATFORMS_LAN = [
    "sensor",
    "switch",
    "select",
    "button",
    "fan",
    "light",
    "camera",
    # "image",
    "number",
    "binary_sensor",
]

# Platforms for Cloud mode (subset mirroring cloud integration)
PLATFORMS_CLOUD = [
    "binary_sensor",
    "button",
    "fan",
    "image",
    "sensor",
    "switch",
    "update",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anycubic from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    mode = get_entry_connection_mode(entry)
    if mode == CONNECTION_MODE_CLOUD and "@" in entry.title:
        printer_ids = entry.data.get("printer_id_list", [])
        if len(printer_ids) == 1:
            new_title = "Anycubic Cloud"
        else:
            new_title = f"Anycubic Cloud ({len(printer_ids)} printers)"
        hass.config_entries.async_update_entry(entry, title=new_title)

    _cleanup_broken_entity_ids(hass, entry)

    coordinator = AnycubicRuntimeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if mode == CONNECTION_MODE_CLOUD:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_CLOUD)
    else:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_LAN)

    entry.async_on_unload(entry.add_update_listener(_async_options_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    mode = get_entry_connection_mode(entry)
    platforms = PLATFORMS_CLOUD if mode == CONNECTION_MODE_CLOUD else PLATFORMS_LAN

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator and hasattr(coordinator, "async_shutdown"):
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
