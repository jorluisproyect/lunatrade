LUNATRADE V7 - MOBILE / PWA / AUTO TESTNET
==========================================

QUE CAMBIA
- Incluye el fix V6.3 para leer siempre el .env correcto.
- Saldo USDT Binance Testnet sincronizado en el dashboard.
- Capital asignado inicial recomendado: 100 USDT virtuales.
- El capital y el estado AUTO TESTNET se guardan en SQLite y sobreviven reinicios.
- Si LunaTrade se reinicia con una posición automática registrada, restaura el seguimiento de esa posición.
- Interfaz móvil mejorada y navegación inferior con etiquetas.
- Manifest + iconos + Service Worker preparados para PWA.
- Botón "Instalar LunaTrade".

IMPORTANTE SOBRE EL TELEFONO
- En tu Wi-Fi local puedes abrir: http://IP-DE-TU-PC:8000
- En HTTP local, algunos navegadores solo permiten "Añadir a pantalla de inicio" como acceso directo.
- La instalación PWA completa requiere HTTPS. Esa será la siguiente fase al alojar LunaTrade de forma segura 24/7.

INSTALACION
1. Deten LunaTrade con Ctrl+C.
2. Copia la carpeta app de esta actualización.
3. Reemplaza C:\Proyectos\LunaTrade\app
4. NO reemplaces .env, .venv, data ni lunatrade.db.
5. Inicia:
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
6. PC: http://127.0.0.1:8000/?v=70
7. Telefono: http://TU-IP:8000/?v=70
8. Verifica Binance Testnet.
9. Asigna 100 USDT virtuales y activa AUTO TESTNET.

SEGURIDAD
- V7 sigue hard-codeada a Binance Spot Testnet. No usa Binance real.
- Las API Keys siguen solamente en tu .env local.
- No publiques ni compartas tus claves.
- No expongas todavía el puerto 8000 directamente a Internet. Antes de acceso remoto añadiremos autenticacion + HTTPS.
