# Integrated build status

This is the consolidated project package. CORE strategy, explosion strategy logic, indicators, option-chain analytics, candidate lifecycle, Telegram commands, REST historical polling, API endpoints, replay harness, and tests are integrated.

## Explicit limitations before live deployment
- Upstox REST API calls use documented V3 historical candle and V2 option-chain endpoints. Credentials, access-token validity, instrument-master schema and account entitlements must be tested with your own account.
- Upstox V3 WebSocket uses protobuf binary messages. This package intentionally does not claim live WebSocket operation: `market_data/websocket_adapter.py` fails closed until the current official protobuf decoder is integrated. Current runtime uses REST closed-candle polling.
- EXPLOSION selection requires a verified 20-session median turnover ranking or a manually verified override in `config/explosion_universe.json`. It will not invent a 150-symbol universe from incomplete instrument metadata.
- Market holiday list is intentionally empty and must be populated from the official NSE calendar. Until then, calendar checks only cover weekdays and trading hours.
- The current scan coordinator is a conservative implementation baseline, not a claim that every rule in the long specification has been implemented or validated. Test results are software tests, not trading-performance evidence.
- No orders are sent. Option chain analytics are underlying-level context; exact contract selection, premium-entry validation and option liquidity checks are exposed as utilities but not auto-selected for alerts.

## Optimization pass (2026-10-22)

- Current defaults are `FILTER_PROFILE=strict`, CORE `MIN_SCORE=75`, and EXPLOSION `EXPLOSION_MIN_SCORE=80`.
- Follow-up latency pass: bounded concurrent scans (default 4, max 8), 30-minute historical warm-up cache, and a one-minute closed-candle rescan cycle. Intraday candles are refreshed on every scan; no unfinished candles are used.
- Added hard gates for ADX level/rising state, directional DI spread, relative volume, candle body/close location, EMA extension, and breakout-specific volume/close quality.
- Added fail-closed 15-minute confirmation when the required closed-bar history is missing.
- Added per-symbol/engine cooldown and protection against overwriting pending/active candidates.
- Candidate target levels now use the conservative entry-zone edge when calculating risk multiples.
- Added strict-filter regression tests. This remains an unverified strategy hypothesis until replay and forward tests are run on representative historical/live data.
