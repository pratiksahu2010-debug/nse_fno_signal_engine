"""Candidate lifecycle, entry windows, risk levels and closed-candle exit tracking."""
from __future__ import annotations
from dataclasses import dataclass,field,asdict
from datetime import datetime
from typing import Any
@dataclass(slots=True)
class Candidate:
    symbol:str; direction:str; engine:str; setup:str; score:int; signal_time:datetime
    signal_close:float; signal_high:float; signal_low:float; atr:float; entry_low:float; entry_high:float
    stop:float; t1:float; t2:float; ttl_bars:int=12; status:str="PENDING"; bars_seen:int=0
    entry_price:float|None=None; t1_hit:bool=False; t2_hit:bool=False; exit_price:float|None=None; exit_reason:str|None=None
    notes:list[str]=field(default_factory=list)
    def as_dict(self):return asdict(self)

def make_candidate(symbol, direction, engine, setup, score, candle, atr, ttl_bars=None):
    close=float(candle.close); high=float(candle.high); low=float(candle.low); a=float(atr)
    if a<=0:raise ValueError("ATR must be positive")
    zone_low=close if direction=="LONG" else close-0.25*a
    zone_high=close+0.25*a if direction=="LONG" else close
    if engine.upper()=="EXPLOSION":
        stop=max(low,close-1.5*a) if direction=="LONG" else min(high,close+1.5*a)
        min_r=0.8*a
        if direction=="LONG" and close-stop<min_r:stop=close-min_r
        if direction=="SHORT" and stop-close<min_r:stop=close+min_r
        ttl=ttl_bars or 3
        target_multiple=3.0
    else:
        swing_low=float(candle.swing_low) if hasattr(candle,"swing_low") else low
        swing_high=float(candle.swing_high) if hasattr(candle,"swing_high") else high
        stop=max(close-1.5*a,swing_low-0.1*a) if direction=="LONG" else min(close+1.5*a,swing_high+0.1*a)
        ttl=ttl_bars or 12
        target_multiple=2.5
    # Targets are calculated from the worst allowed entry-zone edge, not the signal close.
    # This prevents the advertised reward:risk from being overstated for a late zone fill.
    planned_entry = zone_high if direction == "LONG" else zone_low
    r=abs(planned_entry-stop)
    if r <= 0:
        raise ValueError("Entry-to-stop risk must be positive")
    t1=planned_entry+(1.5*r if direction=="LONG" else -1.5*r)
    t2=planned_entry+(target_multiple*r if direction=="LONG" else -target_multiple*r)
    return Candidate(symbol,direction,engine.upper(),setup,int(score),candle.ts,close,high,low,a,zone_low,zone_high,stop,t1,t2,ttl)

def on_closed_candle(c:Candidate, candle:Any)->str|None:
    if c.status not in {"PENDING","ACTIVE"}:return None
    c.bars_seen+=1; close=float(candle.close); low=float(candle.low); high=float(candle.high)
    if c.status=="PENDING":
        if c.bars_seen>1: c.status="EXPIRED"; c.exit_reason="entry_window_expired"; return c.status
        if c.direction=="LONG" and close<c.signal_close-0.35*c.atr: c.status="CANCELLED";c.exit_reason="gap_or_chase";return c.status
        if c.direction=="SHORT" and close>c.signal_close+0.35*c.atr: c.status="CANCELLED";c.exit_reason="gap_or_chase";return c.status
        if (c.direction=="LONG" and close<c.signal_low+(c.signal_high-c.signal_low)/2) or (c.direction=="SHORT" and close>c.signal_low+(c.signal_high-c.signal_low)/2):c.status="CANCELLED";c.exit_reason="signal_midpoint_failed";return c.status
        # The close is a deterministic replay proxy; live mode can mark zone touch from ticks.
        if c.direction=="LONG" and c.entry_low<=close<=c.entry_high or c.direction=="SHORT" and c.entry_low<=close<=c.entry_high:
            c.status="ACTIVE";c.entry_price=close;return "ENTERED"
        c.status="EXPIRED";c.exit_reason="entry_zone_not_reached_on_close";return c.status
    if c.direction=="LONG":
        if close<=c.stop:c.status="STOPPED";c.exit_price=close;c.exit_reason="stop_close_confirmed";return c.status
        if close>=c.t2:c.t2_hit=True;c.status="TARGET2";c.exit_price=close;c.exit_reason="target2_close_confirmed";return c.status
        if close>=c.t1:c.t1_hit=True;return "TARGET1"
    else:
        if close>=c.stop:c.status="STOPPED";c.exit_price=close;c.exit_reason="stop_close_confirmed";return c.status
        if close<=c.t2:c.t2_hit=True;c.status="TARGET2";c.exit_price=close;c.exit_reason="target2_close_confirmed";return c.status
        if close<=c.t1:c.t1_hit=True;return "TARGET1"
    return None
