"""Strict, transparent scoring with independent hard rejection gates.

All decisions use the last CLOSED candle. Thresholds are deliberately configurable
through arguments/constants so replay can compare balanced and strict profiles.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any

from config import defaults


@dataclass(slots=True)
class Score:
    score: int
    direction: str | None
    setup: str | None
    reasons: list[str]
    rejects: list[str]
    metrics: dict[str, Any]

    def as_dict(self):
        return asdict(self)


def score_core(
    df,
    min_score: int = defaults.MIN_SCORE,
    option_adjustment: int = 0,
    option_available: bool = False,
    *,
    profile: str = "strict",
    context_adjustment: int = 0,
    context_label: str | None = None,
) -> Score:
    """Score CORE setups; strict mode fails closed on weak/late/uncorroborated bars."""
    profile = profile.lower().strip()
    if profile not in {"strict", "balanced"}:
        raise ValueError("profile must be 'strict' or 'balanced'")
    if len(df) < 35:
        return Score(0, None, None, [], ["insufficient_history"], {})

    r, p = df.iloc[-1], df.iloc[-2]
    rejects: list[str] = []
    reasons: list[str] = []
    required = ("atr14", "adx14", "rsi14", "ema9", "ema21", "vwap", "rvol", "plus_di", "minus_di", "body_ratio", "clv", "er10")
    if any(not _finite(r.get(k)) for k in required):
        return Score(0, None, None, [], ["indicator_warmup"], {})
    if not _finite(r.get("donchian_high20")) or not _finite(r.get("donchian_low20")):
        return Score(0, None, None, [], ["breakout_indicator_warmup"], {})

    close, atr = float(r.close), float(r.atr14)
    adx, rvol, rsi = float(r.adx14), float(r.rvol), float(r.rsi14)
    long_trend = close > float(r.ema21) and float(r.ema9) > float(r.ema21)
    short_trend = close < float(r.ema21) and float(r.ema9) < float(r.ema21)
    direction = "LONG" if long_trend else "SHORT" if short_trend else None
    if direction is None:
        rejects.append("no_ema_trend")

    # Hard quality gates. Independent evidence is required; score cannot override these.
    adx_floor = 22.0 if profile == "strict" else 20.0
    rvol_floor = 1.2 if profile == "strict" else 0.9
    body_floor = 0.50 if profile == "strict" else 0.35
    if adx < adx_floor:
        rejects.append("adx_below_minimum")
    prev_adx = float(p.adx14) if _finite(p.get("adx14")) else float("nan")
    if profile == "strict" and (not math.isfinite(prev_adx) or adx < prev_adx - 0.5):
        rejects.append("adx_not_rising")

    pdi, mdi = float(r.plus_di), float(r.minus_di)
    di_spread = abs(pdi - mdi)
    if direction == "LONG" and (pdi <= mdi or di_spread < 5.0):
        rejects.append("di_conflict")
    elif direction == "SHORT" and (mdi <= pdi or di_spread < 5.0):
        rejects.append("di_conflict")
    if rvol < rvol_floor:
        rejects.append("low_relative_volume")
    if float(r.body_ratio) < body_floor:
        rejects.append("weak_candle_body")
    if direction == "LONG" and float(r.clv) < (0.20 if profile == "balanced" else 0.35):
        rejects.append("weak_bullish_close_location")
    if direction == "SHORT" and float(r.clv) > (-0.20 if profile == "balanced" else -0.35):
        rejects.append("weak_bearish_close_location")

    # Don't chase a candle that is already materially stretched from its fast mean.
    ema9_extension = abs(close - float(r.ema9)) / atr if atr > 0 else float("inf")
    ema21_extension = abs(close - float(r.ema21)) / atr if atr > 0 else float("inf")
    max_ema9_extension = 1.50 if profile == "strict" else 2.0
    max_ema21_extension = 2.0 if profile == "strict" else 2.5
    if ema9_extension > max_ema9_extension:
        rejects.append("overextended_from_ema9")
    if ema21_extension > max_ema21_extension:
        rejects.append("overextended_from_ema21")

    if direction == "LONG" and not ((45 <= rsi <= 70) if profile == "strict" else (40 <= rsi <= 75)):
        rejects.append("rsi_long_out_of_range")
    if direction == "SHORT" and not ((30 <= rsi <= 55) if profile == "strict" else (25 <= rsi <= 60)):
        rejects.append("rsi_short_out_of_range")
    # Strict mode requires VWAP-side agreement. Balanced mode lets setup quality
    # and the VWAP score contribution decide, preserving valid pullbacks/reclaims.
    if profile == "strict":
        if direction == "LONG" and close <= float(r.vwap):
            rejects.append("below_vwap")
        if direction == "SHORT" and close >= float(r.vwap):
            rejects.append("above_vwap")

    # Give range breaks and genuine VWAP crosses precedence over a generic
    # EMA9 reclaim. Otherwise an overlapping breakout can be mislabeled as a
    # pullback and escape the breakout-specific volume/close-location gates.
    setup = None
    if direction == "LONG":
        if close > float(r.donchian_high20):
            setup = "A2_BREAKOUT"
        elif float(p.close) <= float(p.vwap) and close > float(r.vwap):
            setup = "A3_VWAP_RECLAIM"
        elif float(p.close) <= float(p.ema9) and close > float(r.ema9):
            setup = "A1_TREND_PULLBACK"
        elif int(r.step_state) == 1 and int(p.step_state) != 1:
            setup = "A5_STEP_FLIP"
    elif direction == "SHORT":
        if close < float(r.donchian_low20):
            setup = "A2_BREAKDOWN"
        elif float(p.close) >= float(p.vwap) and close < float(r.vwap):
            setup = "A3_VWAP_REJECTION"
        elif float(p.close) >= float(p.ema9) and close < float(r.ema9):
            setup = "A1_TREND_PULLBACK"
        elif int(r.step_state) == -1 and int(p.step_state) != -1:
            setup = "A5_STEP_FLIP"
    if setup:
        reasons.append(setup)
    else:
        rejects.append("no_entry_pattern")

    # A breakout needs stronger volume and a decisive close; don't let total score hide this.
    if setup in {"A2_BREAKOUT", "A2_BREAKDOWN"}:
        if rvol < (1.5 if profile == "strict" else 1.2):
            rejects.append("breakout_volume_insufficient")
        if direction == "LONG" and float(r.clv) < 0.65:
            rejects.append("breakout_close_not_near_high")
        if direction == "SHORT" and float(r.clv) > -0.65:
            rejects.append("breakdown_close_not_near_low")

    score = 0
    if direction:
        score += 20; reasons.append("ema_alignment:+20")
    if adx >= 28:
        score += 15; reasons.append("adx_strong:+15")
    elif adx >= adx_floor:
        score += 10; reasons.append("adx_ok:+10")
    if direction and ((direction == "LONG" and close > float(r.vwap)) or (direction == "SHORT" and close < float(r.vwap))):
        score += 12; reasons.append("vwap_alignment:+12")
    if setup:
        score += 18; reasons.append("setup_trigger:+18")
    if rvol >= 1.5:
        score += 12; reasons.append("rvol_strong:+12")
    elif rvol >= rvol_floor:
        score += 7; reasons.append("rvol_ok:+7")
    if direction and ((direction == "LONG" and rsi >= 52) or (direction == "SHORT" and rsi <= 48)):
        score += 8; reasons.append("rsi_momentum:+8")
    if float(r.er10) >= defaults.ER_MIN:
        score += 5; reasons.append("efficiency:+5")

    # Higher-timeframe context adjusts confidence but does not replace the
    # setup evidence or override independent hard rejection gates.
    if context_adjustment:
        score += int(context_adjustment)
        reasons.append(f"{context_label or 'higher_timeframe_context'}:{int(context_adjustment):+d}")
    elif context_label:
        reasons.append(context_label)
    # Options can adjust the score, but never override hard technical rejections.
    score = max(0, min(100, score + (int(option_adjustment) if option_available else 0)))
    no_option_floor = defaults.NO_OC_MIN_TECH_SCORE if profile == "strict" else min_score
    if not option_available and score < no_option_floor:
        rejects.append("option_chain_unavailable_requires_tech_score_75" if profile == "strict" else "score_below_balanced_technical_floor")
    if score < min_score:
        rejects.append("score_below_minimum")

    metrics = {
        k: (float(r[k]) if _finite(r.get(k)) else None)
        for k in ("close", "atr14", "adx14", "plus_di", "minus_di", "rsi14", "rvol", "body_ratio", "clv", "ema9", "ema21", "vwap", "step_line", "er10")
    }
    metrics.update({
        "ema9_extension_atr": round(ema9_extension, 3),
        "ema21_extension_atr": round(ema21_extension, 3),
        "profile": profile,
        "context_adjustment": int(context_adjustment),
        "context_label": context_label,
        "score_components": {
            "ema_alignment": 20 if direction else 0,
            "adx": 15 if adx >= 28 else 10 if adx >= adx_floor else 0,
            "vwap_alignment": 12 if direction and ((direction == "LONG" and close > float(r.vwap)) or (direction == "SHORT" and close < float(r.vwap))) else 0,
            "entry_setup": 18 if setup else 0,
            "relative_volume": 12 if rvol >= 1.5 else 7 if rvol >= rvol_floor else 0,
            "rsi_momentum": 8 if direction and ((direction == "LONG" and rsi >= 52) or (direction == "SHORT" and rsi <= 48)) else 0,
            "er10": 5 if float(r.er10) >= defaults.ER_MIN else 0,
            "option_adjustment": int(option_adjustment) if option_available else 0,
            "context_adjustment": int(context_adjustment),
        },
        "hard_gates": {
            "entry_setup": bool(setup),
            "ema_alignment": direction is not None,
            "adx_minimum": adx >= adx_floor,
            "vwap_side": bool(direction and ((direction == "LONG" and close > float(r.vwap)) or (direction == "SHORT" and close < float(r.vwap)))),
        },
    })
    # Hard rejection gates are fail-closed and cannot be rescued by a high numeric score.
    return Score(score, direction if not rejects else None, setup, reasons, rejects, metrics)


def score_explosion(df, min_score: int = defaults.EXPLOSION_MIN_SCORE, *, profile: str = "strict") -> Score:
    """High-conviction impulse scanner; requires volume, range, body and close location."""
    if len(df) < 35:
        return Score(0, None, None, [], ["insufficient_history"], {})
    r = df.iloc[-1]
    keys = ("atr14", "rvol", "tr_atr", "body_ratio", "clv", "roc10", "vwap")
    if not all(_finite(r.get(k)) for k in keys):
        return Score(0, None, None, [], ["indicator_warmup"], {})
    close, atr = float(r.close), float(r.atr14)
    direction = "LONG" if float(r.close) > float(r.open) and float(r.clv) >= 0 else "SHORT" if float(r.close) < float(r.open) and float(r.clv) <= 0 else None
    rvol_min = 2.5 if profile == "strict" else 2.0
    range_min = 1.8 if profile == "strict" else 1.5
    body_min = 0.65 if profile == "strict" else 0.55
    clv_min = 0.70 if profile == "strict" else 0.60
    gates = {
        "rvol": float(r.rvol) >= rvol_min,
        "range_expansion": float(r.tr_atr) >= range_min,
        "body_ratio": float(r.body_ratio) >= body_min,
        "close_location": float(r.clv) >= clv_min if direction == "LONG" else float(r.clv) <= -clv_min if direction == "SHORT" else False,
        "not_overextended": abs(close - float(r.vwap)) <= 2.5 * atr,
    }
    reasons = [f"{k}:pass" for k, passed in gates.items() if passed]
    rejects = [f"{k}:fail" for k, passed in gates.items() if not passed]
    if not direction:
        rejects.append("no_directional_impulse")
    score = (25 if gates["rvol"] else 0) + (20 if gates["range_expansion"] else 0) + (20 if gates["body_ratio"] else 0) + (20 if gates["close_location"] else 0) + (10 if direction and abs(float(r.roc10)) >= 0.5 else 0) + (5 if direction else 0)
    if score < min_score:
        rejects.append("score_below_minimum")
    metrics = {k: float(r[k]) for k in ("close", "atr14", "rvol", "tr_atr", "body_ratio", "clv", "roc10", "vwap")}
    return Score(min(100, score), direction if not rejects else None, "EXPLOSION", reasons, rejects, metrics)


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False
