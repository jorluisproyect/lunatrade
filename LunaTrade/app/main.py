from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from .database import add_event, init_db, recent_events, recent_trades  # noqa: E402
from .market import market_stream  # noqa: E402
from .simulator import simulation_loop  # noqa: E402
from .state import state  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    add_event("info", "LunaTrade iniciado", "Modo PAPER. No hay dinero real conectado.")
    market_task = asyncio.create_task(market_stream())
    sim_task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        market_task.cancel()
        sim_task.cancel()
        await asyncio.gather(market_task, sim_task, return_exceptions=True)


app = FastAPI(title="LunaTrade V1", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ToggleRequest(BaseModel):
    enabled: bool


class AmountRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class SettingsRequest(BaseModel):
    reinvest_pct: float = Field(ge=0, le=1)
    max_daily_loss_pct: float = Field(ge=0.001, le=0.10)
    max_position_pct: float = Field(ge=0.01, le=1)


@app.get("/")
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    payload = state.snapshot()
    payload["trades"] = recent_trades(10)
    payload["events"] = recent_events(10)
    return payload


@app.post("/api/bot/toggle")
async def bot_toggle(req: ToggleRequest):
    state.bot_enabled = req.enabled
    if req.enabled:
        state.bot_pause_reason = ""
        add_event("success", "Bot PAPER activado", "LunaTrade puede abrir operaciones simuladas.")
    else:
        add_event("warning", "Bot PAPER pausado", "No se abriran nuevas operaciones simuladas.")
    return state.snapshot()


@app.post("/api/sim/deposit")
async def sim_deposit(req: AmountRequest):
    state.cash += req.amount
    state.total_deposits += req.amount
    add_event("success", "Deposito simulado", f"+{req.amount:.2f} USDT PAPER agregado.")
    return state.snapshot()


@app.post("/api/sim/withdraw")
async def sim_withdraw(req: AmountRequest):
    if req.amount > state.reserve:
        raise HTTPException(status_code=400, detail="Solo puedes retirar de la reserva PAPER en esta V1.")
    state.reserve -= req.amount
    state.total_withdrawals += req.amount
    add_event("success", "Retiro simulado", f"-{req.amount:.2f} USDT PAPER retirado de la reserva.")
    return state.snapshot()


@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    state.reinvest_pct = req.reinvest_pct
    state.max_daily_loss_pct = req.max_daily_loss_pct
    state.max_position_pct = req.max_position_pct
    add_event("info", "Configuracion actualizada", "Ajustes PAPER guardados para esta sesion.")
    return state.snapshot()


@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = state.snapshot()
            payload["trades"] = recent_trades(8)
            payload["events"] = recent_events(8)
            await ws.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
