from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

from .database import add_event, init_db, recent_events, recent_trades, get_runtime_setting, set_runtime_setting  # noqa: E402
from .binance_testnet import binance_testnet_monitor, check_binance_testnet, testnet_auto_loop  # noqa: E402
from .market import market_stream  # noqa: E402
from .simulator import simulation_loop  # noqa: E402
from .state import state  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

CLOUD_MODE = os.getenv("CLOUD_MODE", "false").lower() == "true"
ACCESS_PASSWORD = os.getenv("LUNATRADE_ACCESS_PASSWORD", "").strip()
SESSION_SECRET = os.getenv("LUNATRADE_SESSION_SECRET", "").strip()
SESSION_COOKIE = "lunatrade_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30


def _auth_required() -> bool:
    return CLOUD_MODE or bool(ACCESS_PASSWORD)


def _auth_ready() -> bool:
    return bool(ACCESS_PASSWORD and len(SESSION_SECRET) >= 32)


def _make_session_token() -> str:
    exp = int(time.time()) + SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(12)
    payload = f"{exp}:{nonce}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _valid_session_token(token: str | None) -> bool:
    if not token or not _auth_ready():
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        exp_s, nonce, sig = raw.split(":", 2)
        payload = f"{exp_s}:{nonce}"
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected) and int(exp_s) > int(time.time())
    except Exception:
        return False


def _require_http_auth(request: Request) -> None:
    if not _auth_required():
        return
    if not _auth_ready():
        raise HTTPException(status_code=503, detail="Seguridad cloud pendiente: configura LUNATRADE_ACCESS_PASSWORD y LUNATRADE_SESSION_SECRET.")
    if not _valid_session_token(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Inicia sesión en LunaTrade.")


def _load_persisted_runtime() -> None:
    """Restaura la configuración operativa TESTNET al reiniciar LunaTrade.

    Solo aplica al entorno virtual. La futura versión REAL exigirá confirmación explícita
    y reglas de seguridad adicionales.
    """
    try:
        default_capital = os.getenv("TESTNET_ASSIGNED_CAPITAL", "100")
        default_auto = os.getenv("TESTNET_AUTOTRADE", "false")
        state.testnet_assigned_capital = float(get_runtime_setting("testnet_assigned_capital", default_capital) or default_capital)
        state.testnet_auto_enabled = (get_runtime_setting("testnet_auto_enabled", default_auto) or default_auto).lower() == "true"
        state.reinvest_pct = float(get_runtime_setting("reinvest_pct", str(state.reinvest_pct)) or state.reinvest_pct)
        state.max_daily_loss_pct = float(get_runtime_setting("max_daily_loss_pct", str(state.max_daily_loss_pct)) or state.max_daily_loss_pct)
        state.max_position_pct = float(get_runtime_setting("max_position_pct", str(state.max_position_pct)) or state.max_position_pct)
        raw_position = get_runtime_setting("testnet_auto_position", "") or ""
        if raw_position:
            state.testnet_auto_position = json.loads(raw_position)
    except Exception as exc:
        state.testnet_auto_enabled = False
        state.testnet_auto_position = None
        add_event("warning", "Configuración recuperada parcialmente", f"{type(exc).__name__}: se inició en modo seguro/pausado.")


def _persist_auto_position() -> None:
    set_runtime_setting("testnet_auto_position", json.dumps(state.testnet_auto_position) if state.testnet_auto_position else "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _load_persisted_runtime()
    add_event("info", "LunaTrade V8 Cloud iniciado", "AUTO Binance Spot Testnet + PWA + acceso protegido. Fondos virtuales solamente.")
    tasks = [
        asyncio.create_task(market_stream()),
        asyncio.create_task(simulation_loop()),
        asyncio.create_task(binance_testnet_monitor()),
        asyncio.create_task(testnet_auto_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="LunaTrade V8 Cloud Testnet", version="0.8.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ToggleRequest(BaseModel):
    enabled: bool


class AmountRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class TestnetAutoSettings(BaseModel):
    assigned_capital: float = Field(ge=5.0, le=1000.0)


class SettingsRequest(BaseModel):
    reinvest_pct: float = Field(ge=0, le=1)
    max_daily_loss_pct: float = Field(ge=0.001, le=0.10)
    max_position_pct: float = Field(ge=0.01, le=1)


@app.get("/")
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "LunaTrade V8", "mode": "TESTNET_ONLY"}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    required = _auth_required()
    ready = _auth_ready()
    authenticated = (not required) or _valid_session_token(request.cookies.get(SESSION_COOKIE))
    return {"required": required, "ready": ready, "authenticated": authenticated}


@app.post("/api/login")
async def login(req: LoginRequest, request: Request, response: Response):
    if not _auth_required():
        return {"ok": True, "authenticated": True}
    if not _auth_ready():
        raise HTTPException(status_code=503, detail="Configura la contraseña y el secreto de sesión en el servidor.")
    if not hmac.compare_digest(req.password, ACCESS_PASSWORD):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")
    secure_cookie = CLOUD_MODE or request.headers.get("x-forwarded-proto", "").lower() == "https"
    response.set_cookie(
        SESSION_COOKIE, _make_session_token(), max_age=SESSION_TTL_SECONDS,
        httponly=True, secure=secure_cookie, samesite="lax", path="/"
    )
    return {"ok": True, "authenticated": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/service-worker.js")
async def service_worker():
    return FileResponse(
        STATIC_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/status")
async def status(request: Request):
    _require_http_auth(request)
    payload = state.snapshot(); payload["trades"] = recent_trades(10); payload["events"] = recent_events(10)
    return payload


@app.post("/api/binance-testnet/check")
async def binance_testnet_check(request: Request):
    _require_http_auth(request)
    await check_binance_testnet(log_event=True)
    return state.snapshot()


@app.post("/api/testnet-auto/toggle")
async def testnet_auto_toggle(req: ToggleRequest, request: Request):
    _require_http_auth(request)
    if req.enabled:
        ok = await check_binance_testnet(log_event=False)
        if not ok:
            raise HTTPException(status_code=400, detail=state.binance_testnet_message)
        if state.testnet_assigned_capital < 5:
            raise HTTPException(status_code=400, detail="Asigna al menos 5 USDT virtuales al bot.")
        state.testnet_auto_enabled = True
        state.testnet_auto_pause_reason = ""
        set_runtime_setting("testnet_auto_enabled", "true")
        add_event("success", "AUTO TESTNET activado", f"Capital asignado: {state.testnet_assigned_capital:.2f} USDT virtuales. LunaTrade decide cuándo entrar/salir.")
    else:
        state.testnet_auto_enabled = False
        set_runtime_setting("testnet_auto_enabled", "false")
        add_event("warning", "AUTO TESTNET pausado", "No se abrirán nuevas operaciones automáticas.")
    return state.snapshot()


@app.post("/api/testnet-auto/settings")
async def testnet_auto_settings(req: TestnetAutoSettings, request: Request):
    _require_http_auth(request)
    if state.testnet_auto_position:
        raise HTTPException(status_code=400, detail="No cambies el capital asignado con una posición abierta.")
    state.testnet_assigned_capital = req.assigned_capital
    set_runtime_setting("testnet_assigned_capital", str(req.assigned_capital))
    add_event("info", "Capital AUTO TESTNET actualizado", f"{req.assigned_capital:.2f} USDT virtuales asignados.")
    return state.snapshot()


@app.post("/api/bot/toggle")
async def bot_toggle(req: ToggleRequest, request: Request):
    _require_http_auth(request)
    state.bot_enabled = req.enabled
    return state.snapshot()


@app.post("/api/sim/deposit")
async def sim_deposit(req: AmountRequest, request: Request):
    _require_http_auth(request)
    state.cash += req.amount; state.total_deposits += req.amount
    return state.snapshot()


@app.post("/api/sim/withdraw")
async def sim_withdraw(req: AmountRequest, request: Request):
    _require_http_auth(request)
    if req.amount > state.reserve:
        raise HTTPException(status_code=400, detail="Solo puedes retirar de la reserva PAPER.")
    state.reserve -= req.amount; state.total_withdrawals += req.amount
    return state.snapshot()


@app.post("/api/settings")
async def update_settings(req: SettingsRequest, request: Request):
    _require_http_auth(request)
    state.reinvest_pct = req.reinvest_pct
    state.max_daily_loss_pct = req.max_daily_loss_pct
    state.max_position_pct = req.max_position_pct
    set_runtime_setting("reinvest_pct", str(req.reinvest_pct))
    set_runtime_setting("max_daily_loss_pct", str(req.max_daily_loss_pct))
    set_runtime_setting("max_position_pct", str(req.max_position_pct))
    add_event("info", "Configuración actualizada", "Riesgo actualizado para esta sesión.")
    return state.snapshot()


@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    if _auth_required():
        if not _auth_ready() or not _valid_session_token(ws.cookies.get(SESSION_COOKIE)):
            await ws.close(code=4401)
            return
    await ws.accept()
    try:
        while True:
            payload = state.snapshot(); payload["trades"] = recent_trades(8); payload["events"] = recent_events(8)
            await ws.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
