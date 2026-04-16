"""Abstract transport base for Anycubic coordinator."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class AnycubicTransport(ABC):
    """Abstract transport layer; LAN or Cloud implementation plugs in here."""

    @abstractmethod
    async def async_setup(self, on_data: Callable[[dict], None]) -> None:
        """Connect and start receiving data. Call on_data for every incoming update."""

    @abstractmethod
    async def async_send_command(self, msg_type: str, action: str, data: Any = None) -> None:
        """Send a command to the device."""

    @abstractmethod
    async def async_query_topic(self, topic: str, action: str = "query") -> None:
        """Request fresh data for a topic."""

    @abstractmethod
    async def async_teardown(self) -> None:
        """Disconnect and clean up."""

    async def async_open_camera_stream(self) -> str | None:
        """Request the printer to start streaming and return the stream URL.

        Returns an HTTP-FLV URL when the transport can determine the printer IP,
        or None if streaming is not supported / the IP is unknown.
        Subclasses override this to provide transport-specific behaviour.
        """
        return None
