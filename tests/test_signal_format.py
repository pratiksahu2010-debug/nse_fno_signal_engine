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

    assert "BUY PUT (PE)" in message
    assert "SHORT / BEARISH SIGNAL" in message
    assert "OPTION CONTRACT" in message
    assert "PREMIUM TRADE PLAN" in message
    assert "SIGNAL QUALITY" in message
    assert "Greeks" in message
    assert "Entry validity" in message
    assert "Support / resistance" in message
    assert "SIGNAL DETAILS" in message
    assert "TRADE PLAN (UNDERLYING REFERENCE LEVELS)" in message
    assert "Stop-loss (SL)" in message
    assert "Target 1 (TP1)" in message
    assert "TECHNICAL INDICATORS" in message
    assert "EMA 9 / EMA 21" in message
    assert "WHY THIS SIGNAL?" in message
    assert "no order is placed automatically" in message



def test_format_signal_renders_selected_option_contract_without_fabricating_fields():
    ist = ZoneInfo("Asia/Kolkata")
    candidate = Candidate(
        symbol="RELIANCE", direction="LONG", engine="CORE", setup="A2_BREAKOUT",
        score=79, signal_time=datetime(2026, 10, 23, 10, 0, tzinfo=ist),
        signal_close=1450, signal_high=1453, signal_low=1448, atr=4,
        entry_low=1450, entry_high=1451, stop=1445, t1=1460, t2=1470,
    )
    score = Score(79, "LONG", "A2_BREAKOUT", ["ema_alignment", "vwap_alignment"], [], {
        "ema9": 1451, "ema21": 1448, "rsi14": 60, "adx14": 28, "vwap": 1449,
        "atr14": 4, "rvol": 1.5, "donchian_low20": 1430, "donchian_high20": 1465,
    })
    option = {
        "trading_symbol": "RELIANCE26OCT1450CE", "expiry": "2026-10-29",
        "strike": 1450, "lot_size": 250, "bid": 22.5, "ask": 23.0, "ltp": 22.8,
        "estimated_cost_per_lot": 5750, "premium_entry_low": 22.5, "premium_entry_high": 23.0,
        "premium_stop": 20.0, "premium_t1": 27.5, "premium_t2": 32.5,
        "risk_per_lot": 750, "premium_rr1": 1.8, "premium_rr2": 3.8,
        "delta": 0.52, "gamma": 0.001, "theta": -2.1, "vega": 0.8, "iv": 22.5,
        "oi": 125000, "volume": 45000, "spread_pct": 2.2,
    }
    message = SignalEngine.format_signal(candidate, score, option)
    assert "🟩 <b>BUY CALL (CE)" in message
    assert "RELIANCE26OCT1450CE" in message
    assert "₹5,750.00" in message
    assert "₹20.00" in message
    assert "₹27.50" in message
    assert "125,000" in message
