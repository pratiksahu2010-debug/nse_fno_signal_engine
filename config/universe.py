"""Default user-editable universes. Instrument keys are resolved dynamically at runtime."""
from __future__ import annotations

CORE_INDICES: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
CORE_STOCKS: tuple[str, ...] = (
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK",
    "KOTAKBANK", "LT", "ITC", "BHARTIARTL", "TATAMOTORS", "TATASTEEL", "M&M",
    "MARUTI", "BAJFINANCE", "BAJAJFINSV", "HINDUNILVR", "SUNPHARMA", "ONGC",
    "NTPC", "POWERGRID", "COALINDIA", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "HINDALCO", "VEDL", "WIPRO", "HCLTECH", "TECHM", "ULTRACEMCO", "TITAN",
    "ASIANPAINT", "INDUSINDBK", "BANKBARODA", "PNB", "CANBK", "FEDERALBNK",
    "IDFCFIRSTB", "DLF", "DIVISLAB", "DRREDDY", "CIPLA", "EICHERMOT",
    "HEROMOTOCO", "BPCL", "IOC", "GAIL", "SBILIFE",
)
CORE_UNIVERSE: tuple[str, ...] = CORE_INDICES + CORE_STOCKS

# The runtime builds the default 150-symbol universe from current F&O instruments and
# 20-day median turnover. This file is the explicit manual override, not a hardcoded list.
EXPLOSION_MANUAL_OVERRIDE_PATH = "config/explosion_universe.json"
