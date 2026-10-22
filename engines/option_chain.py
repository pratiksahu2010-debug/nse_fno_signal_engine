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
