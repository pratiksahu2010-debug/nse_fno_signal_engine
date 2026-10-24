"""Option-chain analytics. Missing data is represented as unavailable, never fabricated."""
from __future__ import annotations
from dataclasses import dataclass
from math import log, sqrt
from typing import Any
@dataclass(slots=True)
class OptionAssessment:
    available: bool
    adjustment: int=0
    pcr: float|None=None
    call_wall: float|None=None
    put_wall: float|None=None
    max_pain: float|None=None
    reason: str="unavailable"

def assess_chain(rows: list[dict[str,Any]], direction: str)->OptionAssessment:
    if not rows:return OptionAssessment(False,0,reason="empty_option_chain")
    call_oi={}; put_oi={}; pcr_num=pcr_den=0.0
    for r in rows:
        try:
            strike=float(r["strike_price"]); co=float((r.get("call_options") or {}).get("market_data",{}).get("oi",0) or 0); po=float((r.get("put_options") or {}).get("market_data",{}).get("oi",0) or 0)
        except (TypeError,ValueError,KeyError):continue
        call_oi[strike]=co; put_oi[strike]=po; pcr_num+=po; pcr_den+=co
    if not call_oi and not put_oi:return OptionAssessment(False,0,reason="no_valid_oi")
    pcr=pcr_num/pcr_den if pcr_den else None
    cw=max(call_oi,key=call_oi.get) if call_oi else None; pw=max(put_oi,key=put_oi.get) if put_oi else None
    # Simple max pain estimate from listed strikes and OI; not an expiry forecast.
    strikes=sorted(set(call_oi)|set(put_oi)); pains=[]
    for settle in strikes:
        pain=sum(oi*max(0,settle-k) for k,oi in call_oi.items())+sum(oi*max(0,k-settle) for k,oi in put_oi.items()); pains.append((pain,settle))
    mp=min(pains)[1] if pains else None
    adj=0
    if pcr is not None:
        if direction=="LONG": adj=4 if 0.8<=pcr<=1.5 else -4 if pcr<0.55 or pcr>2.5 else 0
        else: adj=4 if 0.55<=pcr<=1.2 else -4 if pcr<0.35 or pcr>2.0 else 0
    return OptionAssessment(True,adj,pcr,cw,pw,mp,"computed_from_chain")

def option_liquidity_ok(option: dict[str,Any], min_oi=100000, min_volume=10000, max_spread_pct=0.08)->tuple[bool,str]:
    md=option.get("market_data",{}) or {}; ltp=float(md.get("ltp") or 0); bid=float(md.get("bid_price") or 0); ask=float(md.get("ask_price") or 0)
    oi=float(md.get("oi") or 0); vol=float(md.get("volume") or 0)
    if ltp<=0:return False,"missing_ltp"
    if oi<min_oi:return False,"low_oi"
    if vol<min_volume:return False,"low_volume"
    if bid<=0 or ask<=0 or ask<bid:return False,"missing_or_crossed_market"
    if (ask-bid)/ltp>max_spread_pct:return False,"wide_spread"
    return True,"ok"


def select_option_plan(
    rows: list[dict[str, Any]],
    direction: str,
    instrument_rows: list[dict[str, Any]],
    entry: float,
    stop: float,
    target1: float,
    target2: float,
) -> dict[str, Any]:
    """Select a quoted, liquid CE/PE and estimate premium levels with delta-only approximation.

    This is a first-order estimate, not an options-pricing model. It deliberately
    returns an empty dict if the chain cannot support a defensible contract choice.
    """
    side = "call_options" if direction == "LONG" else "put_options"
    masters = {
        str(r.get("instrument_key", r.get("instrumentKey", ""))): r
        for r in instrument_rows
        if r.get("instrument_key", r.get("instrumentKey"))
    }
    candidates = []
    for row in rows or []:
        opt = row.get(side) or {}
        md = opt.get("market_data") or {}
        greeks = opt.get("option_greeks") or {}
        key = str(opt.get("instrument_key") or opt.get("instrumentKey") or "")
        master = masters.get(key, {})
        try:
            ltp = float(md.get("ltp") or 0)
            bid = float(md.get("bid_price") or 0)
            ask = float(md.get("ask_price") or 0)
            oi = float(md.get("oi") or 0)
            volume = float(md.get("volume") or 0)
            delta = abs(float(greeks.get("delta")))
            strike = float(row.get("strike_price"))
            lot_size = int(master.get("lot_size") or opt.get("lot_size") or row.get("lot_size") or 0)
        except (TypeError, ValueError):
            continue
        if not key or ltp <= 0 or bid <= 0 or ask < bid or ask <= 0 or oi < 1000 or volume < lot_size * 100 or lot_size <= 0:
            continue
        spread_pct = ((ask - bid) / ltp) * 100.0
        underlying_key = str(master.get("underlying_key") or "")
        max_spread_pct = 1.5 if underlying_key.startswith("NSE_INDEX|") else 3.0
        if spread_pct > max_spread_pct or not 0.45 <= delta <= 0.60:
            continue
        # Prefer delta near 0.52 and tighter spreads; tie-break in favour of more OI.
        candidates.append((abs(delta - 0.52) + spread_pct / 100.0, -oi, row, opt, md, greeks, master, key, ltp, bid, ask, oi, volume, delta, strike, lot_size, spread_pct))
    if not candidates:
        return {}
    item = min(candidates, key=lambda x: (x[0], x[1]))
    _, _, row, opt, md, greeks, master, key, ltp, bid, ask, oi, volume, delta, strike, lot_size, spread_pct = item
    premium_entry = ask
    premium_stop = max(0.05, premium_entry - delta * abs(entry - stop))
    premium_t1 = premium_entry + delta * abs(target1 - entry)
    premium_t2 = premium_entry + delta * abs(target2 - entry)
    risk_per_unit = max(0.0, premium_entry - premium_stop)
    return {
        "instrument_key": key,
        "trading_symbol": master.get("trading_symbol") or master.get("tradingsymbol") or opt.get("trading_symbol") or key,
        "expiry": row.get("expiry") or row.get("expiry_date") or master.get("expiry") or "N/A",
        "strike": strike,
        "lot_size": lot_size,
        "ltp": ltp,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "oi": oi,
        "volume": volume,
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "theta": greeks.get("theta"),
        "vega": greeks.get("vega"),
        "iv": greeks.get("iv"),
        "estimated_cost_per_lot": ask * lot_size,
        "premium_entry_low": bid,
        "premium_entry_high": ask,
        "premium_stop": premium_stop,
        "premium_t1": premium_t1,
        "premium_t2": premium_t2,
        "risk_per_lot": risk_per_unit * lot_size,
        "premium_rr1": (premium_t1 - premium_entry) / risk_per_unit if risk_per_unit > 0 else None,
        "premium_rr2": (premium_t2 - premium_entry) / risk_per_unit if risk_per_unit > 0 else None,
        "premium_estimate_method": "delta-only; excludes gamma, IV and theta changes",
    }
