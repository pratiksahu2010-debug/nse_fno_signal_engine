from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from engines.candidates import make_candidate, on_closed_candle
from engines.scoring import score_core


def _scoring_frame(*, close=101.0, vwap=100.0, rsi=60.0, donchian_high=100.5):
    rows = []
    start = datetime(2026, 10, 1, 9, 15, tzinfo=timezone.utc)
    for i in range(35):
        price = 100.0
        rows.append({
            "ts": start + timedelta(minutes=5 * i),
            "open": 99.8,
            "high": 100.2,
            "low": 99.5,
            "close": price,
            "atr14": 1.0,
            "adx14": 24.0,
            "rsi14": 55.0,
            "ema9": 99.8,
            "ema21": 99.0,
            "vwap": 99.7,
            "rvol": 1.6,
            "plus_di": 30.0,
            "minus_di": 15.0,
            "body_ratio": 0.7,
            "clv": 0.6,
            "er10": 0.5,
            "donchian_high20": 100.8,
            "donchian_low20": 98.0,
            "step_line": 99.5,
            "step_state": 1,
        })
    rows[-2].update({"close": 99.7, "adx14": 23.0, "step_state": 0})
    rows[-1].update({
        "open": close - 0.8,
        "high": close + 0.1,
        "low": close - 0.9,
        "close": close,
        "atr14": 1.0,
        "adx14": 25.0,
        "rsi14": rsi,
        "ema9": 100.5,
        "ema21": 99.5,
        "vwap": vwap,
        "rvol": 1.6,
        "plus_di": 30.0,
        "minus_di": 15.0,
        "body_ratio": 0.8,
        "clv": 0.8,
        "er10": 0.5,
        "donchian_high20": donchian_high,
        "donchian_low20": 98.0,
        "step_line": 100.0,
        "step_state": 1,
    })
    return pd.DataFrame(rows)


def test_breakout_takes_precedence_over_overlapping_ema_reclaim():
    frame = _scoring_frame(close=101.0, donchian_high=100.5)
    result = score_core(frame, min_score=70, option_available=True, profile="balanced")
    assert result.setup == "A2_BREAKOUT"
    assert result.direction == "LONG"
    assert "A2_BREAKOUT" in result.reasons


def test_balanced_profile_does_not_hard_reject_a_valid_long_pullback_below_vwap():
    # This is not a breakout: the candle reclaims EMA9 in an EMA uptrend, but
    # remains below VWAP. Balanced mode should let the score decide; strict mode
    # retains its VWAP-side rejection.
    frame = _scoring_frame(close=100.6, vwap=101.0, donchian_high=101.2)
    frame.iloc[-2, frame.columns.get_loc("close")] = 100.4
    frame.iloc[-1, frame.columns.get_loc("ema9")] = 100.5
    frame.iloc[-1, frame.columns.get_loc("ema21")] = 100.0
    frame.iloc[-1, frame.columns.get_loc("clv")] = 0.8
    balanced = score_core(frame, min_score=65, option_available=True, profile="balanced")
    strict = score_core(frame, min_score=65, option_available=True, profile="strict")
    assert "below_vwap" not in balanced.rejects
    assert "below_vwap" in strict.rejects
    # Rejected diagnostics retain direction without exposing a tradable signal.
    assert strict.direction is None
    assert strict.metrics["proposed_direction"] == "LONG"


def test_candidate_lifecycle_advances_once_per_unique_closed_candle():
    signal_ts = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)
    signal_candle = SimpleNamespace(
        ts=signal_ts, close=100.0, high=101.0, low=99.0,
        swing_low=99.0, swing_high=101.0,
    )
    candidate = make_candidate("TEST", "LONG", "CORE", "A1_TREND_PULLBACK", 75,
                               signal_candle, atr=2.0)
    next_candle = SimpleNamespace(
        ts=signal_ts + timedelta(minutes=5),
        open=100.0, close=100.25, high=100.5, low=99.9,
    )
    assert on_closed_candle(candidate, next_candle) == "ENTERED"
    assert candidate.bars_seen == 1
    assert on_closed_candle(candidate, next_candle) is None
    assert candidate.bars_seen == 1

def _five_minute_frame(start, count, missing=()):
    rows = []
    for i in range(count):
        if i in missing:
            continue
        ts = start + timedelta(minutes=5 * i)
        rows.append({
            "ts": ts,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_completed_15m_bars_excludes_bucket_with_missing_5m_constituent():
    from market_data.engine import completed_15m_bars

    start = datetime(2026, 10, 24, 9, 15, tzinfo=timezone.utc)
    frame = _five_minute_frame(start, 6, missing=(1,))
    result = completed_15m_bars(frame, start + timedelta(minutes=32))
    assert result["ts"].tolist() == [start + timedelta(minutes=15)]


def test_completed_15m_bars_excludes_still_forming_bucket():
    from market_data.engine import completed_15m_bars

    start = datetime(2026, 10, 24, 9, 15, tzinfo=timezone.utc)
    frame = _five_minute_frame(start, 4)
    result = completed_15m_bars(frame, start + timedelta(minutes=17))
    assert result["ts"].tolist() == [start]


def test_rejected_forward_outcome_labels_target_and_mfe_mae_without_trade_creation():
    from replay.backtest import _rejected_forward_outcome

    start = datetime(2026, 10, 24, 9, 15, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        {"ts": start, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
        {"ts": start + timedelta(minutes=5), "open": 100.0, "high": 103.0, "low": 99.8, "close": 102.0},
    ])
    result = _rejected_forward_outcome(frame, 0, "LONG", 1.0, 3)
    assert result is not None
    assert result["outcome"] == "target"
    assert result["mfe_r"] >= 1.5
    assert result["mae_r"] <= 0

def test_compare_profiles_uses_same_data_and_cost_assumptions(monkeypatch):
    from replay import backtest

    calls = []

    def fake_replay(path, min_score, *, profile, cost_bps_per_side,
                    slippage_bps_per_side, max_hold_bars):
        calls.append((path, min_score, profile, cost_bps_per_side,
                      slippage_bps_per_side, max_hold_bars))
        return {
            "trades": 3, "win_rate_pct": 50.0, "expectancy_net_r": 0.2,
            "expectancy_gross_r": 0.3, "profit_factor_net": 1.2,
            "max_drawdown_net_r": 1.0, "rejected_setup_count": 4,
            "rejection_reason_counts": {}, "rejected_forward_outcomes": {},
        }

    monkeypatch.setattr(backtest, "replay", fake_replay)
    result = backtest.compare_profiles(
        "sample.csv", 70, cost_bps_per_side=8,
        slippage_bps_per_side=3, max_hold_bars=10,
    )
    assert [call[2] for call in calls] == ["strict", "balanced"]
    assert all(call[0] == "sample.csv" and call[1] == 70 for call in calls)
    assert all(call[3:] == (8, 3, 10) for call in calls)
    assert set(result["profiles"]) == {"strict", "balanced"}
    assert "not proof of future performance" in result["comparison_warning"]
