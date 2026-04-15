"""Core cloud SDK entrypoints used by transport code.

Exports are resolved lazily to reduce import side effects and startup work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import AnycubicAPI, AnycubicMQTTAPI
    from .auth import AnycubicAuthMode

__all__ = ["AnycubicAPI", "AnycubicMQTTAPI", "AnycubicAuthMode"]


def __getattr__(name: str) -> Any:
    if name == "AnycubicAuthMode":
        from .auth import AnycubicAuthMode

        return AnycubicAuthMode
    if name == "AnycubicMQTTAPI":
        from .api import AnycubicMQTTAPI

        return AnycubicMQTTAPI
    if name == "AnycubicAPI":
        from .api import AnycubicAPI

        return AnycubicAPI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
