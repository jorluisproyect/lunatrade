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
import re
import unicodedata

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

from .database import (
    add_event, init_db, recent_events, recent_trades, get_runtime_setting, set_runtime_setting,
    username_exists, referral_exists, create_demo_user_record, get_demo_user_by_username,
    get_demo_user_by_id, list_demo_users, touch_demo_login, update_demo_mode, update_demo_bot,
    update_demo_password,
)  # noqa: E402
from .binance_testnet import binance_testnet_monitor, check_binance_testnet, testnet_auto_loop  # noqa: E402
from .market import market_stream  # noqa: E402
from .simulator import simulation_loop  # noqa: E402
from .state import state  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

CLOUD_MODE = os.getenv("CLOUD_MODE", "false").lower() == "true"

# V9.2: login local robusto.
# Si el proyecto corre realmente en Railway usamos las variables privadas del servidor.
# Si corre en tu PC, usamos siempre la clave local, aunque un .env antiguo conserve CLOUD_MODE=true.
LOCAL_ACCESS_PASSWORD = "LunaTrade-9146!"
LOCAL_SESSION_SECRET = "lunatrade-local-only-9f3a7c2e6b184d5aa1c0e2f4b6d8a0c7"
RUNNING_ON_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
    or os.getenv("RAILWAY_SERVICE_ID")
)

if RUNNING_ON_RAILWAY:
    ACCESS_PASSWORD = os.getenv("LUNATRADE_ACCESS_PASSWORD", "").strip()
    SESSION_SECRET = os.getenv("LUNATRADE_SESSION_SECRET", "").strip()
else:
    ACCESS_PASSWORD = LOCAL_ACCESS_PASSWORD
    SESSION_SECRET = LOCAL_SESSION_SECRET
SESSION_COOKIE = "lunatrade_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30


def _auth_required() -> bool:
    return CLOUD_MODE or bool(ACCESS_PASSWORD)


def _auth_ready() -> bool:
    return bool(ACCESS_PASSWORD and len(SESSION_SECRET) >= 32)


def _password_hash(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 220_000)
    return salt.hex(), digest.hex()


def _verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    _, actual = _password_hash(password, salt_hex)
    return hmac.compare_digest(actual, expected_hex)


def _make_session_token(*, role: str = "admin", user_id: int = 0) -> str:
    exp = int(time.time()) + SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(12)
    payload = f"{exp}:{nonce}:{role}:{user_id}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _session_info(token: str | None) -> dict | None:
    if not token or not _auth_ready():
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        exp_s, nonce, role, user_id_s, sig = raw.split(":", 4)
        payload = f"{exp_s}:{nonce}:{role}:{user_id_s}"
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(exp_s) <= int(time.time()):
            return None
        info = {"role": role, "user_id": int(user_id_s), "exp": int(exp_s)}
        if role == "demo":
            user = get_demo_user_by_id(info["user_id"])
            if not user or not user.get("is_active"):
                return None
        return info
    except Exception:
        return None


def _valid_session_token(token: str | None) -> bool:
    return _session_info(token) is not None


def _current_session(request: Request) -> dict | None:
    return _session_info(request.cookies.get(SESSION_COOKIE))


def _require_http_auth(request: Request) -> dict:
    if not _auth_required():
        return {"role": "admin", "user_id": 0}
    if not _auth_ready():
        raise HTTPException(status_code=503, detail="Seguridad cloud pendiente: configura LUNATRADE_ACCESS_PASSWORD y LUNATRADE_SESSION_SECRET.")
    info = _current_session(request)
    if not info:
        raise HTTPException(status_code=401, detail="Inicia sesión en LunaTrade.")
    return info


def _require_admin(request: Request) -> dict:
    info = _require_http_auth(request)
    if info.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para el administrador de LunaTrade.")
    return info


def _slug_name(name: str) -> str:
    raw = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    raw = re.sub(r"[^a-z0-9]+", "", raw.split()[0] if raw.split() else raw)
    return raw[:12] or "usuario"


def _generate_demo_credentials(display_name: str) -> tuple[str, str, str]:
    base = _slug_name(display_name)
    words = ["Luna", "Sol", "Rio", "Nube", "Nova", "Atlas", "Zen", "Oro", "Mar", "Vega"]
    for _ in range(50):
        digits = f"{secrets.randbelow(10000):04d}"
        username = f"luna.{base}.{digits}"
        referral = f"LT-{base.upper()[:8]}-{digits}"
        if not username_exists(username) and not referral_exists(referral):
            password = f"{secrets.choice(words)}-{secrets.choice(words)}-{digits}-{secrets.token_hex(1).upper()}!"
            return username, password, referral
    raise RuntimeError("No se pudo generar un usuario único.")

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
    add_event("info", "LunaTrade V12 iniciado", "Admin Testnet + usuarios demo + referidos + PWA. Fondos virtuales solamente.")
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


app = FastAPI(title="LunaTrade V12 Users PWA", version="12.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoginRequest(BaseModel):
    username: str = Field(default="admin", min_length=0, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CreateDemoUserRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)


class DemoModeRequest(BaseModel):
    mode: str = Field(pattern="^(trading|arbitrage)$")


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
    return {"ok": True, "service": "LunaTrade V12", "mode": "TESTNET_AND_DEMO", "cloud": CLOUD_MODE}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    required = _auth_required()
    ready = _auth_ready()
    info = _current_session(request) if ready else None
    authenticated = (not required) or bool(info)
    payload = {
        "required": required, "ready": ready, "authenticated": authenticated,
        "mode": "railway" if RUNNING_ON_RAILWAY else "local", "version": "12.0",
        "role": (info or {}).get("role", "admin" if not required else None),
    }
    if info and info.get("role") == "demo":
        user = get_demo_user_by_id(info["user_id"])
        if user:
            payload["user"] = {"display_name": user["display_name"], "username": user["username"], "referral_code": user["referral_code"]}
    return payload


@app.post("/api/login")
async def login(req: LoginRequest, request: Request, response: Response):
    if not _auth_required():
        return {"ok": True, "authenticated": True, "role": "admin"}
    if not _auth_ready():
        raise HTTPException(status_code=503, detail="Configura la contraseña y el secreto de sesión en el servidor.")

    username = (req.username or "admin").strip()
    role, user_id = None, 0
    if username.lower() in {"admin", "jorge", "owner", ""} and hmac.compare_digest(req.password, ACCESS_PASSWORD):
        role = "admin"
    else:
        user = get_demo_user_by_username(username)
        if user and user.get("is_active") and _verify_password(req.password, user["password_salt"], user["password_hash"]):
            role, user_id = "demo", int(user["id"])
            touch_demo_login(user_id)
    if not role:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    secure_cookie = CLOUD_MODE or request.headers.get("x-forwarded-proto", "").lower() == "https"
    response.set_cookie(
        SESSION_COOKIE, _make_session_token(role=role, user_id=user_id), max_age=SESSION_TTL_SECONDS,
        httponly=True, secure=secure_cookie, samesite="lax", path="/"
    )
    return {"ok": True, "authenticated": True, "role": role}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/admin/users")
async def admin_users(request: Request):
    _require_admin(request)
    return {"users": list_demo_users()}


@app.post("/api/admin/users")
async def admin_create_user(req: CreateDemoUserRequest, request: Request):
    _require_admin(request)
    username, plain_password, referral = _generate_demo_credentials(req.display_name.strip())
    salt, digest = _password_hash(plain_password)
    user = create_demo_user_record(
        display_name=req.display_name.strip(), username=username, password_salt=salt, password_hash=digest,
        referral_code=referral, referrer_code="JORGE-LT", demo_balance=100.0
    )
    add_event("success", "Usuario demo creado", f"{user['display_name']} · {username} · 100 USDT demo")
    return {
        "ok": True,
        "credentials": {"display_name": user["display_name"], "username": username, "password": plain_password, "referral_code": referral},
        "demo_balance": 100.0,
    }


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(user_id: int, request: Request):
    _require_admin(request)
    user = get_demo_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    _, plain_password, _ = _generate_demo_credentials(user["display_name"])
    salt, digest = _password_hash(plain_password)
    update_demo_password(user_id, salt, digest)
    return {"ok": True, "username": user["username"], "password": plain_password}


@app.get("/api/demo/status")
async def demo_status(request: Request):
    info = _require_http_auth(request)
    if info.get("role") != "demo":
        raise HTTPException(status_code=403, detail="Esta vista es para usuarios demo.")
    user = get_demo_user_by_id(info["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="Usuario demo no encontrado.")
    return {
        "user": {
            "display_name": user["display_name"], "username": user["username"], "referral_code": user["referral_code"],
            "balance": user["demo_balance"], "pnl": user["demo_pnl"], "mode": user["selected_mode"],
            "bot_running": bool(user["demo_bot_running"]),
        },
        "market": {"symbol": state.symbol, "price": state.price or state.testnet_price},
        "demo": True, "message": "Fondos demo. No es dinero real.",
    }


@app.post("/api/demo/mode")
async def demo_mode(req: DemoModeRequest, request: Request):
    info = _require_http_auth(request)
    if info.get("role") != "demo":
        raise HTTPException(status_code=403, detail="Solo disponible para usuarios demo.")
    update_demo_mode(info["user_id"], req.mode)
    return await demo_status(request)


@app.post("/api/demo/bot/toggle")
async def demo_bot_toggle(req: ToggleRequest, request: Request):
    info = _require_http_auth(request)
    if info.get("role") != "demo":
        raise HTTPException(status_code=403, detail="Solo disponible para usuarios demo.")
    update_demo_bot(info["user_id"], req.enabled)
    return await demo_status(request)


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
    _require_admin(request)
    payload = state.snapshot(); payload["trades"] = recent_trades(10); payload["events"] = recent_events(10)
    return payload


@app.post("/api/binance-testnet/check")
async def binance_testnet_check(request: Request):
    _require_admin(request)
    await check_binance_testnet(log_event=True)
    return state.snapshot()


@app.post("/api/testnet-auto/toggle")
async def testnet_auto_toggle(req: ToggleRequest, request: Request):
    _require_admin(request)
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
    _require_admin(request)
    if state.testnet_auto_position:
        raise HTTPException(status_code=400, detail="No cambies el capital asignado con una posición abierta.")
    state.testnet_assigned_capital = req.assigned_capital
    set_runtime_setting("testnet_assigned_capital", str(req.assigned_capital))
    add_event("info", "Capital AUTO TESTNET actualizado", f"{req.assigned_capital:.2f} USDT virtuales asignados.")
    return state.snapshot()


@app.post("/api/bot/toggle")
async def bot_toggle(req: ToggleRequest, request: Request):
    _require_admin(request)
    state.bot_enabled = req.enabled
    return state.snapshot()


@app.post("/api/sim/deposit")
async def sim_deposit(req: AmountRequest, request: Request):
    _require_admin(request)
    state.cash += req.amount; state.total_deposits += req.amount
    return state.snapshot()


@app.post("/api/sim/withdraw")
async def sim_withdraw(req: AmountRequest, request: Request):
    _require_admin(request)
    if req.amount > state.reserve:
        raise HTTPException(status_code=400, detail="Solo puedes retirar de la reserva PAPER.")
    state.reserve -= req.amount; state.total_withdrawals += req.amount
    return state.snapshot()


@app.post("/api/settings")
async def update_settings(req: SettingsRequest, request: Request):
    _require_admin(request)
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
        info = _session_info(ws.cookies.get(SESSION_COOKIE)) if _auth_ready() else None
        if not info or info.get("role") != "admin":
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
