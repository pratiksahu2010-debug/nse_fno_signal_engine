"""Causal 5-minute candle replay for research, not a profitability guarantee.

Example:
  python -m replay.backtest candles.csv --profile strict --cost-bps-per-side 10 --slippage-bps-per-side 5

CSV columns required: ts, open, high, low, close, volume. Input must be chronological
5-minute candles for one instrument; use separate runs per symbol. When a candle
hits both stop and target, the replay conservatively assumes the stop occurred first.
"""
from __future__ import annotations

import argparse
import json
import pandas as pd
from engines.indicators import add_indicators
from engines.scoring import score_core


def replay(path, min_score=75, *, profile="strict", cost_bps_per_side=0.0,
           slippage_bps_per_side=0.0, max_hold_bars=12):
    if cost_bps_per_side < 0 or slippage_bps_per_side < 0:
        raise ValueError("Costs and slippage must be non-negative")
    if max_hold_bars < 1:
        raise ValueError("max_hold_bars must be >= 1")
    d = pd.read_csv(path, parse_dates=["ts"])
    d = add_indicators(d)
    trades = []
    next_eligible_index = 35
    last_signal_index = None
    per_side_bps = float(cost_bps_per_side) + float(slippage_bps_per_side)

    for i in range(35, len(d) - 1):
        if i < next_eligible_index:
            continue
        if last_signal_index is not None and i - last_signal_index < 6:
            continue
        hist = d.iloc[:i + 1]  # Strategy cannot see future rows.
        result = score_core(hist, min_score, 0, False, profile=profile)
        if not result.direction:
            continue
        row = hist.iloc[-1]
        entry_i = i + 1
        entry = float(d.iloc[entry_i].open)
        atr = float(row.atr14)
        if not pd.notna(atr) or atr <= 0 or entry <= 0:
            continue
        direction = result.direction
        stop = entry - 1.5 * atr if direction == "LONG" else entry + 1.5 * atr
        risk = abs(entry - stop)
        target = entry + 1.5 * risk if direction == "LONG" else entry - 1.5 * risk
        exit_px = float(d.iloc[min(entry_i + max_hold_bars - 1, len(d) - 1)].close)
        exit_i = min(entry_i + max_hold_bars - 1, len(d) - 1)
        reason = "max_hold_or_end_of_data"

        for j in range(entry_i, min(entry_i + max_hold_bars, len(d))):
            bar = d.iloc[j]
            if direction == "LONG":
                stop_hit, target_hit = float(bar.low) <= stop, float(bar.high) >= target
            else:
                stop_hit, target_hit = float(bar.high) >= stop, float(bar.low) <= target
            if stop_hit:  # conservative tie-break when stop and target both trade in one bar
                exit_px, exit_i, reason = stop, j, "stop"
                break
            if target_hit:
                exit_px, exit_i, reason = target, j, "target"
                break

        signed_gross = (exit_px - entry) * (1 if direction == "LONG" else -1)
        # Approximate per-side costs as basis points of entry notional; option premium
        # mapping, taxes, and instrument-specific charges are not inferred here.
        cost_points = entry * per_side_bps * 2 / 10000.0
        signed_net = signed_gross - cost_points
        net_r = signed_net / risk
        trades.append({
            "signal_time": str(row.ts), "direction": direction, "setup": result.setup,
            "score": result.score, "entry_time": str(d.iloc[entry_i].ts), "entry": entry,
            "stop": stop, "target_t1": target, "exit": exit_px,
            "gross_r": signed_gross / risk, "net_r": net_r,
            "cost_points_estimate": cost_points, "reason": reason,
            "exit_time": str(d.iloc[exit_i].ts), "hold_bars": exit_i - entry_i + 1,
        })
        last_signal_index = i
        next_eligible_index = exit_i + 1  # no overlapping trades in a single-symbol replay

    rs = [float(x["net_r"]) for x in trades]
    gross_rs = [float(x["gross_r"]) for x in trades]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]
    stop_count = sum(x["reason"] == "stop" for x in trades)
    eq = peak = drawdown = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        drawdown = max(drawdown, peak - eq)
    gross_profit = sum(x for x in rs if x > 0)
    gross_loss = abs(sum(x for x in rs if x < 0))
    return {
        "file": path, "profile": profile, "min_score": min_score,
        "trades": len(trades), "win_rate_pct": 100 * len(wins) / len(rs) if rs else 0,
        "stop_before_target_rate_pct": 100 * stop_count / len(trades) if trades else 0,
        "avg_win_r": sum(wins) / len(wins) if wins else 0,
        "avg_loss_r": sum(losses) / len(losses) if losses else 0,
        "expectancy_net_r": sum(rs) / len(rs) if rs else 0,
        "expectancy_gross_r": sum(gross_rs) / len(gross_rs) if gross_rs else 0,
        "profit_factor_net": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown_net_r": drawdown,
        "cost_bps_per_side": cost_bps_per_side,
        "slippage_bps_per_side": slippage_bps_per_side,
        "cost_model_warning": "Basis-point approximation only; configure charges for your broker/instrument. Not option-premium P&L.",
        "warning": "Research replay only; not evidence of profitability or live execution quality.",
        "trades_detail": trades,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--min-score", type=int, default=75)
    parser.add_argument("--profile", choices=("strict", "balanced"), default="strict")
    parser.add_argument("--cost-bps-per-side", type=float, default=0.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=0.0)
    parser.add_argument("--max-hold-bars", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(replay(args.csv, args.min_score, profile=args.profile,
                            cost_bps_per_side=args.cost_bps_per_side,
                            slippage_bps_per_side=args.slippage_bps_per_side,
                            max_hold_bars=args.max_hold_bars), indent=2))
