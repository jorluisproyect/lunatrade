from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from dotenv import load_dotenv

from .database import add_event, add_trade, set_runtime_setting
from .state import state

# HARD SAFETY RULE: V6.3 habla SOLAMENTE con Binance Spot Testnet.
BASE_URL = "https://testnet.binance.vision"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _credentials() -> tuple[str, str]:
    # Recarga SIEMPRE el .env de C:\Proyectos\LunaTrade para evitar
    # credenciales antiguas heredadas por el proceso/reloader de Uvicorn.
    load_dotenv(dotenv_path=ENV_FILE, override=True)
    return (
        os.getenv("BINANCE_TESTNET_API_KEY", "").strip(),
        os.getenv("BINANCE_TESTNET_SECRET_KEY", "").strip(),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_json(path: str, *, api_key: str | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method)
    if api_key:
        req.add_header("X-MBX-APIKEY", api_key)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _server_time_ms() -> int:
    return int(_request_json("/api/v3/time")["serverTime"])


def _sign_params(secret: str, params: dict) -> str:
    query = urllib.parse.urlencode(params)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def _signed_request(path: str, api_key: str, secret: str, params: dict | None = None, *, method: str = "GET") -> dict:
    payload = dict(params or {})
    payload.setdefault("recvWindow", 5000)
    payload["timestamp"] = _server_time_ms()
    query = _sign_params(secret, payload)
    return _request_json(f"{path}?{query}", api_key=api_key, method=method)


def _signed_account_request(api_key: str, secret: str) -> dict:
    return _signed_request("/api/v3/account", api_key, secret, {"omitZeroBalances": "true"})


def _extract_balances(account: dict) -> dict:
    wanted = {"USDT", "BTC", "ETH", "BNB"}
    result = {}
    for item in account.get("balances", []):
        asset = item.get("asset", "")
        free = float(item.get("free", 0) or 0)
        locked = float(item.get("locked", 0) or 0)
        if asset in wanted or free > 0 or locked > 0:
            result[asset] = {"free": free, "locked": locked, "total": free + locked}
    return result


def _ticker_price(symbol: str) -> float:
    data = _request_json(f"/api/v3/ticker/price?symbol={urllib.parse.quote(symbol)}")
    return float(data["price"])


def _symbol_info(symbol: str) -> dict:
    data = _request_json(f"/api/v3/exchangeInfo?symbol={urllib.parse.quote(symbol)}")
    symbols = data.get("symbols") or []
    if not symbols:
        raise RuntimeError(f"No se encontró información para {symbol}")
    return symbols[0]


def _lot_rules(symbol: str) -> tuple[Decimal, Decimal, Decimal]:
    info = _symbol_info(symbol)
    for f in info.get("filters", []):
        if f.get("filterType") == "LOT_SIZE":
            return Decimal(str(f["minQty"])), Decimal(str(f["maxQty"])), Decimal(str(f["stepSize"]))
    raise RuntimeError("Binance no devolvió LOT_SIZE")


def _floor_step(value: float | Decimal, step: Decimal) -> Decimal:
    d = Decimal(str(value))
    if step <= 0:
        return d
    return (d / step).to_integral_value(rounding=ROUND_DOWN) * step


def _format_decimal(value: Decimal) -> str:
    s = format(value, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _avg_price(order: dict) -> float:
    qty = float(order.get("executedQty", 0) or 0)
    quote = float(order.get("cummulativeQuoteQty", 0) or 0)
    return quote / qty if qty > 0 else 0.0


def _market_buy_quote(api_key: str, secret: str, symbol: str, quote_usdt: float) -> dict:
    params = {
        "symbol": symbol, "side": "BUY", "type": "MARKET",
        "quoteOrderQty": f"{quote_usdt:.8f}", "newOrderRespType": "FULL",
    }
    return _signed_request("/api/v3/order", api_key, secret, params, method="POST")


def _market_sell_qty(api_key: str, secret: str, symbol: str, qty: Decimal) -> dict:
    params = {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": _format_decimal(qty), "newOrderRespType": "FULL",
    }
    return _signed_request("/api/v3/order", api_key, secret, params, method="POST")


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    value = sum(values[:period]) / period
    for p in values[period:]:
        value = p * k + value * (1 - k)
    return value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(max(x, 0) for x in recent) / period
    losses = sum(abs(min(x, 0)) for x in recent) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


async def check_binance_testnet(*, log_event: bool = True) -> bool:
    api_key, secret = _credentials()
    state.binance_testnet_configured = bool(api_key and secret)
    if not state.binance_testnet_configured:
        state.binance_testnet_connected = False
        state.binance_testnet_message = "Agrega API Key y Secret del Spot Testnet en .env"
        return False
    try:
        account = await asyncio.to_thread(_signed_account_request, api_key, secret)
        state.binance_testnet_connected = True
        state.binance_testnet_message = "Binance Spot Testnet conectado"
        state.binance_testnet_balances = _extract_balances(account)
        state.binance_testnet_last_sync = _utc_now()
        if log_event:
            usdt = state.binance_testnet_balances.get("USDT", {}).get("total", 0)
            add_event("success", "Binance Testnet conectado", f"USDT virtual: {usdt:.4f}")
        return True
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8")); msg = body.get("msg") or f"HTTP {exc.code}"
        except Exception:
            msg = f"HTTP {exc.code}"
        state.binance_testnet_connected = False
        state.binance_testnet_message = f"Error Binance Testnet: {msg}"
        if log_event: add_event("warning", "Binance Testnet no validado", msg)
        return False
    except Exception as exc:
        state.binance_testnet_connected = False
        state.binance_testnet_message = f"No se pudo conectar: {type(exc).__name__}"
        if log_event: add_event("warning", "Binance Testnet sin conexión", type(exc).__name__)
        return False


async def _open_auto_position() -> None:
    api_key, secret = _credentials()
    await check_binance_testnet(log_event=False)
    usdt_free = float(state.binance_testnet_balances.get("USDT", {}).get("free", 0) or 0)
    planned = state.testnet_assigned_capital * state.max_position_pct
    amount = min(max(5.0, planned), state.testnet_assigned_capital, usdt_free)
    if amount < 5:
        raise RuntimeError("Capital disponible insuficiente. Usa al menos 5 USDT virtuales.")

    buy = await asyncio.to_thread(_market_buy_quote, api_key, secret, state.symbol, amount)
    buy_qty = float(buy.get("executedQty", 0) or 0)
    buy_quote = float(buy.get("cummulativeQuoteQty", 0) or 0)
    entry_price = _avg_price(buy)
    if buy_qty <= 0 or entry_price <= 0:
        raise RuntimeError("La compra automática no devolvió una ejecución válida.")

    account_after = await asyncio.to_thread(_signed_account_request, api_key, secret)
    balances_after = _extract_balances(account_after)
    base_asset = state.symbol.removesuffix("USDT") if state.symbol.endswith("USDT") else "BTC"
    free_base = float(balances_after.get(base_asset, {}).get("free", 0) or 0)
    min_qty, max_qty, step = await asyncio.to_thread(_lot_rules, state.symbol)
    sell_qty = _floor_step(min(buy_qty, free_base) if free_base > 0 else buy_qty, step)
    if sell_qty < min_qty:
        raise RuntimeError("La cantidad comprada quedó por debajo del mínimo vendible.")
    if sell_qty > max_qty:
        sell_qty = max_qty

    state.testnet_auto_position = {
        "entry_price": entry_price,
        "amount_usdt": buy_quote,
        "buy_qty": buy_qty,
        "sell_qty": float(sell_qty),
        "opened_at": _utc_now(),
        "buy_order_id": buy.get("orderId"),
    }
    set_runtime_setting("testnet_auto_position", json.dumps(state.testnet_auto_position))
    state.testnet_auto_last_trade_ts = time.time()
    state.testnet_auto_last_action = f"BUY automático {buy_quote:.4f} USDT a {entry_price:,.2f}"
    add_event("info", "BUY automático TESTNET", state.testnet_auto_last_action)


async def _close_auto_position(reason: str) -> None:
    pos = state.testnet_auto_position
    if not pos:
        return
    api_key, secret = _credentials()
    min_qty, max_qty, step = await asyncio.to_thread(_lot_rules, state.symbol)
    account = await asyncio.to_thread(_signed_account_request, api_key, secret)
    balances = _extract_balances(account)
    base_asset = state.symbol.removesuffix("USDT") if state.symbol.endswith("USDT") else "BTC"
    free_base = float(balances.get(base_asset, {}).get("free", 0) or 0)
    qty = _floor_step(min(float(pos["sell_qty"]), free_base), step)
    if qty < min_qty:
        raise RuntimeError("No hay cantidad suficiente para cerrar la posición automática.")
    if qty > max_qty:
        qty = max_qty

    sell = await asyncio.to_thread(_market_sell_qty, api_key, secret, state.symbol, qty)
    sell_quote = float(sell.get("cummulativeQuoteQty", 0) or 0)
    exit_price = _avg_price(sell)
    net_pnl = sell_quote - float(pos["amount_usdt"])
    state.testnet_auto_pnl += net_pnl
    state.testnet_auto_daily_pnl += net_pnl
    if net_pnl > 0:
        state.testnet_auto_consecutive_losses = 0
        level, title = "success", "Operación automática ganada"
    else:
        state.testnet_auto_consecutive_losses += 1
        level, title = "danger", "Operación automática cerrada"

    trade = {
        "opened_at": pos["opened_at"], "closed_at": _utc_now(), "symbol": "BTC/USDT",
        "side": "TESTNET_AUTO_LONG", "entry_price": pos["entry_price"], "exit_price": exit_price,
        "amount_usdt": pos["amount_usdt"], "gross_pnl": net_pnl, "fees": 0.0,
        "net_pnl": net_pnl, "reason": f"TESTNET_AUTO_{reason}",
    }
    add_trade(trade)
    state.binance_testnet_last_trade = trade
    state.testnet_auto_last_action = f"SELL automático {reason}: {net_pnl:+.6f} USDT"
    add_event(level, title, state.testnet_auto_last_action)
    state.testnet_auto_position = None
    set_runtime_setting("testnet_auto_position", "")
    state.testnet_auto_last_trade_ts = time.time()
    await check_binance_testnet(log_event=False)


async def testnet_auto_loop() -> None:
    """Trading técnico automático. V6 está hard-codeado a Spot Testnet solamente."""
    while True:
        try:
            if not state.testnet_auto_enabled:
                await asyncio.sleep(1)
                continue
            if not state.binance_testnet_connected:
                ok = await check_binance_testnet(log_event=False)
                if not ok:
                    state.testnet_auto_signal = "SIN CONEXIÓN"
                    await asyncio.sleep(3)
                    continue

            price = await asyncio.to_thread(_ticker_price, state.symbol)
            state.testnet_price = price
            state.testnet_prices.append(price)
            values = list(state.testnet_prices)
            state.testnet_ema_fast = _ema(values[-60:], 9)
            state.testnet_ema_slow = _ema(values[-90:], 21)
            state.testnet_rsi = _rsi(values, 14)

            if state.testnet_ema_fast is None or state.testnet_ema_slow is None or state.testnet_rsi is None:
                state.testnet_auto_signal = "CALENTANDO"
                await asyncio.sleep(1)
                continue

            if state.testnet_auto_position:
                entry = float(state.testnet_auto_position["entry_price"])
                change = (price - entry) / entry
                if change <= -state.stop_loss_pct:
                    state.testnet_auto_signal = "STOP LOSS"
                    await _close_auto_position("STOP_LOSS")
                elif change >= state.take_profit_pct:
                    state.testnet_auto_signal = "TAKE PROFIT"
                    await _close_auto_position("TAKE_PROFIT")
                elif state.testnet_ema_fast < state.testnet_ema_slow and state.testnet_rsi < 48:
                    state.testnet_auto_signal = "SALIR"
                    await _close_auto_position("SIGNAL_EXIT")
                else:
                    state.testnet_auto_signal = "MANTENER"
            else:
                loss_limit = -(state.testnet_assigned_capital * state.max_daily_loss_pct)
                if state.testnet_auto_daily_pnl <= loss_limit:
                    state.testnet_auto_enabled = False
                    set_runtime_setting("testnet_auto_enabled", "false")
                    state.testnet_auto_pause_reason = "Límite de pérdida diaria alcanzado"
                    add_event("danger", "AUTO TESTNET pausado", state.testnet_auto_pause_reason)
                    continue
                if state.testnet_auto_consecutive_losses >= state.max_consecutive_losses:
                    state.testnet_auto_enabled = False
                    set_runtime_setting("testnet_auto_enabled", "false")
                    state.testnet_auto_pause_reason = "Máximo de pérdidas consecutivas alcanzado"
                    add_event("danger", "AUTO TESTNET pausado", state.testnet_auto_pause_reason)
                    continue
                if time.time() - state.testnet_auto_last_trade_ts < state.cooldown_seconds:
                    state.testnet_auto_signal = "COOLDOWN"
                    await asyncio.sleep(1)
                    continue

                bullish = state.testnet_ema_fast > state.testnet_ema_slow * 1.00005
                rsi_ok = 52 <= state.testnet_rsi <= 68
                if bullish and rsi_ok:
                    state.testnet_auto_signal = "COMPRAR"
                    await _open_auto_position()
                else:
                    state.testnet_auto_signal = "ESPERAR"

            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.testnet_auto_last_action = f"Error automático: {type(exc).__name__}: {exc}"
            add_event("danger", "Error AUTO TESTNET", state.testnet_auto_last_action)
            await asyncio.sleep(3)


async def binance_testnet_monitor() -> None:
    first = True
    while True:
        try:
            await check_binance_testnet(log_event=first)
            first = False
            await asyncio.sleep(20)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(20)
