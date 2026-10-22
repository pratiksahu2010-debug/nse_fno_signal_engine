import pandas as pd
from engines.scoring import score_core, score_explosion


def make_core_frame(n=40):
    rows=[]
    for i in range(n):
        rows.append({
            "ts": pd.Timestamp("2026-01-01", tz="Asia/Kolkata") + pd.Timedelta(minutes=5*i),
            "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0,
            "atr14": 2.0, "adx14": 28.0, "rsi14": 58.0,
            "ema9": 102.0, "ema21": 101.0, "vwap": 100.5,
            "rvol": 1.7, "plus_di": 30.0, "minus_di": 15.0,
            "body_ratio": 0.60, "clv": 0.60, "er10": 0.40,
            "donchian_high20": 102.5, "donchian_low20": 98.0,
            "step_state": 1, "step_line": 101.0,
        })
    rows[-2]["close"] = 101.5
    rows[-2]["ema9"] = 102.0
    return pd.DataFrame(rows)


def test_strict_core_rejects_di_conflict_even_when_score_is_high():
    d = make_core_frame()
    d.loc[d.index[-1], "plus_di"] = 12.0
    d.loc[d.index[-1], "minus_di"] = 28.0
    result = score_core(d, min_score=65, option_available=True, profile="strict")
    assert "di_conflict" in result.rejects
    assert result.direction is None


def test_strict_core_rejects_weak_volume_and_late_extension():
    d = make_core_frame()
    d.loc[d.index[-1], "rvol"] = 0.8
    d.loc[d.index[-1], "close"] = 108.0
    result = score_core(d, min_score=65, option_available=True, profile="strict")
    assert "low_relative_volume" in result.rejects
    assert "overextended_from_ema9" in result.rejects
    assert result.direction is None


def test_explosion_rejects_overextended_impulse():
    d = make_core_frame()
    d.loc[d.index[-1], ["open", "high", "low", "close"]] = [106.0, 110.0, 105.0, 109.0]
    d.loc[d.index[-1], ["rvol", "tr_atr", "body_ratio", "clv", "roc10", "vwap"]] = [3.0, 2.0, 0.8, 0.8, 0.8, 100.0]
    result = score_explosion(d, min_score=75, profile="strict")
    assert "not_overextended:fail" in result.rejects
    assert result.direction is None
