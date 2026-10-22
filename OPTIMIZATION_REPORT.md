# NSE F&O Signal Engine — Optimization Pass

Date: 2026-10-22

## Changes applied

- Default `FILTER_PROFILE=strict`.
- Default `MIN_SCORE=80` and `EXPLOSION_MIN_SCORE=80`.
- CORE hard gates for ADX level/rising behavior, directional +DI/-DI spread, RVOL, candle body, close location, RSI range, VWAP side, and EMA9/EMA21 extension.
- Breakout-specific stronger RVOL and close-location requirements.
- EXPLOSION hard gates for relative volume, range expansion, body, close location, and maximum distance from VWAP.
- CORE 15-minute confirmation now fails closed if adequate completed bars are not available.
- Option-chain analysis is only attempted for a technically valid preliminary direction; it uses that direction rather than defaulting missing directions to LONG.
- Pending/active candidates cannot be overwritten; cooldown is applied per symbol/engine.
- Targets are derived from the conservative edge of the entry zone so reward:risk is not overstated.
- Replay accepts strict/balanced profiles, estimated per-side cost/slippage inputs, a max holding period, and avoids overlapping trades in a single-symbol replay.

## Verification performed

- `pytest -q`: 19 passed.
- `python -m compileall -q .`: passed.
- FastAPI app import: passed.
- ZIP integrity: verified after packaging.

## Important limits

- No live Upstox credentials were used; no live API/WebSocket session was verified.
- The V3 protobuf WebSocket decoder remains unimplemented; the current market-data path is REST closed-candle polling.
- Automatic EXPLOSION universe ranking and several requested option-chain/order-flow filters remain incomplete; see `PHASE_STATUS.md`.
- No historical performance result or 90% false-signal reduction is claimed. Use representative historical data and out-of-sample forward testing before relying on signals.
- Replay costs are configurable basis-point approximations and do not automatically model every broker charge, taxes, futures/options basis, or option premium P&L.
