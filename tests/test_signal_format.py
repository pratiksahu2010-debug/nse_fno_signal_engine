from datetime import datetime
from zoneinfo import ZoneInfo

from engines.scoring import Score
from market_data.engine import SignalEngine
from engines.candidates import Candidate


def test_format_signal_contains_trade_plan_and_indicators():
    ist = ZoneInfo("Asia/Kolkata")
    candidate = Candidate(
        symbol="RELIANCE",
        direction="SHORT",
        engine="CORE",
        setup="A1_TREND_PULLBACK",
        score=82,
        signal_time=datetime(2026, 10, 23, 14, 20, tzinfo=ist),
        signal_close=1450.0,
        signal_high=1455.0,
        signal_low=1448.0,
        atr=4.0,
        entry_low=1449.0,
        entry_high=1450.0,
        stop=1457.0,
        t1=1436.0,
        t2=1430.0,
    )
    score = Score(
        score=82,
        direction="SHORT",
        setup="A1_TREND_PULLBACK",
        reasons=["A1_TREND_PULLBACK", "ema_alignment:+20", "vwap_alignment:+12"],
        rejects=[],
        metrics={
            "ema9": 1451.0,
            "ema21": 1453.0,
            "rsi14": 42.0,
            "adx14": 27.0,
            "vwap": 1452.0,
            "atr14": 4.0,
            "rvol": 1.6,
            "plus_di": 14.0,
            "minus_di": 26.0,
            "ema9_extension_atr": 0.25,
            "body_ratio": 0.72,
            "clv": -0.75,
        },
    )

    message = SignalEngine.format_signal(candidate, score)

    assert "SHORT / BEARISH SIGNAL" in message
    assert "SIGNAL DETAILS" in message
    assert "TRADE PLAN (UNDERLYING REFERENCE LEVELS)" in message
    assert "Stop-loss (SL)" in message
    assert "Target 1 (TP1)" in message
    assert "TECHNICAL INDICATORS" in message
    assert "EMA 9 / EMA 21" in message
    assert "WHY THIS SIGNAL?" in message
    assert "no order is placed automatically" in message
