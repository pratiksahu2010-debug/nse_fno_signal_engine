"""Dynamic instrument-key resolver with cached instrument master."""
from __future__ import annotations
import logging, time
from typing import Any

from config.universe import CORE_UNIVERSE

log = logging.getLogger(__name__)

# NSE symbol changes: keep the requested legacy name but resolve to the current
# listed underlying where that alias is unambiguous.
SYMBOL_ALIASES = {
    "TATAMOTORS": ("TMPV", "TATAMOTORS"),
}


class InstrumentResolver:
    def __init__(self, rest, cache_seconds: int = 86400):
        self.rest = rest
        self.cache_seconds = cache_seconds
        self.rows = []
        self.loaded_at = 0.0

    async def refresh(self, force=False):
        if self.rows and not force and time.time() - self.loaded_at < self.cache_seconds:
            return
        self.rows = await self.rest.instrument_list()
        self.loaded_at = time.time()
        log.info("Instrument master loaded rows=%d", len(self.rows))

    @staticmethod
    def _field(row, *names, default=None):
        for name in names:
            if row.get(name) is not None:
                return row[name]
        return default

    async def resolve(self, symbol: str, prefer: str = "NSE_EQ") -> str | None:
        await self.refresh()
        requested = symbol.upper().strip()
        candidates = SYMBOL_ALIASES.get(requested, (requested,))
        for candidate in candidates:
            matches = []
            for row in self.rows:
                trad = str(self._field(row, "trading_symbol", "tradingsymbol", "symbol", default="")).upper()
                name = str(self._field(row, "name", "underlying_symbol", default="")).upper()
                seg = str(self._field(row, "segment", "exchange", default="")).upper()
                key = self._field(row, "instrument_key", "instrumentKey")
                if key and (trad == candidate or name == candidate):
                    matches.append((0 if prefer.upper() in seg else 1, str(key)))
            if matches:
                resolved = sorted(matches)[0][1]
                if candidate != requested:
                    log.info("Resolved legacy symbol %s using current alias %s", requested, candidate)
                return resolved
        return None

    async def resolve_many(self, symbols=None) -> dict[str, str]:
        result = {}
        for symbol in symbols or CORE_UNIVERSE:
            key = await self.resolve(
                symbol,
                "NSE_INDEX" if symbol in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"} else "NSE_EQ",
            )
            if key:
                result[symbol] = key
            else:
                log.warning("No instrument key resolved for %s", symbol)
        return result

    async def explosion_universe(self, limit=150, min_median_turnover=5e7) -> list[str]:
        """Rank only when genuine historical turnover values are supplied by the data source.

        Upstox's instrument master does not provide a verified 20-session median turnover.
        The curated manual override in config/explosion_universe.json is the safe fallback.
        """
        import json
        from pathlib import Path
        path = Path("config/explosion_universe.json")
        if path.exists():
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(obj, list) and obj:
                    return list(dict.fromkeys(str(item).upper() for item in obj if str(item).strip()))[:limit]
            except (OSError, ValueError):
                log.exception("Invalid explosion override; ignoring")
        ranked = []
        for row in self.rows:
            symbol = str(self._field(row, "underlying_symbol", "trading_symbol", default="")).upper()
            segment = str(self._field(row, "segment", default="")).upper()
            kind = str(self._field(row, "instrument_type", default="")).upper()
            turnover = self._field(row, "median_turnover_20d", "median_turnover")
            if symbol and ("FO" in segment or kind in {"FUT", "CE", "PE"}) and turnover is not None:
                try:
                    value = float(turnover)
                except (TypeError, ValueError):
                    continue
                if value >= min_median_turnover:
                    ranked.append((value, symbol))
        if not ranked:
            log.warning("Explosion universe unavailable: no verified 20-day median turnover values; configure config/explosion_universe.json")
            return []
        return list(dict.fromkeys(symbol for _, symbol in sorted(ranked, reverse=True)))[:limit]
