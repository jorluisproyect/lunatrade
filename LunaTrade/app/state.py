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

    bot_enabled: bool = os.getenv("PAPER_AUTOTRADE", "false").lower() == "true"
    mode: str = "PAPER"

    cash: float = float(os.getenv("PAPER_STARTING_CAPITAL", "10"))
    reserve: float = 0.0
    total_deposits: float = float(os.getenv("PAPER_STARTING_CAPITAL", "10"))
    total_withdrawals: float = 0.0

    position: Position | None = None
    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    equity_history: Deque[dict] = field(default_factory=lambda: deque(maxlen=500))

    # Ajustes V1 (SIMULACION)
    fee_rate: float = 0.001       # 0.10% por lado, solo supuesto del simulador
    stop_loss_pct: float = 0.004  # 0.40%
    take_profit_pct: float = 0.008  # 0.80%
    max_position_pct: float = 0.25
    max_daily_loss_pct: float = 0.02
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
        return {
            "symbol": self.symbol,
            "price": self.price,
            "connected": self.connected,
            "connection_message": self.connection_message,
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
