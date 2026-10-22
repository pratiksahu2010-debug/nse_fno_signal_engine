"""NSE trading calendar helpers; special sessions can override normal weekdays."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.defaults import MARKET_CLOSE, MARKET_OPEN, TZ

log = logging.getLogger(__name__)
IST = ZoneInfo(TZ)

@dataclass(frozen=True, slots=True)
class MarketCalendar:
    holidays_path: Path = Path("config/nse_holidays.json")

    def _data(self) -> dict:
        try:
            return json.loads(self.holidays_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log.warning("NSE holiday file missing: %s; weekday-only calendar fallback active", self.holidays_path)
            return {"year": None, "holidays": [], "special_sessions": []}
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Cannot read NSE holiday file %s: %s", self.holidays_path, exc)
            return {"year": None, "holidays": [], "special_sessions": []}

    def is_trading_day(self, day: date) -> bool:
        data = self._data()
        if data.get("year") != day.year:
            log.warning("NSE holiday file year %r does not cover %s; verify official calendar", data.get("year"), day.year)
        specials = {item.get("date") for item in data.get("special_sessions", []) if item.get("date")}
        holidays = {item for item in data.get("holidays", []) if isinstance(item, str)}
        return day.isoformat() in specials or (day.weekday() < 5 and day.isoformat() not in holidays)

    def session_bounds(self, day: date) -> tuple[datetime, datetime] | None:
        if not self.is_trading_day(day):
            return None
        start, end = MARKET_OPEN, MARKET_CLOSE
        for item in self._data().get("special_sessions", []):
            if item.get("date") == day.isoformat():
                start = time.fromisoformat(item.get("open", start.isoformat()))
                end = time.fromisoformat(item.get("close", end.isoformat()))
                break
        return datetime.combine(day, start, IST), datetime.combine(day, end, IST)

    def is_market_open(self, instant: datetime | None = None) -> bool:
        instant = (instant or datetime.now(IST)).astimezone(IST)
        bounds = self.session_bounds(instant.date())
        return bool(bounds and bounds[0] <= instant < bounds[1])
