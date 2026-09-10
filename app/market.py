from __future__ import annotations

import asyncio
import json

from websockets.asyncio.client import connect

from .database import add_event
from .state import state

SPOT_STREAMS = [
    "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "wss://stream.binance.com:443/ws/btcusdt@trade",
]


async def market_stream() -> None:
    """Consume precio publico BTC/USDT. No usa API key ni mueve fondos."""
    url_index = 0
    while True:
        url = SPOT_STREAMS[url_index % len(SPOT_STREAMS)]
        try:
            state.connection_message = "Conectando con Binance Spot..."
            async with connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                state.connected = True
                state.connection_message = "Datos públicos Binance conectados"
                add_event("success", "Mercado conectado", "LunaTrade recibe BTC/USDT en tiempo real.")
                async for raw in ws:
                    data = json.loads(raw)
                    price = float(data["p"])
                    state.price = price
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.connected = False
            state.connection_message = "Reconectando..."
            add_event("warning", "Mercado desconectado", f"Reintento automatico: {type(exc).__name__}")
            url_index += 1
            await asyncio.sleep(3)
