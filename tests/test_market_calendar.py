from datetime import date, datetime
from pathlib import Path
from utils.market_calendar import MarketCalendar, IST

def test_weekday_fallback_when_file_missing(tmp_path):
    cal = MarketCalendar(tmp_path / "missing.json")
    assert cal.is_trading_day(date(2026, 10, 22))
    assert not cal.is_trading_day(date(2026, 10, 24))

def test_market_open_bounds(tmp_path):
    holiday_file = tmp_path / "holidays.json"
    holiday_file.write_text('{"year": 2026, "holidays": [], "special_sessions": []}', encoding="utf-8")
    cal = MarketCalendar(holiday_file)
    assert cal.is_market_open(datetime(2026, 10, 22, 9, 15, tzinfo=IST))
    assert not cal.is_market_open(datetime(2026, 10, 22, 15, 30, tzinfo=IST))


def test_configured_2026_holidays():
    cal = MarketCalendar(Path('config/nse_holidays.json'))
    assert not cal.is_trading_day(date(2026, 10, 20))
    assert not cal.is_trading_day(date(2026, 11, 10))
