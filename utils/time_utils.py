"""Timezone-aware market time helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.defaults import TZ

IST = ZoneInfo(TZ)

def now_ist() -> datetime:
    """Return the current aware datetime in configured market timezone."""
    return datetime.now(IST)

def epoch_to_ist(epoch_seconds: float) -> datetime:
    """Convert a UTC epoch timestamp to the configured market timezone."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).astimezone(IST)

def ist_to_epoch(value: datetime) -> float:
    """Convert an aware datetime to UTC epoch seconds; reject naive datetimes."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.timestamp()
