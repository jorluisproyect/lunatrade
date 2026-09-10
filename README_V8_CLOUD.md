# LunaTrade V8 — Cloud Auto Testnet

**Solo Binance Spot Testnet. Sin dinero real.**

## Objetivo
Ejecutar LunaTrade en un servidor para que la laptop pueda estar apagada y el panel siga disponible desde el teléfono por HTTPS.

## Railway
1. Sube esta carpeta a un repositorio privado de GitHub.
2. En Railway crea `New Project -> Deploy from GitHub repo` y selecciona el repo.
3. En `Variables` agrega:
   - `CLOUD_MODE=true`
   - `SYMBOL=BTCUSDT`
   - `TESTNET_ASSIGNED_CAPITAL=100`
   - `TESTNET_AUTOTRADE=true`
   - `BINANCE_TESTNET_API_KEY=...`
   - `BINANCE_TESTNET_SECRET_KEY=...`
   - `LUNATRADE_ACCESS_PASSWORD=...`
   - `LUNATRADE_SESSION_SECRET=...`
   - `LUNATRADE_DATA_DIR=/data`
4. Genera un secreto de sesión en PowerShell:
   `-join (1..64 | ForEach-Object { [char](Get-Random -InputObject ((48..57)+(65..90)+(97..122))) })`
5. Añade un Volume al servicio y móntalo en `/data` para conservar historial y el estado Activado/Pausado.
6. En `Settings -> Networking -> Public Networking`, pulsa `Generate Domain`.
7. Abre el dominio `https://....up.railway.app` desde el teléfono, inicia sesión y usa `Instalar LunaTrade` / `Añadir a pantalla de inicio`.

## Seguridad
- Nunca subas `.env` a GitHub.
- Usa exclusivamente claves de Binance Spot Testnet en esta versión.
- El navegador/teléfono no recibe la API Secret de Binance.
- El panel cloud queda protegido por contraseña y cookie HttpOnly.

## Operación automática
La primera vez que la base de datos esté vacía, `TESTNET_AUTOTRADE=true` y `TESTNET_ASSIGNED_CAPITAL=100` dejan el bot configurado para Auto Testnet. Si lo pausas desde Emergency Stop, esa pausa queda persistida en el Volume y no se reactivará sola al reiniciar.

Por seguridad, el máximo por operación usa `max_position_pct` (25% por defecto). Con 100 USDT asignados, una entrada utiliza hasta ~25 USDT, no los 100 completos.
