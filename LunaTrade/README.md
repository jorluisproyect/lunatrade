# LunaTrade V1 — PAPER Trading

LunaTrade V1 es un prototipo local para aprender y validar la arquitectura del bot antes de conectar dinero real.

## Lo que hace esta V1
- Lee BTC/USDT en tiempo real desde el stream publico de Binance.
- Dashboard oscuro/morado tipo app.
- Modo PAPER con capital simulado.
- Estrategia DEMO basada en EMA 9 / EMA 21 + RSI.
- Stop Loss, Take Profit, limite diario y racha maxima de perdidas.
- Reinversion parcial y reserva de ganancias.
- Historial SQLite de trades y eventos.
- Depositos y retiros simulados.
- Funciona en PC y se adapta a movil.

## Lo que NO hace todavia
- No utiliza API keys reales.
- No compra ni vende criptomonedas reales.
- No retira dinero real.
- No conecta Bybit.
- No ejecuta arbitraje real.
- No envia notificaciones push todavia.

## Instalacion Windows
1. Instala Python 3.12 o superior desde python.org y marca `Add Python to PATH`.
2. Abre la carpeta `LunaTrade` en Visual Studio Code.
3. Abre Terminal > New Terminal.
4. Ejecuta:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. Abre en tu navegador:

`http://127.0.0.1:8000`

## Siguiente fase
1. Binance Spot Testnet.
2. Cuenta/ordenes Testnet.
3. Scanner Binance + Bybit.
4. Arbitraje PAPER.
5. PWA instalable en telefono.
6. Notificaciones push/Telegram.
7. Servidor 24/7.
8. Solo despues de validacion: evaluar capital real.

> Importante: la estrategia incluida es un ejemplo de simulacion y no es una recomendacion ni una estrategia validada para dinero real.
