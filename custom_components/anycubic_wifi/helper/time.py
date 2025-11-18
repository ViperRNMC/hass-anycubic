"""Time formatting utilities for the Anycubic integration.

Contains helper(s) to format minutes into a human-readable hhmm string.
"""
from __future__ import annotations

from typing import Optional


def minutes_to_hhmm(minutes: Optional[int]) -> str:
    """Format minutes as 'XhYm' or 'Zm' (use '0m' for zero / unknown).

    Examples:
      61 -> '1h1m'
      65 -> '1h5m'
      5  -> '5m'
      0  -> '0m'
    """
    if minutes is None:
        return "0m"
    try:
        m = int(minutes)
    except Exception:
        return str(minutes)
    if m <= 0:
        return "0m"
    hours, mins = divmod(m, 60)
    if hours > 0:
        return f"{hours}h{mins}m"
    return f"{mins}m"
