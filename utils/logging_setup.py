"""Logging setup with IST timestamps."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config.defaults import TZ

class ISTFormatter(logging.Formatter):
    """Format log timestamps in Asia/Kolkata regardless of host timezone."""
    converter = staticmethod(lambda timestamp: datetime.fromtimestamp(timestamp, ZoneInfo(TZ)).timetuple())


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s IST | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(ISTFormatter(handler.formatter._fmt if handler.formatter else None, "%Y-%m-%d %H:%M:%S"))
