from __future__ import annotations

"""Time utilities for the Anycubic integration."""

from . import ErrorsSystem

import re
from datetime import timedelta
from typing import Optional

REX_PRINT_TOTAL_TIME: re.Pattern[str] = re.compile(r"^([\d]+)hour([\d]+)min$")


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


def timedelta_to_total_minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60.0


def timedelta_to_total_hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600.0


def timedelta_to_dhm_string(delta: timedelta) -> str:
    days = delta.days
    hours, remain_sec = divmod(delta.seconds, 3600)
    mins = int(remain_sec / 60)
    return f"{days}:{hours}:{mins}"


def hour_min_time_string_to_delta(time_string: str) -> timedelta:
    match = REX_PRINT_TOTAL_TIME.match(time_string)
    if match:
        hours = int(match.group(1))
        mins = int(match.group(2))
        return timedelta(minutes=mins, hours=hours)
    raise ValueError(ErrorsSystem.time_regex_no_match)


def float_minutes_string_to_delta(time_string: str) -> timedelta:
    minutes = float(time_string)
    total_seconds = int(minutes * 60)
    return timedelta(seconds=total_seconds)


def time_duration_string_to_delta(time_string: str | None) -> timedelta:
    if isinstance(time_string, str):
        try:
            return float_minutes_string_to_delta(time_string)
        except ValueError:
            pass
        try:
            return hour_min_time_string_to_delta(time_string)
        except ValueError:
            pass
    return timedelta()
