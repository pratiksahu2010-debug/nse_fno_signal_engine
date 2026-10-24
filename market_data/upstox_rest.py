"""Upstox REST adapter. Uses documented V3 candles and V2 option-chain endpoints."""
from __future__ import annotations
import asyncio, logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from typing import Any
import httpx
from market_data.models import Candle

log=logging.getLogger(__name__)
BASE="https://api.upstox.com"
class UpstoxREST:
    def __init__(self, token: str, timeout: float=15.0):
        self.token=token.strip(); self.timeout=timeout
        self.client=httpx.AsyncClient(timeout=timeout, headers={"Authorization":f"Bearer {self.token}","Accept":"application/json","Content-Type":"application/json"})
    async def close(self): await self.client.aclose()
    async def _get(self,path: str,params: dict|None=None)->dict[str,Any]:
        if not self.token: raise RuntimeError("UPSTOX_ACCESS_TOKEN is empty")
        r=await self.client.get(BASE+path,params=params); r.raise_for_status(); data=r.json()
        if data.get("status") not in (None,"success"): raise RuntimeError(f"Upstox API returned {data.get('status')}")
        return data
    async def historical_candles(self,key: str, interval: int=5, days: int=7, end: date|None=None)->list[Candle]:
        end=end or __import__("datetime").datetime.now(ZoneInfo("Asia/Kolkata")).date(); start=end-timedelta(days=days)
        # V3 permits minute intervals 1..300; date range for <=15m is limited to one month.
        safe=key.replace("|","%7C").replace(" ","%20")
        path=f"/v3/historical-candle/{safe}/minutes/{interval}/{end.isoformat()}/{start.isoformat()}"
        data=await self._get(path); out=[]
        for row in data.get("data",{}).get("candles",[]):
            from datetime import datetime
            ts=datetime.fromisoformat(row[0])
            out.append(Candle(ts,float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5] or 0),float(row[6] or 0) if len(row)>6 else 0))
        return sorted(out,key=lambda c:c.ts)
    async def intraday_candles(self,key: str, interval: int=1)->list[Candle]:
        safe=key.replace('|','%7C').replace(' ','%20')
        data=await self._get(f"/v3/historical-candle/intraday/{safe}/minutes/{interval}"); out=[]
        for row in data.get("data",{}).get("candles",[]):
            from datetime import datetime
            out.append(Candle(datetime.fromisoformat(row[0]),float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5] or 0),float(row[6] or 0) if len(row)>6 else 0))
        return sorted(out,key=lambda c:c.ts)
    async def ltp_quote(self, key: str) -> float | None:
        """Return one instrument LTP from the Upstox V3 market-quote endpoint."""
        data = await self._get("/v3/market-quote/ltp", {"instrument_key": key})
        for quote in (data.get("data") or {}).values():
            if quote.get("instrument_token") == key and quote.get("last_price") is not None:
                return float(quote["last_price"])
        return None

    async def option_chain(self,key: str, expiry: str="current_week")->list[dict[str,Any]]:
        data=await self._get("/v2/option/chain",{"instrument_key":key,"expiry_date":expiry})
        return data.get("data",[]) or []
    async def instrument_list(self)->list[dict[str,Any]]:
        # Upstox instrument master is a downloadable JSON/CSV asset and can change format.
        # Keep instrument resolution in a separate resolver; never fabricate keys.
        r=await self.client.get("https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz")
        r.raise_for_status()
        import gzip, json
        raw=gzip.decompress(r.content) if r.content[:2]==b'\x1f\x8b' else r.content
        parsed=json.loads(raw)
        return parsed if isinstance(parsed,list) else parsed.get("data",[])
