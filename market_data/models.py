"""Market data models and candle normalization."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

@dataclass(slots=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    oi: float = 0.0
    def as_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(slots=True)
class Tick:
    instrument_key: str
    symbol: str
    ltp: float
    timestamp: datetime
    volume: float = 0.0
    oi: float = 0.0
    bid: float | None = None
    ask: float | None = None
