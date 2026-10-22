"""Dynamic instrument-key resolver with cached instrument master."""
from __future__ import annotations
import asyncio, logging, time
from typing import Any
from config.universe import CORE_UNIVERSE
log=logging.getLogger(__name__)
class InstrumentResolver:
    def __init__(self, rest, cache_seconds: int=86400): self.rest=rest; self.cache_seconds=cache_seconds; self.rows=[]; self.loaded_at=0.0
    async def refresh(self, force=False):
        if self.rows and not force and time.time()-self.loaded_at<self.cache_seconds: return
        self.rows=await self.rest.instrument_list(); self.loaded_at=time.time(); log.info("Instrument master loaded rows=%d",len(self.rows))
    @staticmethod
    def _field(row,*names,default=None):
        for n in names:
            if row.get(n) is not None:return row[n]
        return default
    async def resolve(self, symbol: str, prefer: str="NSE_EQ")->str|None:
        await self.refresh(); s=symbol.upper().strip()
        matches=[]
        for row in self.rows:
            trad=str(self._field(row,"trading_symbol","tradingsymbol","symbol",default="")).upper()
            name=str(self._field(row,"name","underlying_symbol",default="")).upper()
            seg=str(self._field(row,"segment","exchange",default=""))
            key=self._field(row,"instrument_key","instrumentKey")
            if key and (trad==s or name==s): matches.append((0 if prefer in seg else 1,str(key)))
        return sorted(matches)[0][1] if matches else None
    async def resolve_many(self, symbols=None)->dict[str,str]:
        result={}
        for s in symbols or CORE_UNIVERSE:
            key=await self.resolve(s, "NSE_INDEX" if s in {"NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"} else "NSE_EQ")
            if key: result[s]=key
            else: log.warning("No instrument key resolved for %s",s)
        return result
    async def explosion_universe(self, limit=150, min_median_turnover=5e7)->list[str]:
        """Select F&O rows with a turnover field if supplied by master; otherwise fail closed.
        A proper 20-session turnover ranking requires persisted historical turnover data.
        """
        import json, pathlib
        p=pathlib.Path("config/explosion_universe.json")
        if p.exists():
            try:
                obj=json.loads(p.read_text())
                if isinstance(obj,list) and obj: return [str(x).upper() for x in obj[:limit]]
            except Exception: log.exception("Invalid explosion override; ignoring")
        ranked=[]
        for row in self.rows:
            sym=str(self._field(row,"underlying_symbol","trading_symbol",default="")).upper()
            segment=str(self._field(row,"segment",default="")); kind=str(self._field(row,"instrument_type",default="")).upper()
            turnover=self._field(row,"median_turnover_20d","median_turnover")
            if sym and ("FO" in segment or kind in {"FUT","CE","PE"}) and turnover is not None and float(turnover)>=min_median_turnover:
                ranked.append((float(turnover),sym))
        if not ranked:
            log.warning("Explosion universe unavailable: no verified 20-day median turnover values; configure override or implement historical turnover ranking")
            return []
        return list(dict.fromkeys(s for _,s in sorted(ranked,reverse=True)))[:limit]
