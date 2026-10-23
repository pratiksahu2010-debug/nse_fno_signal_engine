"""Closed-candle scan coordinator. REST historical polling is the safe fallback transport."""
from __future__ import annotations
import asyncio, logging, time as monotonic_time
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
        self.scan_concurrency=max(1,min(8,int(getattr(settings,"scan_concurrency",4))))
        self.historical_cache_ttl_sec=max(60,int(getattr(settings,"historical_cache_ttl_sec",1800)))
        self.historical_cache={};self.last_scan_duration_seconds=None
        self.keys={};self.explosion_keys={};self.candles={};self.last_signal_bar={};self.last_signal_time={};self.candidates={};self.signals=[];self.last_scan=None;self.last_scan_started=None;self.last_scan_completed=None;self.scan_in_progress=False;self.symbols_attempted=0;self.symbols_failed=0;self.last_data_fetch=None;self.data_requests=0;self.data_request_failures=0;self.last_error=None;self.paused=False;self.ws_connected=False;self.last_tick=None;self.rejections={};self.stage_counts={};self.last_symbol_diagnostics={};self.scan_lock=asyncio.Lock()
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
        diag_key=f"{symbol}:{engine}"
        diag={"symbol":symbol,"engine":engine,"stage":"fetching","candles_returned":0,"closed_candles":0,"latest_closed_candle":None,"latest_candle_age_seconds":None,"reason":None}
        self.last_symbol_diagnostics[diag_key]=diag
        try:
            # Historical warm-up data changes slowly; cache it between scans to reduce
            # REST traffic. Intraday data is always fetched fresh and takes precedence
            # for duplicate candle timestamps. A short TTL also bounds stale history.
            cached = self.historical_cache.get(key)
            if cached and monotonic_time.monotonic() - cached[0] < self.historical_cache_ttl_sec:
                historical = cached[1]
                diag["historical_cache_hit"] = True
            else:
                self.data_requests += 1
                historical = await self.rest.historical_candles(key, 5, days=7)
                self.historical_cache[key] = (monotonic_time.monotonic(), historical)
                diag["historical_cache_hit"] = False
            self.data_requests += 1
            intraday = await self.rest.intraday_candles(key, 5)
            self.last_data_fetch = now_ist().isoformat()
            now = now_ist()
            merged = {}
            for candle in historical + intraday:
                ts = candle.ts.astimezone(now.tzinfo) if candle.ts.tzinfo else candle.ts.replace(tzinfo=now.tzinfo)
                candle.ts = ts
                merged[ts] = candle
            candles = [merged[ts] for ts in sorted(merged)]
            today = now.date()
            diag["historical_candles_returned"] = len(historical)
            diag["intraday_candles_returned"] = len(intraday)
            diag["current_session_candles"] = sum(1 for c in intraday if (c.ts.astimezone(now.tzinfo) if c.ts.tzinfo else c.ts.replace(tzinfo=now.tzinfo)).date() == today)
            diag["candles_returned"] = len(candles)
            diag["stage"] = "history_and_intraday_fetched"
            self.stage_counts["history_and_intraday_fetched"] = self.stage_counts.get("history_and_intraday_fetched", 0) + 1
        except Exception as exc:
            self.data_request_failures += 1
            self.symbols_failed += 1
            self.last_error = f"{symbol}: {type(exc).__name__}: {exc}"
            diag["stage"] = "market_data_fetch_failed"; diag["reason"] = type(exc).__name__
            self.stage_counts["market_data_fetch_failed"] = self.stage_counts.get("market_data_fetch_failed", 0) + 1
            log.warning("market data failed %s: %s", symbol, exc)
            return None
        # Ignore still-forming 5-minute candles; timestamps represent candle starts.
        now = now_ist()
        closed = []
        for c in candles:
            ts = c.ts.astimezone(now.tzinfo) if c.ts.tzinfo else c.ts.replace(tzinfo=now.tzinfo)
            if (now - ts).total_seconds() >= 302:
                c.ts = ts
                closed.append(c)
        diag["closed_candles"]=len(closed)
        if closed:
            newest=closed[-1].ts
            diag["latest_closed_candle"]=newest.isoformat()
            diag["latest_candle_age_seconds"]=round((now-newest).total_seconds(),2)
        # Fail closed when the newest completed candle is too old during an open
        # session. A successful API response is not proof that its data is fresh.
        if closed and (now - closed[-1].ts).total_seconds() > 12 * 60:
            diag["stage"] = "stale_market_data"; diag["reason"] = "latest_closed_candle_older_than_12_minutes"
            self.stage_counts["stale_market_data"] = self.stage_counts.get("stale_market_data", 0) + 1
            self.rejections["stale_market_data"] = self.rejections.get("stale_market_data", 0) + 1
            return None
        if len(closed)<35:
            diag["stage"]="insufficient_closed_candles";diag["reason"]="insufficient_closed_candles"
            self.stage_counts["insufficient_closed_candles"]=self.stage_counts.get("insufficient_closed_candles",0)+1
            self.rejections["insufficient_closed_candles"]=self.rejections.get("insufficient_closed_candles",0)+1
            return None
        d=add_indicators(closed);last=d.iloc[-1];bar=last.ts
        diag["stage"]="indicators_ready"
        self.stage_counts["indicators_ready"]=self.stage_counts.get("indicators_ready",0)+1
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
        if engine=="CORE" and not (CORE_WINDOW_START<=clock<=CORE_WINDOW_END):
            diag["stage"]="outside_core_window";diag["reason"]="outside_core_window"
            self.stage_counts["outside_core_window"]=self.stage_counts.get("outside_core_window",0)+1
            self.rejections["outside_core_window"]=self.rejections.get("outside_core_window",0)+1
            return None
        if engine=="EXPLOSION" and not (EXPLOSION_WINDOW_START<=clock<=EXPLOSION_WINDOW_END):
            diag["stage"]="outside_explosion_window";diag["reason"]="outside_explosion_window"
            self.stage_counts["outside_explosion_window"]=self.stage_counts.get("outside_explosion_window",0)+1
            self.rejections["outside_explosion_window"]=self.rejections.get("outside_explosion_window",0)+1
            return None
        diag["stage"]="inside_time_window"
        self.stage_counts["inside_time_window"]=self.stage_counts.get("inside_time_window",0)+1
        k=(symbol,engine)
        if self.last_signal_bar.get(k)==str(bar):
            diag["stage"]="duplicate_bar";diag["reason"]="duplicate_bar"
            self.stage_counts["duplicate_bar"]=self.stage_counts.get("duplicate_bar",0)+1
            self.rejections["duplicate_bar"]=self.rejections.get("duplicate_bar",0)+1
            return None
        if engine=="CORE":
            # Require directionally aligned last CLOSED 15-minute bar; current partial 15m is excluded.
            d15=d.set_index("ts").resample("15min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
            d15=d15[d15.ts + pd.Timedelta(minutes=15) <= pd.Timestamp(now - __import__("datetime").timedelta(seconds=2))]
            # Strict profile fails closed when higher-timeframe confirmation is not ready.
            if len(d15) < 22:
                diag["stage"]="15m_confirmation_missing";diag["reason"]="15m_confirmation_missing"
                self.stage_counts["15m_confirmation_missing"]=self.stage_counts.get("15m_confirmation_missing",0)+1
                self.rejections["15m_confirmation_missing"] = self.rejections.get("15m_confirmation_missing", 0) + 1
                return None
            d15["ema9"]=d15.close.ewm(span=9,adjust=False).mean();d15["ema21"]=d15.close.ewm(span=21,adjust=False).mean()
            confirm=d15.iloc[-1]
            long_htf = confirm.close > confirm.ema21 and confirm.ema9 > confirm.ema21
            short_htf = confirm.close < confirm.ema21 and confirm.ema9 < confirm.ema21
            long_ltf = last.close > last.ema21 and last.ema9 > last.ema21
            short_ltf = last.close < last.ema21 and last.ema9 < last.ema21
            if not ((long_ltf and long_htf) or (short_ltf and short_htf)):
                diag["stage"]="15m_confirmation_failed";diag["reason"]="15m_confirmation_failed"
                self.stage_counts["15m_confirmation_failed"]=self.stage_counts.get("15m_confirmation_failed",0)+1
                self.rejections["15m_confirmation_failed"] = self.rejections.get("15m_confirmation_failed", 0) + 1
                return None
            oc_adj=0;oc_avail=False
            # Option chain is queried only for technical candidates; data unavailable never fabricates an adjustment.
            prelim=score_core(d,60,0,True,profile=getattr(self.settings, "filter_profile", "strict"))
            if prelim.score>=60 and prelim.direction:
                underlying=key
                try:
                    self.data_requests += 1
                    chain=await self.rest.option_chain(underlying,"current_week"); oc=assess_chain(chain,prelim.direction);oc_adj=oc.adjustment;oc_avail=oc.available
                except Exception as exc:log.info("option chain unavailable %s: %s",symbol,exc)
            result=score_core(d,self.settings.min_score,oc_adj,oc_avail,profile=getattr(self.settings, "filter_profile", "strict"))
            self.stage_counts["core_scoring_reached"]=self.stage_counts.get("core_scoring_reached",0)+1
        else:
            result=score_explosion(d,self.settings.explosion_min_score,profile=getattr(self.settings, "filter_profile", "strict"))
            self.stage_counts["explosion_scoring_reached"]=self.stage_counts.get("explosion_scoring_reached",0)+1
        diag["score"] = result.score
        diag["score_reasons"] = list(result.reasons)
        diag["score_metrics"] = result.metrics
        diag["score_rejects"] = list(result.rejects)
        log.info(
            "score_decision engine=%s symbol=%s candle=%s score=%s direction=%s setup=%s components=%s hard_gates=%s rejects=%s",
            engine, symbol, bar, result.score, result.direction, result.setup,
            result.metrics.get("score_components", {}),
            result.metrics.get("hard_gates", {}), result.rejects,
        )
        for reject in result.rejects:self.rejections[reject]=self.rejections.get(reject,0)+1
        if not result.direction:
            diag["stage"]="score_rejected";diag["reason"]=",".join(result.rejects) or "no_direction"
            self.stage_counts["score_rejected"]=self.stage_counts.get("score_rejected",0)+1
            return None
        diag["stage"]="score_qualified"
        self.stage_counts["score_qualified"]=self.stage_counts.get("score_qualified",0)+1
        # Never overwrite a live candidate, even when a later setup appears on the same symbol.
        candidate_key = symbol + ":" + engine
        existing = self.candidates.get(candidate_key)
        if existing and existing.status in {"PENDING", "ACTIVE"}:
            diag["stage"]="existing_candidate_open";diag["reason"]="existing_candidate_open"
            self.stage_counts["existing_candidate_open"]=self.stage_counts.get("existing_candidate_open",0)+1
            self.rejections["existing_candidate_open"] = self.rejections.get("existing_candidate_open", 0) + 1
            return None
        # Cooldown is per symbol+engine and uses the timestamp of the closed signal candle.
        cooldown = 20 if engine == "EXPLOSION" else 30
        previous_signal = self.last_signal_time.get((symbol, engine))
        if previous_signal is not None and (bar - previous_signal).total_seconds() < cooldown * 60:
            diag["stage"]="symbol_cooldown";diag["reason"]="symbol_cooldown"
            self.stage_counts["symbol_cooldown"]=self.stage_counts.get("symbol_cooldown",0)+1
            self.rejections["symbol_cooldown"] = self.rejections.get("symbol_cooldown", 0) + 1
            return None
        candle=closed[-1]
        candidate=make_candidate(symbol,result.direction,engine,result.setup or engine,result.score,candle,float(last.atr14))
        self.candidates[candidate_key]=candidate
        diag["stage"]="signal_created";diag["reason"]=None
        self.stage_counts["signal_created"]=self.stage_counts.get("signal_created",0)+1
        self.last_signal_time[(symbol, engine)] = bar
        self.last_signal_bar[k]=str(bar);self.signals.append({"symbol":symbol,"engine":engine,"score":result.score,"direction":result.direction,"setup":result.setup,"time":str(bar),"metrics":result.metrics,"score_reasons":result.reasons,"score_components":result.metrics.get("score_components",{}),"hard_gates":result.metrics.get("hard_gates",{}),"rejects":result.rejects})
        await self.telegram.send(self.format_signal(candidate,result))
        return result
    @staticmethod
    def format_signal(c,r):
        return (f"{c.engine} {c.direction} | {c.symbol}\nSetup: {c.setup} | Score: {c.score}/100\n"
                f"Signal candle close: {c.signal_close:.2f}\nEntry zone (next 5m only): {c.entry_low:.2f} - {c.entry_high:.2f}\n"
                f"SL: {c.stop:.2f} | T1: {c.t1:.2f} | T2: {c.t2:.2f}\n"
                f"Closed-candle signal; not an order. Confirm option liquidity/spread and position size before trading.\n"
                f"Reasons: {', '.join(r.reasons) or '—'}\nReject gates: {', '.join(r.rejects) or 'none'}")
    async def _scan_one(self,symbol,key,engine):
        """Isolate per-symbol failures so one malformed response cannot abort a full scan."""
        try:
            await self.scan_symbol(symbol,key,engine)
        except Exception as exc:
            diag_key=f"{symbol}:{engine}"
            diag=self.last_symbol_diagnostics.setdefault(diag_key,{"symbol":symbol,"engine":engine})
            diag["stage"]="processing_error";diag["reason"]=type(exc).__name__
            self.stage_counts["processing_error"]=self.stage_counts.get("processing_error",0)+1
            self.last_error=f"{symbol} ({engine}): {type(exc).__name__}: {exc}"
            log.exception("symbol processing failed %s %s",engine,symbol)

    async def scan(self,limit=None):
        if self.paused or self.telegram.paused:return {"status":"paused","scanned":0,"signals":0}
        if not self.calendar.is_market_open():return {"status":"market_closed","scanned":0,"signals":0}
        if not self.keys:await self.initialize()
        start = len(self.signals)
        scanned = 0
        if self.scan_lock.locked():
            return {"status":"scan_already_in_progress","scanned":0,"signals":0}
        await self.scan_lock.acquire()
        self.stage_counts={}
        self.last_symbol_diagnostics={}
        self.last_error=None
        self.last_scan_started = now_ist().isoformat()
        scan_started_monotonic = monotonic_time.monotonic()
        self.scan_in_progress = True
        self.symbols_attempted = 0
        self.symbols_failed = 0
        try:
            # Bounded concurrency reduces serial scan latency without launching an
            # unbounded burst against Upstox. Each symbol still uses closed candles.
            jobs = [(sym, key, "CORE") for sym, key in list(self.keys.items())[:limit]]
            jobs += [(sym, key, "EXPLOSION") for sym, key in list(self.explosion_keys.items())[:limit]]
            self.symbols_attempted = len(jobs)
            semaphore = asyncio.Semaphore(self.scan_concurrency)
            async def run_job(sym, key, kind):
                async with semaphore:
                    await self._scan_one(sym, key, kind)
            await asyncio.gather(*(run_job(sym, key, kind) for sym, key, kind in jobs))
            scanned = len(jobs)
        finally:
            self.last_scan_duration_seconds = round(monotonic_time.monotonic() - scan_started_monotonic, 2)
            self.scan_in_progress = False
            self.last_scan_completed = now_ist().isoformat()
            self.last_scan = self.last_scan_completed
            self.scan_lock.release()
        return {
            "status": "ok",
            "scanned": scanned,
            "signals": len(self.signals) - start,
            "last_scan_started": self.last_scan_started,
            "last_scan_completed": self.last_scan_completed,
            "data_requests": self.data_requests,
            "data_request_failures": self.data_request_failures,
            "symbols_failed": self.symbols_failed,
            "stage_counts": dict(self.stage_counts),
        }
    async def run_loop(self):
        while True:
            try:
                if self.calendar.is_market_open():
                    await self.scan()
                # Recalculate after scanning; using the pre-scan time delayed the next cycle
                # by the scan duration (about a minute for 144 sequential REST requests).
                now=now_ist()
                seconds_into_bucket=(now.minute%5)*60+now.second+now.microsecond/1_000_000
                delay=max(1.0,300.0-seconds_into_bucket)
                await asyncio.sleep(delay)
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
            "signals_today": sum(1 for s in self.signals if str(s.get("time","")).startswith(now_ist().date().isoformat())),
            "signals_in_process_memory": len(self.signals),
            "pending_candidates": sum(c.status == "PENDING" for c in self.candidates.values()),
            "active_candidates": sum(c.status == "ACTIVE" for c in self.candidates.values()),
            "scan_in_progress": self.scan_in_progress,
            "last_scan_started": self.last_scan_started,
            "last_scan_completed": self.last_scan_completed,
            "last_scan": self.last_scan,
            "last_scan_duration_seconds": self.last_scan_duration_seconds,
            "scan_concurrency": self.scan_concurrency,
            "historical_cache_entries": len(self.historical_cache),
            "symbols_attempted": self.symbols_attempted,
            "symbols_failed": self.symbols_failed,
            "last_error": self.last_error,
            "last_tick": str(self.last_tick) if self.last_tick else None,
            "paused": self.paused or self.telegram.paused,
            "filter_profile": getattr(self.settings, "filter_profile", "strict"),
            "reject_reasons": self.rejections,
            "stage_counts": self.stage_counts,
            "last_symbol_diagnostics": (
                [d for d in self.last_symbol_diagnostics.values() if d.get("engine")=="CORE"][-5:]
                + [d for d in self.last_symbol_diagnostics.values() if d.get("engine")=="EXPLOSION"][-5:]
            ),
            "signal_only": True,
        }
