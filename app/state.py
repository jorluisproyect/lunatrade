from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Position:
    entry_price: float
    amount_usdt: float
    btc_qty: float
    opened_at: str


@dataclass
class LunaState:
    symbol: str = os.getenv("SYMBOL", "BTCUSDT")
    price: float = 0.0
    connected: bool = False
    connection_message: str = "Conectando con Binance..."

    # Binance Spot Testnet (fondos virtuales)
    binance_testnet_configured: bool = bool(os.getenv("BINANCE_TESTNET_API_KEY") and os.getenv("BINANCE_TESTNET_SECRET_KEY"))
    binance_testnet_connected: bool = False
    binance_testnet_message: str = "Sin configurar"
    binance_testnet_balances: dict = field(default_factory=dict)
    binance_testnet_last_sync: str | None = None
    binance_testnet_last_trade: dict | None = None

    # Trading automático Binance Spot Testnet. SIEMPRE TESTNET en V6.
    testnet_auto_enabled: bool = os.getenv("TESTNET_AUTOTRADE", "false").lower() == "true"
    testnet_assigned_capital: float = float(os.getenv("TESTNET_ASSIGNED_CAPITAL", "100"))
    testnet_auto_position: dict | None = None
    testnet_auto_pnl: float = 0.0
    testnet_auto_daily_pnl: float = 0.0
    testnet_auto_consecutive_losses: int = 0
    testnet_auto_last_trade_ts: float = 0.0
    testnet_auto_pause_reason: str = ""
    testnet_auto_signal: str = "ESPERAR"
    testnet_auto_last_action: str = "Sin operaciones automáticas todavía"
    testnet_price: float = 0.0
    testnet_prices: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    testnet_ema_fast: float | None = None
    testnet_ema_slow: float | None = None
    testnet_rsi: float | None = None

    # PAPER permanece solo para laboratorio/indicadores.
    bot_enabled: bool = os.getenv("PAPER_AUTOTRADE", "false").lower() == "true"
    mode: str = "TESTNET_AUTO"
    cash: float = float(os.getenv("PAPER_STARTING_CAPITAL", "10"))
    reserve: float = 0.0
    total_deposits: float = float(os.getenv("PAPER_STARTING_CAPITAL", "10"))
    total_withdrawals: float = 0.0
    position: Position | None = None
    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    equity_history: Deque[dict] = field(default_factory=lambda: deque(maxlen=500))

    # Ajustes de riesgo. En V6 aplican también al Testnet automático.
    fee_rate: float = 0.001
    stop_loss_pct: float = 0.004      # -0.40%
    take_profit_pct: float = 0.008    # +0.80%
    max_position_pct: float = 0.25
    max_daily_loss_pct: float = 0.02  # -2% del capital asignado
    max_consecutive_losses: int = 3
    reinvest_pct: float = 0.70
    cooldown_seconds: int = 60

    last_trade_ts: float = 0.0
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    bot_pause_reason: str = ""
    signal: str = "ESPERAR"
    rsi: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None

    def equity(self) -> float:
        position_value = 0.0
        if self.position and self.price > 0:
            position_value = self.position.btc_qty * self.price
        return self.cash + self.reserve + position_value

    def net_funding(self) -> float:
        return self.total_deposits - self.total_withdrawals

    def total_profit(self) -> float:
        return self.equity() - self.net_funding()

    def profit_pct(self) -> float:
        funding = self.net_funding()
        return (self.total_profit() / funding * 100) if funding > 0 else 0.0

    def snapshot(self) -> dict:
        usdt = self.binance_testnet_balances.get("USDT", {})
        return {
            "symbol": self.symbol,
            "price": self.price,
            "connected": self.connected,
            "connection_message": self.connection_message,
            "binance_testnet": {
                "configured": self.binance_testnet_configured,
                "connected": self.binance_testnet_connected,
                "message": self.binance_testnet_message,
                "balances": self.binance_testnet_balances,
                "usdt_free": usdt.get("free", 0),
                "usdt_total": usdt.get("total", 0),
                "last_sync": self.binance_testnet_last_sync,
                "last_trade": self.binance_testnet_last_trade,
            },
            "testnet_auto": {
                "enabled": self.testnet_auto_enabled,
                "assigned_capital": round(self.testnet_assigned_capital, 8),
                "pnl": round(self.testnet_auto_pnl, 8),
                "daily_pnl": round(self.testnet_auto_daily_pnl, 8),
                "consecutive_losses": self.testnet_auto_consecutive_losses,
                "pause_reason": self.testnet_auto_pause_reason,
                "signal": self.testnet_auto_signal,
                "last_action": self.testnet_auto_last_action,
                "price": round(self.testnet_price, 8),
                "ema_fast": round(self.testnet_ema_fast, 2) if self.testnet_ema_fast is not None else None,
                "ema_slow": round(self.testnet_ema_slow, 2) if self.testnet_ema_slow is not None else None,
                "rsi": round(self.testnet_rsi, 2) if self.testnet_rsi is not None else None,
                "position": self.testnet_auto_position,
            },
            "mode": self.mode,
            "bot_enabled": self.bot_enabled,
            "bot_pause_reason": self.bot_pause_reason,
            "signal": self.signal,
            "cash": round(self.cash, 8),
            "reserve": round(self.reserve, 8),
            "equity": round(self.equity(), 8),
            "total_profit": round(self.total_profit(), 8),
            "profit_pct": round(self.profit_pct(), 4),
            "daily_pnl": round(self.daily_pnl, 8),
            "rsi": round(self.rsi, 2) if self.rsi is not None else None,
            "ema_fast": round(self.ema_fast, 2) if self.ema_fast is not None else None,
            "ema_slow": round(self.ema_slow, 2) if self.ema_slow is not None else None,
            "consecutive_losses": self.consecutive_losses,
            "position": None if not self.position else {
                "entry_price": self.position.entry_price,
                "amount_usdt": self.position.amount_usdt,
                "btc_qty": self.position.btc_qty,
                "opened_at": self.position.opened_at,
            },
            "settings": {
                "stop_loss_pct": self.stop_loss_pct,
                "take_profit_pct": self.take_profit_pct,
                "max_position_pct": self.max_position_pct,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_consecutive_losses": self.max_consecutive_losses,
                "reinvest_pct": self.reinvest_pct,
                "cooldown_seconds": self.cooldown_seconds,
            },
            "equity_history": list(self.equity_history),
            "updated_at": utc_now(),
        }


state = LunaState()
