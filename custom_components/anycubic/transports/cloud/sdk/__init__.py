"""Public SDK surface for cloud transport.

Exports are resolved lazily to keep import overhead low when callers only need
MQTT/auth pieces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core.api import AnycubicAPI, AnycubicMQTTAPI
    from .core.auth import AnycubicAuthMode

__all__ = ["AnycubicAPI", "AnycubicMQTTAPI", "AnycubicAuthMode"]


def __getattr__(name: str) -> Any:
    if name == "AnycubicAuthMode":
        from .core.auth import AnycubicAuthMode

        return AnycubicAuthMode
    if name == "AnycubicMQTTAPI":
        from .core.api import AnycubicMQTTAPI

        return AnycubicMQTTAPI
    if name == "AnycubicAPI":
        from .core.api import AnycubicAPI

        return AnycubicAPI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
