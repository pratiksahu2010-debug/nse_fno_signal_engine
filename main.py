"""NSE F&O signal-only service: FastAPI health endpoints, signal engine, Telegram polling."""
from __future__ import annotations
import asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from config.settings import Settings
from utils.logging_setup import configure_logging
from utils.market_calendar import MarketCalendar
from utils.time_utils import now_ist
from market_data.upstox_rest import UpstoxREST
from market_data.instruments import InstrumentResolver
from market_data.engine import SignalEngine
from services.telegram_service import TelegramService

settings = Settings.from_env()
configure_logging(settings.log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)
calendar = MarketCalendar()
started_at = now_ist()
rest = resolver = telegram = engine = None
tasks = []


async def command_handler(message):
    global engine, telegram
    message_text = str(message.get("text", "")).strip()
    chat = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    if not message_text.startswith("/"):
        return
    parts = message_text.split(maxsplit=1)
    command = parts[0].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # Public read-only onboarding/status commands; operational controls are admin-only.
    if command in {"/start", "/help"}:
        await telegram.send(
            "NSE F&O signal-only bot\n/status /watchlist /today /pending /why SYMBOL\n"
            "Admin: /scan /signal SYMBOL /pause /resume /settoken TOKEN\n"
            "Configure TELEGRAM_ADMIN_ID in Render to enable admin commands. No automatic orders are placed.",
            chat,
        )
        return
    if command == "/status":
        await telegram.send(str(engine.status() if engine else {"status": "starting"}), chat)
        return
    admin_commands = {"/scan", "/signal", "/pause", "/resume", "/settoken", "/explode", "/oc", "/settings", "/stats"}
    if command in admin_commands and (user_id is None or int(user_id) not in settings.telegram_admin_ids):
        await telegram.send("Admin only. Set your numeric Telegram user ID in Render as TELEGRAM_ADMIN_ID, then redeploy.", chat)
        return
    if command == "/scan":
        await telegram.send(str(await engine.scan(limit=30)), chat)
        return
    if command == "/pending":
        await telegram.send("\n".join(
            f"{c.symbol} {c.direction} {c.status} entry={c.entry_low:.2f}-{c.entry_high:.2f} SL={c.stop:.2f} T1={c.t1:.2f} T2={c.t2:.2f}"
            for c in engine.candidates.values() if c.status == "PENDING"
        ) or "No pending candidates.", chat)
        return
    if command == "/today":
        await telegram.send(
            f"Signals today: {len(engine.signals)}\n" +
            "\n".join(f"{s['time']} {s['symbol']} {s['direction']} {s['score']}" for s in engine.signals[-20:]),
            chat,
        )
        return
    if command == "/watchlist":
        await telegram.send(", ".join(engine.keys) or "No symbols resolved yet", chat)
        return
    if command == "/pause":
        engine.paused = True
        await telegram.send("Signal scanning paused.", chat)
        return
    if command == "/resume":
        engine.paused = False
        await telegram.send("Signal scanning resumed.", chat)
        return
    if command == "/signal":
        symbol = arg.upper()
        key = engine.keys.get(symbol)
        if not key:
            await telegram.send(f"Symbol not resolved: {symbol}", chat)
            return
        result = await engine.scan_symbol(symbol, key, "CORE")
        await telegram.send(str(result.as_dict() if result else "No qualified closed-candle signal."), chat)
        return
    if command == "/why":
        symbol = arg.upper()
        matches = [item for item in engine.signals if item["symbol"] == symbol]
        await telegram.send(str(matches[-1] if matches else {"symbol": symbol, "reason": "No recent signal stored; check /status and rejection counts."}), chat)
        return
    if command == "/explode":
        await telegram.send(
            f"Configured explosion symbols: {len(engine.explosion_keys)}. "
            "This is a curated scan universe, not a verified 20-session turnover ranking.",
            chat,
        )
        return
    if command == "/oc":
        symbol = arg.upper()
        key = engine.keys.get(symbol)
        if not key:
            await telegram.send("Symbol not resolved", chat)
            return
        try:
            rows = await rest.option_chain(key, "current_week")
            from engines.option_chain import assess_chain
            await telegram.send(str(assess_chain(rows, "LONG")), chat)
        except Exception as exc:
            await telegram.send(f"Option chain unavailable: {type(exc).__name__}", chat)
        return
    if command == "/settoken":
        if not arg:
            await telegram.send("Usage: /settoken YOUR_UPSTOX_ACCESS_TOKEN", chat)
            return
        rest.token = arg
        rest.client.headers["Authorization"] = f"Bearer {arg}"
        await telegram.send(
            "Token updated in memory only. Set UPSTOX_ACCESS_TOKEN in Render to persist it across restarts.",
            chat,
        )
        return
    if command in {"/settings", "/stats"}:
        await telegram.send(str({
            "min_score": settings.min_score,
            "explosion_min_score": settings.explosion_min_score,
            "signal_only": True,
            "rejects": engine.rejections,
        }), chat)
        return
    await telegram.send("Unknown command. Use /help", chat)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rest, resolver, telegram, engine, tasks
    log.info("Starting NSE F&O signal engine (signal-only)")
    for warning in settings.validate_deployment():
        log.warning(warning)
    rest = UpstoxREST(settings.upstox_access_token)
    resolver = InstrumentResolver(rest)
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id, settings.telegram_admin_ids)
    engine = SignalEngine(settings, rest, resolver, telegram, calendar)
    if settings.upstox_access_token:
        try:
            await engine.initialize()
        except Exception:
            log.exception("Instrument initialization failed")
    # Verify Telegram token and destination at every deploy. This sends one
    # explicit startup test so delivery failures are visible before a market signal.
    await telegram.startup_check()
    # Signal-delivery-only mode: do not poll Telegram getUpdates.
    # Telegram remains enabled for outbound signal notifications via sendMessage.
    if settings.upstox_access_token:
        tasks.append(asyncio.create_task(engine.run_loop(), name="signal-loop"))
    yield
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if telegram:
        await telegram.close()
    if rest:
        await rest.close()


app = FastAPI(title="NSE F&O Signal Engine", version="1.0.0", lifespan=lifespan)


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"service": "nse-fno-signal-engine", "status": "ok", "signal_only": True, "engine_version": "1.0.0"}


@app.get("/ping")
async def ping():
    return {
        "status": "ok", "time_ist": now_ist().isoformat(),
        "market_open": calendar.is_market_open(),
        "market_data_transport": "rest_closed_candle_polling",
        "websocket_enabled": False,
        "ws_connected": False,
        "websocket_note": "WebSocket is not implemented/enabled; false is intentional.",
        "rest_polling_configured": bool(settings.upstox_access_token),
        "last_scan_started": engine.last_scan_started if engine else None,
        "last_scan_completed": engine.last_scan_completed if engine else None,
        "scan_in_progress": engine.scan_in_progress if engine else False,
        "last_data_fetch": engine.last_data_fetch if engine else None,
    }


@app.get("/health")
async def health():
    warnings = list(settings.validate_deployment())
    state = engine.status() if engine else {}
    configured = bool(settings.upstox_access_token and settings.telegram_bot_token and settings.telegram_chat_id and settings.telegram_admin_ids)
    return JSONResponse({
        "status": "ok" if configured else "degraded",
        "started_at_ist": started_at.isoformat(),
        "warnings": warnings,
        "engine": state,
        "components": {
            "upstox_rest": "configured" if settings.upstox_access_token else "missing_token",
            "market_data_transport": "rest_closed_candle_polling",
            "upstox_websocket": "disabled_not_connected",
            "websocket_enabled": False,
            "telegram": "configured" if settings.telegram_bot_token and settings.telegram_chat_id else "incomplete",
            "telegram_delivery": telegram.status() if telegram else {},
            "telegram_admin": "configured" if settings.telegram_admin_ids else "missing_admin_id",
            "explosion_universe": "configured" if engine and engine.explosion_keys else "empty_or_not_resolved",
        },
    })


@app.get("/status")
async def status():
    return engine.status() if engine else {"status": "starting"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
