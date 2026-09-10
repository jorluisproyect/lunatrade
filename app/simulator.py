from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

from .database import add_event, add_trade
from .state import Position, state


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = price * k + value * (1 - k)
    return value


def rsi(values: list[float], period: int = 14) -> float | None:
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


def today_limit_hit() -> bool:
    base = max(state.net_funding(), 0.01)
    return state.daily_pnl <= -(base * state.max_daily_loss_pct)


def can_open() -> bool:
    if not state.bot_enabled or state.position is not None or state.price <= 0:
        return False
    if time.time() - state.last_trade_ts < state.cooldown_seconds:
        return False
    if today_limit_hit():
        state.bot_enabled = False
        state.bot_pause_reason = "Limite de perdida diaria alcanzado"
        add_event("danger", "Bot pausado", state.bot_pause_reason)
        return False
    if state.consecutive_losses >= state.max_consecutive_losses:
        state.bot_enabled = False
        state.bot_pause_reason = "Maximo de perdidas consecutivas alcanzado"
        add_event("danger", "Bot pausado", state.bot_pause_reason)
        return False
    return state.cash > 0.50


def open_position() -> None:
    amount = min(state.cash * state.max_position_pct, state.cash)
    if amount <= 0:
        return

    entry_fee = amount * state.fee_rate
    spend = amount
    btc_qty = (spend - entry_fee) / state.price
    state.cash -= spend
    state.position = Position(
        entry_price=state.price,
        amount_usdt=spend,
        btc_qty=btc_qty,
        opened_at=datetime.now(timezone.utc).isoformat(),
    )
    state.last_trade_ts = time.time()
    add_event("info", "Compra PAPER", f"Compra simulada BTC/USDT por ${spend:.2f} a {state.price:,.2f}.")


def close_position(reason: str) -> None:
    pos = state.position
    if not pos or state.price <= 0:
        return

    gross_value = pos.btc_qty * state.price
    exit_fee = gross_value * state.fee_rate
    net_value = gross_value - exit_fee
    net_pnl = net_value - pos.amount_usdt

    # Para mostrar fees totales, estimamos fee entrada a partir del capital usado.
    entry_fee = pos.amount_usdt * state.fee_rate
    gross_pnl = (pos.btc_qty * state.price) - (pos.btc_qty * pos.entry_price)
    total_fees = entry_fee + exit_fee

    state.cash += net_value
    state.daily_pnl += net_pnl

    if net_pnl > 0:
        reserve_part = net_pnl * (1 - state.reinvest_pct)
        reserve_part = min(reserve_part, state.cash)
        state.cash -= reserve_part
        state.reserve += reserve_part
        state.consecutive_losses = 0
        level = "success"
        title = "Operacion ganada"
    else:
        state.consecutive_losses += 1
        level = "danger"
        title = "Operacion cerrada con perdida"

    trade = {
        "opened_at": pos.opened_at,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTC/USDT",
        "side": "LONG",
        "entry_price": pos.entry_price,
        "exit_price": state.price,
        "amount_usdt": pos.amount_usdt,
        "gross_pnl": gross_pnl,
        "fees": total_fees,
        "net_pnl": net_pnl,
        "reason": reason,
    }
    add_trade(trade)
    add_event(level, title, f"Resultado PAPER: {net_pnl:+.4f} USDT. Motivo: {reason}.")
    state.position = None
    state.last_trade_ts = time.time()


def evaluate_signal() -> None:
    values = list(state.prices)
    state.ema_fast = ema(values[-60:], 9)
    state.ema_slow = ema(values[-90:], 21)
    state.rsi = rsi(values, 14)

    if state.ema_fast is None or state.ema_slow is None or state.rsi is None:
        state.signal = "CALENTANDO"
        return

    if state.position:
        entry = state.position.entry_price
        change = (state.price - entry) / entry
        if change <= -state.stop_loss_pct:
            state.signal = "STOP LOSS"
            close_position("STOP_LOSS")
            return
        if change >= state.take_profit_pct:
            state.signal = "TAKE PROFIT"
            close_position("TAKE_PROFIT")
            return
        if state.ema_fast < state.ema_slow and state.rsi < 48:
            state.signal = "SALIR"
            close_position("SIGNAL_EXIT")
            return
        state.signal = "MANTENER"
        return

    # Estrategia DEMO deliberadamente conservadora. Solo PAPER.
    bullish = state.ema_fast > state.ema_slow * 1.00005
    rsi_ok = 52 <= state.rsi <= 68

    if bullish and rsi_ok:
        state.signal = "COMPRAR (PAPER)"
        if can_open():
            open_position()
    else:
        state.signal = "ESPERAR"


async def simulation_loop() -> None:
    last_sample = 0.0
    while True:
        try:
            now = time.time()
            if state.price > 0 and now - last_sample >= 1:
                state.prices.append(state.price)
                evaluate_signal()
                state.equity_history.append(
                    {"t": int(now * 1000), "value": round(state.equity(), 8)}
                )
                last_sample = now
            await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            add_event("danger", "Error del simulador", f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(1)
