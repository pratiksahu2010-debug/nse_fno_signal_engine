"""Closed-candle scan coordinator. REST historical polling is the safe fallback transport."""
from __future__ import annotations
import asyncio, logging
import pandas as pd
from datetime import datetime, timezone, time
from engines.indicators import add_indicators
from engines.scoring import score_core,score_explosion
from engines.candidates import make_candidate,on_closed_candle
from engines.option_chain import assess_chain
from utils.time_utils import now_ist
log=logging.getLogger(__name__)
class SignalEngine:
    def __init__(self,settings,rest,resolver,telegram,calendar):
        self.settings=settings;self.rest=rest;self.resolver=resolver;self.telegram=telegram;self.calendar=calendar
        self.keys={};self.explosion_keys={};self.candles={};self.last_signal_bar={};self.last_signal_time={};self.candidates={};self.signals=[];self.last_scan=None;self.last_scan_started=None;self.last_scan_completed=None;self.scan_in_progress=False;self.symbols_attempted=0;self.symbols_failed=0;self.last_data_fetch=None;self.data_requests=0;self.data_request_failures=0;self.last_error=None;self.paused=False;self.ws_connected=False;self.last_tick=None;self.rejections={}
    async def initialize(self):
        self.keys=await self.resolver.resolve_many()
        try:
            import json
            from pathlib import Path
            override=json.loads(Path("config/explosion_universe.json").read_text())
            if isinstance(override,list) and override:
                self.explosion_keys=await self.resolver.resolve_many(override)
        except Exception as exc: log.warning("Explosion override not loaded: %s",exc)
        if not self.keys:log.warning("No symbols resolved; configure/verify instrument master")
        log.info("Resolved CORE=%d EXPLOSION=%d",len(self.keys),len(self.explosion_keys))
    async def scan_symbol(self,symbol,key,engine="CORE"):
        self.data_requests += 1
        try:
            candles = await self.rest.historical_candles(key, 5, days=7)
            self.last_data_fetch = now_ist().isoformat()
        except Exception as exc:
            self.data_request_failures += 1
            self.symbols_failed += 1
            self.last_error = f"{symbol}: {type(exc).__name__}: {exc}"
            log.warning("history failed %s: %s", symbol, exc)
            return None
        # Ignore still-forming 5-minute candle; use the timestamp's start plus 5m and 2s grace.
        now=now_ist(); closed=[]
        for c in candles:
            ts=c.ts.astimezone(now.tzinfo) if c.ts.tzinfo else c.ts.replace(tzinfo=now.tzinfo)
            if (now-ts).total_seconds()>=302: c.ts=ts;closed.append(c)
        if len(closed)<35:return None
        d=add_indicators(closed);last=d.iloc[-1];bar=last.ts
        # Advance existing candidates exactly once per newly closed candle before evaluating new setups.
        for candidate in list(self.candidates.values()):
            if candidate.symbol==symbol and candidate.engine==engine and candidate.signal_time < bar:
                transition=on_closed_candle(candidate,closed[-1])
                if transition in {"ENTERED","TARGET1","TARGET2","STOPPED","EXPIRED","CANCELLED"}:
                    await self.telegram.send(f"{candidate.engine} {candidate.symbol}: {transition}\nStatus: {candidate.status}\nSL {candidate.stop:.2f} | T1 {candidate.t1:.2f} | T2 {candidate.t2:.2f}\n{candidate.exit_reason or ''}")
        # Apply independent configured time windows; no signals near the open/close edges.
        from config.defaults import CORE_WINDOW_START, CORE_WINDOW_END, EXPLOSION_WINDOW_START, EXPLOSION_WINDOW_END
        local_bar=last.ts.astimezone(now.tzinfo) if last.ts.tzinfo else last.ts.replace(tzinfo=now.tzinfo)
        clock=local_bar.time().replace(tzinfo=None)
        if engine=="CORE" and not (CORE_WINDOW_START<=clock<=CORE_WINDOW_END): return None
        if engine=="EXPLOSION" and not (EXPLOSION_WINDOW_START<=clock<=EXPLOSION_WINDOW_END): return None
        k=(symbol,engine)
        if self.last_signal_bar.get(k)==str(bar):return None
        if engine=="CORE":
            # Require directionally aligned last CLOSED 15-minute bar; current partial 15m is excluded.
            d15=d.set_index("ts").resample("15min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
            d15=d15[d15.ts + pd.Timedelta(minutes=15) <= pd.Timestamp(now - __import__("datetime").timedelta(seconds=2))]
            # Strict profile fails closed when higher-timeframe confirmation is not ready.
            if len(d15) < 22:
                self.rejections["15m_confirmation_missing"] = self.rejections.get("15m_confirmation_missing", 0) + 1
                return None
            d15["ema9"]=d15.close.ewm(span=9,adjust=False).mean();d15["ema21"]=d15.close.ewm(span=21,adjust=False).mean()
            confirm=d15.iloc[-1]
            long_htf = confirm.close > confirm.ema21 and confirm.ema9 > confirm.ema21
            short_htf = confirm.close < confirm.ema21 and confirm.ema9 < confirm.ema21
            long_ltf = last.close > last.ema21 and last.ema9 > last.ema21
            short_ltf = last.close < last.ema21 and last.ema9 < last.ema21
            if not ((long_ltf and long_htf) or (short_ltf and short_htf)):
                self.rejections["15m_confirmation_failed"] = self.rejections.get("15m_confirmation_failed", 0) + 1
                return None
            oc_adj=0;oc_avail=False
            # Option chain is queried only for technical candidates; data unavailable never fabricates an adjustment.
            prelim=score_core(d,60,0,True,profile=getattr(self.settings, "filter_profile", "strict"))
            if prelim.score>=60 and prelim.direction:
                underlying=key
                try:
                    chain=await self.rest.option_chain(underlying,"current_week"); oc=assess_chain(chain,prelim.direction);oc_adj=oc.adjustment;oc_avail=oc.available
                except Exception as exc:log.info("option chain unavailable %s: %s",symbol,exc)
            result=score_core(d,self.settings.min_score,oc_adj,oc_avail,profile=getattr(self.settings, "filter_profile", "strict"))
        else: result=score_explosion(d,self.settings.explosion_min_score,profile=getattr(self.settings, "filter_profile", "strict"))
        for reject in result.rejects:self.rejections[reject]=self.rejections.get(reject,0)+1
        if not result.direction:return None
        # Never overwrite a live candidate, even when a later setup appears on the same symbol.
        candidate_key = symbol + ":" + engine
        existing = self.candidates.get(candidate_key)
        if existing and existing.status in {"PENDING", "ACTIVE"}:
            self.rejections["existing_candidate_open"] = self.rejections.get("existing_candidate_open", 0) + 1
            return None
        # Cooldown is per symbol+engine and uses the timestamp of the closed signal candle.
        cooldown = 20 if engine == "EXPLOSION" else 30
        previous_signal = self.last_signal_time.get((symbol, engine))
        if previous_signal is not None and (bar - previous_signal).total_seconds() < cooldown * 60:
            self.rejections["symbol_cooldown"] = self.rejections.get("symbol_cooldown", 0) + 1
            return None
        candle=closed[-1]
        candidate=make_candidate(symbol,result.direction,engine,result.setup or engine,result.score,candle,float(last.atr14))
        self.candidates[candidate_key]=candidate
        self.last_signal_time[(symbol, engine)] = bar
        self.last_signal_bar[k]=str(bar);self.signals.append({"symbol":symbol,"engine":engine,"score":result.score,"direction":result.direction,"setup":result.setup,"time":str(bar),"metrics":result.metrics,"rejects":result.rejects})
        await self.telegram.send(self.format_signal(candidate,result))
        return result
    @staticmethod
    def format_signal(c,r):
        return (f"{c.engine} {c.direction} | {c.symbol}\nSetup: {c.setup} | Score: {c.score}/100\n"
                f"Signal candle close: {c.signal_close:.2f}\nEntry zone (next 5m only): {c.entry_low:.2f} - {c.entry_high:.2f}\n"
                f"SL: {c.stop:.2f} | T1: {c.t1:.2f} | T2: {c.t2:.2f}\n"
                f"Closed-candle signal; not an order. Confirm option liquidity/spread and position size before trading.\n"
                f"Reasons: {', '.join(r.reasons) or '—'}\nReject gates: {', '.join(r.rejects) or 'none'}")
    async def scan(self,limit=None):
        if self.paused or self.telegram.paused:return {"status":"paused","scanned":0,"signals":0}
        if not self.calendar.is_market_open():return {"status":"market_closed","scanned":0,"signals":0}
        if not self.keys:await self.initialize()
        start = len(self.signals)
        scanned = 0
        self.last_scan_started = now_ist().isoformat()
        self.scan_in_progress = True
        self.symbols_attempted = 0
        self.symbols_failed = 0
        try:
            for sym, key in list(self.keys.items())[:limit]:
                self.symbols_attempted += 1
                await self.scan_symbol(sym, key, "CORE")
                scanned += 1
                await asyncio.sleep(0.08)
            # EXPLOSION is independent and runs only for the configured curated universe.
            for sym, key in list(self.explosion_keys.items())[:limit]:
                self.symbols_attempted += 1
                await self.scan_symbol(sym, key, "EXPLOSION")
                scanned += 1
                await asyncio.sleep(0.08)
        finally:
            self.scan_in_progress = False
            self.last_scan_completed = now_ist().isoformat()
            self.last_scan = self.last_scan_completed
        return {
            "status": "ok",
            "scanned": scanned,
            "signals": len(self.signals) - start,
            "last_scan_started": self.last_scan_started,
            "last_scan_completed": self.last_scan_completed,
            "data_requests": self.data_requests,
            "data_request_failures": self.data_request_failures,
            "symbols_failed": self.symbols_failed,
        }
    async def run_loop(self):
        while True:
            try:
                now=now_ist()
                if self.calendar.is_market_open(): await self.scan()
                await asyncio.sleep(max(5,300-(now.minute%5)*60-now.second))
            except asyncio.CancelledError:raise
            except Exception as exc:self.last_error=str(exc);log.exception("scan loop error");await asyncio.sleep(10)
    def status(self):
        return {
            "service": "nse-fno-signal-engine",
            "market_open": self.calendar.is_market_open(),
            "market_data_transport": "rest_closed_candle_polling",
            "websocket_enabled": False,
            "ws_connected": False,
            "websocket_note": "WebSocket is not implemented/enabled; false is intentional.",
            "rest_polling_configured": bool(getattr(self.rest, "token", "")),
            "data_requests": self.data_requests,
            "data_request_failures": self.data_request_failures,
            "last_data_fetch": self.last_data_fetch,
            "symbols_resolved": len(self.keys),
            "explosion_symbols_resolved": len(self.explosion_keys),
            "signals_today": len(self.signals),
            "pending_candidates": sum(c.status == "PENDING" for c in self.candidates.values()),
            "active_candidates": sum(c.status == "ACTIVE" for c in self.candidates.values()),
            "scan_in_progress": self.scan_in_progress,
            "last_scan_started": self.last_scan_started,
            "last_scan_completed": self.last_scan_completed,
            "last_scan": self.last_scan,
            "symbols_attempted": self.symbols_attempted,
            "symbols_failed": self.symbols_failed,
            "last_error": self.last_error,
            "last_tick": str(self.last_tick) if self.last_tick else None,
            "paused": self.paused or self.telegram.paused,
            "filter_profile": getattr(self.settings, "filter_profile", "strict"),
            "reject_reasons": self.rejections,
            "signal_only": True,
        }
