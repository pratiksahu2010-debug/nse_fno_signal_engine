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
6. Open `/ping`, `/health`, and `/status`. On startup, the service verifies the Telegram bot token with `getMe` and sends one Telegram delivery-test message to `TELEGRAM_CHAT_ID`. Check `/health.components.telegram_delivery` or `/status.telegram_delivery` for message counts and the last delivery error. Inbound Telegram command polling is disabled, so use HTTP endpoints for health/status checks. For a private chat, set `TELEGRAM_CHAT_ID` to your own numeric Telegram user ID (not the bot's ID, bot username, or token), open the configured bot in Telegram, and press Start. You can obtain your numeric user ID from a trusted Telegram user-ID helper bot. For a group, add your bot and use the group's numeric chat ID (often a negative number); for a channel, add it with permission to post and use the channel chat ID. Telegram does not allow a bot to message another bot, so `Forbidden: the bot can't send messages to the bot` means the destination is wrong and must be corrected in Render Environment.

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

## Telegram signal format and market-close report

Confirmed CORE and EXPLOSION alerts are formatted as readable Telegram HTML messages with signal timestamp (IST and UTC), symbol/engine/setup/score, signal close, next-5-minute entry zone, stop and two targets, calculated reward-to-risk, EMA 9/21, RSI, ADX, VWAP, ATR, RVOL, directional indicators, candle quality, reasons and rejection gates. Price levels are **underlying reference levels**, not option-premium prices; the service remains signal-only and does not place orders.

The service also attempts one daily summary after the configured NSE session close (normally 15:30 IST, with special-session times read from the market calendar). The report includes daily signal counts by direction and engine, candidate statuses, recent signals, top rejection counts and data/scan diagnostics. It is sent by the running service's polling loop; if the Render service sleeps or is unavailable at close, delivery may be delayed or missed. Signal/candidate history and the duplicate-send guard are currently in memory, so a restart can reset summary counts or allow a duplicate summary. Use durable storage and an always-on instance if reliable historical reporting is required.


### Strict vs balanced replay comparison

Run both profiles against the **same chronological 5-minute CSV** and the same assumptions:

```bash
python -m replay.backtest path/to/candles.csv --min-score 70 --compare-profiles --cost-bps-per-side 8 --slippage-bps-per-side 3 --max-hold-bars 12
```

Replace the example cost/slippage values with defensible estimates for the instrument and broker being studied; the numbers above are examples, not measured NSE charges. Output is JSON. The comparison includes trade count, win rate, gross/net expectancy in R, net profit factor, max drawdown in R, rejection reasons, and counterfactual outcomes for certain rejected setups.

To run one profile only:

```bash
python -m replay.backtest path/to/candles.csv --profile balanced --min-score 70 --cost-bps-per-side 8 --slippage-bps-per-side 3 --max-hold-bars 12
```

CSV requirements and interpretation:

- Required columns: `ts,open,high,low,close,volume`; optional `oi`. Keep timestamps parseable and rows in ascending time order. Use one instrument per file and use completed 5-minute candles.
- The replay uses the next candle's open as the entry approximation and resolves a same-bar stop/target collision conservatively as a stop first. It is not an options-premium simulation.
- `rejected_setup_count` and `rejected_forward_outcomes` are diagnostic counterfactuals for rejected setups, not extra trades. They can overlap accepted trades and one another; do not add them to P&L or use them as live signals.
- A same-period strict/balanced comparison is in-sample. Choose thresholds only after checking a separate later out-of-sample period, across multiple symbols and different market conditions. Include realistic charges and slippage; do not optimize only for win rate or signal count.
- The default profile remains `strict`. Use `balanced` as a controlled research comparison, not an automatic production recommendation.
