"""Path utilities for extracting nested values from dict/list structures.

Provides a safe `get_from_path` helper used by sensors and other modules to
navigate nested MQTT JSON without raising KeyError/IndexError.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, Union


def get_from_path(data: Any, path: Sequence[Union[str, int]], default: Any = None) -> Any:
    """Safely return the value at `path` inside `data`, or `default`.

    - `path` is a sequence of keys (str) and/or indices (int).
    - Returns `default` (None by default) when any step is missing or types mismatch.
    """
    cur = data
    for p in path:
        if isinstance(p, int):
            if not isinstance(cur, list):
                return default
            if p < 0 or p >= len(cur):
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(p)
            if cur is None:
                return default
    return cur
