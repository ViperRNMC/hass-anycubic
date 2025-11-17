"""The Anycubic integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AnycubicDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

_PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.IMAGE, Platform.LIGHT, Platform.SENSOR, Platform.FAN, Platform.CAMERA, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anycubic from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get("host")

    # Create the coordinator (handles polling and updating credentials)
    coordinator = AnycubicDataUpdateCoordinator(hass, host)
    coordinator.config_entry = entry
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    if coordinator and getattr(coordinator, "mqtt", None):
        disconnect = getattr(coordinator.mqtt, "disconnect", None)
        if disconnect:
            if callable(disconnect):
                # Check if disconnect is a coroutine function
                import inspect
                if inspect.iscoroutinefunction(disconnect):
                    await disconnect()
                else:
                    disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    return unload_ok
