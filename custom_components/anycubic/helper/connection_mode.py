"""Connection mode helpers shared across the integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from ..const import CONF_CONNECTION_MODE, CONNECTION_MODE_CLOUD, CONNECTION_MODE_LAN


def get_entry_connection_mode(entry: ConfigEntry) -> str:
    """Return active mode for a config entry.

    Home Assistant standard place for runtime user choice is `entry.options`.
    We keep fallback to `entry.data` for backward compatibility.
    """
    return (
        entry.options.get(CONF_CONNECTION_MODE)
        or entry.data.get(
            CONF_CONNECTION_MODE,
            CONNECTION_MODE_CLOUD if "user_token" in entry.data else CONNECTION_MODE_LAN,
        )
    )


def is_cloud_mode(entry: ConfigEntry) -> bool:
    """True when current entry mode is cloud."""
    return get_entry_connection_mode(entry) == CONNECTION_MODE_CLOUD
