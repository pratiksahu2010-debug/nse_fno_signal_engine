# NSE F&O Signal Engine — consolidated Python 3.11 package

Signal-only intraday research bot with FastAPI health endpoints, Upstox REST historical-candle polling, CORE trend setups, independent EXPLOSION impulse scoring, option-chain context, Telegram alerts/commands, candidate lifecycle, and CSV replay.

## Safety / scope
This code does not place orders. Signals are based on completed 5-minute candles. The engine discards candles younger than 5 minutes + 2-second grace. Do not interpret passing unit tests as proof of profitability. Run in paper/sandbox observation first.

## Deploy
1. Create a GitHub repository and upload all files.
2. On Render create a Web Service from the repo. Build: `pip install --upgrade pip && pip install -r requirements.txt`. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
3. Copy `.env.example` values into Render Environment. Set `UPSTOX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally `TELEGRAM_ADMIN_IDS` (comma-separated Telegram numeric IDs). Never commit credentials.
4. Populate `config/nse_holidays.json` with official NSE holidays/special sessions. Resolve the instruments and check `/health`.
5. For explosion symbols, supply a verified list to `config/explosion_universe.json`. Do not treat the empty default as a generated universe.
6. Open `/ping`, `/health`, and `/status`. This deployment sends outbound Telegram alerts; inbound Telegram command polling is disabled, so use the HTTP endpoints for health/status checks.

## Build and test locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate ; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m compileall -q .
pytest -q
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Historical replay
CSV must contain `ts,open,high,low,close,volume`; optional `oi`. Example:
`python -m replay.backtest sample_candles.csv --min-score 70`
Replay is an educational close/next-open approximation, not an options backtest. Estimated fees/slippage can be configured, but instrument-specific charges and option-premium P&L are not fully modeled; do not treat replay as a profitability claim.

## Current transport caveat
Upstox Market Data Feed V3 uses protobuf binary frames. The WebSocket adapter is a fail-closed integration boundary; runtime currently uses REST polling of closed candles. Do not describe this build as websocket-connected. Integrate the current official Upstox protobuf schema/SDK and test reconnect/subscription limits before enabling WebSocket mode.

## Render free tier
Free instances may sleep and can miss market-time work. A periodic `/ping` request may reduce idling in some setups but does not guarantee uptime or replace a paid always-on service. In-memory state is lost on restart; use durable storage before relying on signal history.

## Strict signal-quality profile (optimized defaults)

The default profile is `FILTER_PROFILE=strict` with `MIN_SCORE=75` and
`EXPLOSION_MIN_SCORE=80`. The scanner uses bounded concurrency and caches historical
warm-up candles for 30 minutes while refreshing intraday candles each scan. The CORE engine applies hard rejection gates for ADX
strength/rising behavior, +DI/-DI alignment, relative volume, candle body and
close location, overextension from EMA9/EMA21, VWAP side, RSI range, and stronger
volume/close-location requirements on breakouts. The 15-minute trend confirmation
fails closed if enough closed 15-minute bars are unavailable. Option-chain score
adjustments cannot override technical hard-rejection gates.

Use `FILTER_PROFILE=balanced` only for controlled comparison. It relaxes selected
thresholds; it does not disable the closed-candle rule. Compare both profiles on
the same chronological data with realistic fees/slippage before choosing a live
configuration. Strict filters reduce signal count and can miss profitable moves;
no fixed false-signal reduction is guaranteed.

Candidate management also prevents a new signal from overwriting a still-pending
or active candidate for the same symbol/engine, enforces a per-symbol cooldown,
and calculates target distances from the conservative edge of the advertised
entry zone so reward:risk is not overstated.
