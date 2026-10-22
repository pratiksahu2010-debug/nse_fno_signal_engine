"""NSE F&O signal-only service: FastAPI health endpoints, signal engine, Telegram polling."""
from __future__ import annotations
import asyncio,logging,os
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
settings=Settings.from_env();configure_logging(settings.log_level);log=logging.getLogger(__name__)
calendar=MarketCalendar();started_at=now_ist();rest=None;resolver=None;telegram=None;engine=None;tasks=[]
async def command_handler(message):
    global engine,telegram
    text=str(message.get("text","")).strip();chat=message.get("chat",{}).get("id");uid=message.get("from",{}).get("id")
    if not text.startswith("/"):return
    cmd=text.split()[0].split("@")[0].lower();arg=text.split(maxsplit=1)[1] if len(text.split(maxsplit=1))>1 else ""
    if cmd in {"/start","/help"}:
        await telegram.send("NSE F&O signal-only bot\n/status /scan /signal SYMBOL /pending /today /watchlist /why SYMBOL /pause /resume /settoken TOKEN (admin only)\nNo automatic orders are placed.",chat);return
    if cmd=="/status":await telegram.send(str(engine.status() if engine else {"status":"starting"}),chat);return
    if cmd=="/scan":await telegram.send(str(await engine.scan(limit=30)),chat);return
    if cmd=="/pending":await telegram.send("\n".join(f"{c.symbol} {c.direction} {c.status} entry={c.entry_low:.2f}-{c.entry_high:.2f} SL={c.stop:.2f} T1={c.t1:.2f} T2={c.t2:.2f}" for c in engine.candidates.values() if c.status=="PENDING") or "No pending candidates.",chat);return
    if cmd=="/today":await telegram.send(f"Signals today: {len(engine.signals)}\n"+"\n".join(f"{s['time']} {s['symbol']} {s['direction']} {s['score']}" for s in engine.signals[-20:]),chat);return
    if cmd=="/watchlist":await telegram.send(", ".join(engine.keys) or "No symbols resolved yet",chat);return
    if cmd=="/pause":engine.paused=True;await telegram.send("Signal scanning paused.",chat);return
    if cmd=="/resume":engine.paused=False;await telegram.send("Signal scanning resumed.",chat);return
    if cmd=="/signal":
        sym=arg.upper();key=engine.keys.get(sym)
        if not key:await telegram.send(f"Symbol not resolved: {sym}",chat);return
        res=await engine.scan_symbol(sym,key,"CORE");await telegram.send(str(res.as_dict() if res else "No qualified closed-candle signal."),chat);return
    if cmd=="/why":
        sym=arg.upper();s=[x for x in engine.signals if x["symbol"]==sym]
        await telegram.send(str(s[-1] if s else {"symbol":sym,"reason":"No recent signal stored; check /status and rejection counts."}),chat);return
    if cmd=="/explode":await telegram.send("Explosion universe is disabled until a verified 20-session median turnover ranking is available. Set config/explosion_universe.json to a manually verified symbol list.",chat);return
    if cmd=="/oc":
        sym=arg.upper();key=engine.keys.get(sym)
        if not key:await telegram.send("Symbol not resolved",chat);return
        try:
            rows=await rest.option_chain(key,"current_week");from engines.option_chain import assess_chain
            await telegram.send(str(assess_chain(rows,"LONG")),chat)
        except Exception as e:await telegram.send(f"Option chain unavailable: {e}",chat)
        return
    if cmd=="/settoken":
        if uid not in settings.telegram_admin_ids:await telegram.send("Admin only.",chat);return
        if not arg:await telegram.send("Usage: /settoken YOUR_UPSTOX_ACCESS_TOKEN",chat);return
        # In-memory token rotation only; environment is not persisted on Render.
        rest.token=arg;rest.client.headers["Authorization"]=f"Bearer {arg}";await telegram.send("Token updated in memory. It will be lost on restart; set UPSTOX_ACCESS_TOKEN in Render for persistent deployment configuration.",chat);return
    if cmd in {"/settings","/stats"}:await telegram.send(str({"min_score":settings.min_score,"explosion_min_score":settings.explosion_min_score,"signal_only":True,"rejects":engine.rejections}),chat);return
    await telegram.send("Unknown command. Use /help",chat)

@asynccontextmanager
async def lifespan(app:FastAPI):
    global rest,resolver,telegram,engine,tasks
    log.info("Starting NSE F&O signal engine (signal-only)")
    for w in settings.validate_deployment():log.warning(w)
    rest=UpstoxREST(settings.upstox_access_token) if settings.upstox_access_token else UpstoxREST("")
    resolver=InstrumentResolver(rest);telegram=TelegramService(settings.telegram_bot_token,settings.telegram_chat_id,settings.telegram_admin_ids)
    engine=SignalEngine(settings,rest,resolver,telegram,calendar)
    if settings.upstox_access_token:
        try:await engine.initialize()
        except Exception:log.exception("Instrument initialization failed")
    if settings.telegram_bot_token:tasks.append(asyncio.create_task(telegram.poll(command_handler),name="telegram-poll"))
    # Polling loop can run when credentials are present; no calls/orders are made outside market hours.
    if settings.upstox_access_token:tasks.append(asyncio.create_task(engine.run_loop(),name="signal-loop"))
    yield
    for t in tasks:t.cancel()
    if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    if telegram:await telegram.close()
    if rest:await rest.close()

app=FastAPI(title="NSE F&O Signal Engine",version="1.0.0",lifespan=lifespan)
@app.api_route("/", methods=["GET", "HEAD"])
async def root():return {"service":"nse-fno-signal-engine","status":"ok","signal_only":True,"engine_version":"1.0.0"}
@app.get("/ping")
async def ping():return {"status":"ok","time_ist":now_ist().isoformat(),"market_open":calendar.is_market_open(),"ws_connected":False,"transport":"rest_closed_candle_polling","last_tick_age_sec":None}
@app.get("/health")
async def health():
    warnings=list(settings.validate_deployment()); st=engine.status() if engine else {}
    return JSONResponse({"status":"ok" if settings.upstox_access_token and settings.telegram_bot_token else "degraded","started_at_ist":started_at.isoformat(),"warnings":warnings,"engine":st,"components":{"upstox_rest":"configured" if settings.upstox_access_token else "missing_token","upstox_websocket":"not_enabled_protobuf_decoder_required","telegram":"configured" if settings.telegram_bot_token else "disabled"}})
@app.get("/status")
async def status():return engine.status() if engine else {"status":"starting"}
if __name__=="__main__":
    import uvicorn;uvicorn.run("main:app",host=settings.host,port=settings.port,reload=False)
