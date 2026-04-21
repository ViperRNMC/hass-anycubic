"""Typed models for Anycubic LAN discovery payloads."""

from __future__ import annotations

from typing import TypedDict


class DiscoveryInfo(TypedDict, total=False):
    token: str
    ctrlInfoUrl: str


class ControlInfo(TypedDict, total=False):
    encrypted_info: str
    local_token: str
    http_token: str
