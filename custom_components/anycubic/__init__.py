"""The Anycubic integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONNECTION_MODE_CLOUD, CONNECTION_MODE_LAN, DOMAIN
from .coordinator import async_create_coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS_LAN = [
    "sensor",
    "image",
    "switch",
    "select",
    "button",
    "fan",
    "light",
    "number",
    "binary_sensor",
]

PLATFORMS_CLOUD = [
    "sensor",
    "image",
    "switch",
    "select",
    "button",
    "fan",
    "light",
    "number",
    "binary_sensor",
]

# Add `update` platform only when the file is present to avoid import errors
try:
    if (Path(__file__).parent / "update.py").exists():
        PLATFORMS_CLOUD.append("update")
except Exception:
    pass


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anycubic from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = await async_create_coordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    mode = entry.data.get("connection_mode", CONNECTION_MODE_LAN)
    platforms = PLATFORMS_CLOUD if mode == CONNECTION_MODE_CLOUD else PLATFORMS_LAN
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        try:
            await coordinator.async_shutdown()
        except Exception:
            _LOGGER.debug("Coordinator shutdown failed during unload", exc_info=True)

    mode = entry.data.get("connection_mode", CONNECTION_MODE_LAN)
    platforms = PLATFORMS_CLOUD if mode == CONNECTION_MODE_CLOUD else PLATFORMS_LAN
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    return unload_ok
