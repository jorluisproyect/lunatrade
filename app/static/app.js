let latest = null;
let ws;
const $ = (id) => document.getElementById(id);
const money = (n, d=2) => `$${Number(n || 0).toFixed(d)}`;
const num = (n, d=2) => n == null ? '—' : Number(n).toFixed(d);
function toast(msg){const t=$('toast');if(!t)return;t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function escapeHtml(s=''){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function strategyLabel(pct){if(pct>=100)return'Crecimiento';if(pct>=70)return'Equilibrado';if(pct>=50)return'Conservador';if(pct<=0)return'Reservar ganancias';return'Personalizado'}
function syncStrategyUi(pct){const rounded=Math.round(pct);if($('reinvestPct'))$('reinvestPct').value=rounded;if($('reinvestLabel'))$('reinvestLabel').textContent=`${rounded}%`;if($('reinvestQuick'))$('reinvestQuick').textContent=`${rounded}%`;if($('reserveQuick'))$('reserveQuick').textContent=`${100-rounded}%`;if($('strategyName'))$('strategyName').textContent=strategyLabel(rounded);document.querySelectorAll('.strategy-btn').forEach(btn=>btn.classList.toggle('active',Number(btn.dataset.reinvest)===rounded));}
function drawChart(history){const canvas=$('equityChart');if(!canvas)return;const ctx=canvas.getContext('2d'),rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.max(500,rect.width*dpr);canvas.height=300*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);const w=rect.width,h=300;ctx.clearRect(0,0,w,h);ctx.strokeStyle='#1f2a40';for(let i=0;i<5;i++){const y=20+i*((h-40)/4);ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}if(!history||history.length<2)return;const data=history.slice(-150),vals=data.map(x=>x.value);let min=Math.min(...vals),max=Math.max(...vals);if(max===min){max+=.01;min-=.01}const pad=(max-min)*.12;min-=pad;max+=pad;const pts=data.map((x,i)=>({x:(i/(data.length-1))*w,y:h-20-((x.value-min)/(max-min))*(h-40)}));ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle='#a855f7';ctx.lineWidth=2.3;ctx.stroke()}

function render(data){
  latest=data;
  const bt=data.binance_testnet||{}, a=data.testnet_auto||{};
  if($('totalTestnetCapital')) $('totalTestnetCapital').textContent=bt.connected ? money(bt.usdt_total||0) : '—';
  if($('equity')) $('equity').textContent=money(a.assigned_capital||100);
  if($('profit')) $('profit').textContent=`${Number(a.pnl||0)>=0?'+':''}${money(a.pnl||0)}`;
  if($('profit')) $('profit').className=Number(a.pnl||0)>=0?'positive':'neg';
  if($('profitPct')) $('profitPct').textContent='desde activación';
  const px=a.price||data.price;
  if($('btcPrice')) $('btcPrice').textContent=px?`$${Number(px).toLocaleString(undefined,{maximumFractionDigits:2})}`:'—';
  if($('signal')) $('signal').textContent=a.signal||'ESPERAR';
  if($('commandSignal')) $('commandSignal').textContent=a.signal||'ESPERAR';
  if($('cash'))$('cash').textContent=money(data.cash);if($('walletReserve'))$('walletReserve').textContent=money(data.reserve);if($('walletEquity'))$('walletEquity').textContent=money(data.equity);

  if($('marketStatus')) $('marketStatus').textContent=data.connected?'Mercado Binance conectado':(data.connection_message||'Conectando mercado...');
  if($('marketDot')) $('marketDot').className=`status-dot ${data.connected?'online':''}`;
  if($('marketFeedLabel')) $('marketFeedLabel').textContent=data.connected?'DATOS PÚBLICOS CONECTADOS':'RECONECTANDO…';
  if($('marketFeedBadge')) $('marketFeedBadge').textContent=data.connected?'LIVE':'…';

  const btCard=$('binanceTestnetCard'),btLabel=$('binanceTestnetLabel'),btBadge=$('binanceTestnetBadge'),btBalance=$('binanceTestnetBalance');
  if(bt.connected){btCard?.classList.remove('disconnected');btCard?.classList.add('testnet-connected');if(btLabel)btLabel.textContent='SPOT TESTNET CONECTADO';if(btBadge){btBadge.textContent='TESTNET';btBadge.className='connection-badge testnet'}if(btBalance)btBalance.textContent=`USDT virtual: ${Number(bt.usdt_total||0).toFixed(4)}`}
  else{btCard?.classList.add('disconnected');btCard?.classList.remove('testnet-connected');if(btLabel)btLabel.textContent=bt.configured?'TESTNET NO VALIDADO':'NO CONECTADA';if(btBadge){btBadge.textContent=bt.configured?'REVISAR':'OFF';btBadge.className='connection-badge off'}if(btBalance)btBalance.textContent=bt.message||'Spot Testnet pendiente'}

  if($('tradeBotStatus')) $('tradeBotStatus').textContent=a.enabled?'ACTIVO':'PAUSADO';
  if($('tradeBotStatus')) $('tradeBotStatus').className=`big-status ${a.enabled?'green-status':''}`;
  if($('toggleBot')) $('toggleBot').textContent=a.enabled?'PAUSAR AUTO TESTNET':'ACTIVAR AUTO TESTNET';
  if($('toggleTestnetAuto'))$('toggleTestnetAuto').textContent=a.enabled?'PAUSAR AUTO TESTNET':'ACTIVAR AUTO TESTNET';
  if($('autoTestnetBadge')){$('autoTestnetBadge').textContent=a.enabled?'ACTIVO':'PAUSADO';$('autoTestnetBadge').className=`connection-badge ${a.enabled?'on':'testnet'}`}
  if($('testnetAssignedCapital')&&document.activeElement!==$('testnetAssignedCapital'))$('testnetAssignedCapital').value=Number(a.assigned_capital||100).toFixed(0);
  const pos=a.position;
  if($('testnetAutoResult')){
    const status=a.pause_reason?`<b>⚠️ ${escapeHtml(a.pause_reason)}</b>`:a.enabled?'<b>🟢 LunaTrade está operando automáticamente</b>':'<b>⏸ LunaTrade automático está pausado</b>';
    const p=pos?`<br>Posición abierta: ${Number(pos.amount_usdt||0).toFixed(4)} USDT @ $${Number(pos.entry_price||0).toFixed(2)}`:'<br>Posición: ninguna abierta';
    $('testnetAutoResult').innerHTML=`${status}<br>Señal: <b>${escapeHtml(a.signal||'ESPERAR')}</b> · PnL: <b>${Number(a.pnl||0)>=0?'+':''}${Number(a.pnl||0).toFixed(6)} USDT</b>${p}<br><small>${escapeHtml(a.last_action||'Esperando')}</small>`;
  }

  if($('emaFast')) $('emaFast').textContent=a.ema_fast?`$${Number(a.ema_fast).toLocaleString(undefined,{maximumFractionDigits:2})}`:'—';
  if($('emaSlow')) $('emaSlow').textContent=a.ema_slow?`$${Number(a.ema_slow).toLocaleString(undefined,{maximumFractionDigits:2})}`:'—';
  if($('rsi')) $('rsi').textContent=a.rsi==null?'—':num(a.rsi); if($('lossStreak')) $('lossStreak').textContent=a.consecutive_losses||0;
  if(data.settings){syncStrategyUi(Math.round(data.settings.reinvest_pct*100));if($('dailyLossPct'))$('dailyLossPct').value=(data.settings.max_daily_loss_pct*100).toFixed(1);if($('positionPct'))$('positionPct').value=Math.round(data.settings.max_position_pct*100)}
  if($('eventList')) $('eventList').innerHTML=(data.events||[]).map(e=>`<div class="event-item ${e.level}"><b>${escapeHtml(e.title)}</b><small>${escapeHtml(e.message)}</small></div>`).join('')||'<div class="event-item"><small>Sin actividad todavía.</small></div>';
  if($('tradeRows')) $('tradeRows').innerHTML=(data.trades||[]).map(t=>`<tr><td>${escapeHtml(t.symbol)}</td><td>$${Number(t.entry_price).toFixed(2)}</td><td>$${Number(t.exit_price).toFixed(2)}</td><td>$${Number(t.amount_usdt).toFixed(2)}</td><td class="${t.net_pnl>=0?'pos':'neg'}">${t.net_pnl>=0?'+':''}$${Number(t.net_pnl).toFixed(4)}</td><td>${escapeHtml(t.reason)}</td></tr>`).join('')||'<tr><td colspan="6">Todavía no hay operaciones cerradas.</td></tr>';
  drawChart(data.equity_history);
}

// ===== V8 CLOUD AUTH =====
let authOkay = false;
let authRequired = false;
let wsRetryTimer = null;
function showLogin(message=''){
  const ov=$('loginOverlay'); if(ov) ov.hidden=false;
  if($('loginMessage') && message) $('loginMessage').textContent=message;
  $('loginPassword')?.focus();
}
function hideLogin(){ const ov=$('loginOverlay'); if(ov) ov.hidden=true; }
async function checkAuth(){
  try{
    const r=await fetch('/api/auth/status',{cache:'no-store'}); const d=await r.json();
    authRequired=!!d.required; authOkay=!!d.authenticated;
    if(d.required && !d.ready){ showLogin('Seguridad cloud pendiente de configurar en el servidor.'); return false; }
    if(!authOkay){ showLogin('Ingresa tu contraseña LunaTrade.'); return false; }
    hideLogin(); return true;
  }catch(_){ showLogin('No se pudo contactar LunaTrade.'); return false; }
}
$('loginForm')?.addEventListener('submit',async(e)=>{
  e.preventDefault(); const password=$('loginPassword')?.value||'';
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});
    const d=await r.json(); if(!r.ok) throw new Error(d.detail||'No se pudo iniciar sesión');
    authOkay=true; hideLogin(); if($('loginPassword')) $('loginPassword').value=''; connectWs();
  }catch(err){ showLogin(err.message); }
});
$('logoutBtn')?.addEventListener('click',async()=>{
  try{await fetch('/api/logout',{method:'POST'});}catch(_){}
  authOkay=false; try{ws?.close();}catch(_){} showLogin('Sesión cerrada.');
});
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(r.status===401){authOkay=false;showLogin('Tu sesión expiró. Vuelve a entrar.');throw new Error('Sesión expirada')}if(!r.ok)throw new Error(data.detail||'Error');render(data);return data}
function connectWs(){if(!authOkay)return; if(ws && (ws.readyState===WebSocket.OPEN||ws.readyState===WebSocket.CONNECTING))return; const proto=location.protocol==='https:'?'wss':'ws';ws=new WebSocket(`${proto}://${location.host}/ws/dashboard`);ws.onmessage=e=>render(JSON.parse(e.data));ws.onclose=(ev)=>{if(ev.code===4401){authOkay=false;showLogin('Tu sesión expiró. Vuelve a entrar.');return;} clearTimeout(wsRetryTimer);wsRetryTimer=setTimeout(connectWs,1500)}}
async function toggleAuto(){try{const enabling=!latest?.testnet_auto?.enabled;await post('/api/testnet-auto/toggle',{enabled:enabling});toast(enabling?'🤖 AUTO TESTNET activado. LunaTrade decidirá cuándo operar.':'⏸ AUTO TESTNET pausado.')}catch(e){toast(e.message)}}
$('toggleBot')?.addEventListener('click',toggleAuto);$('toggleTestnetAuto')?.addEventListener('click',toggleAuto);
$('saveTestnetCapital')?.addEventListener('click',async()=>{try{const amount=Number($('testnetAssignedCapital').value||100);await post('/api/testnet-auto/settings',{assigned_capital:amount});toast(`💰 Capital asignado: ${amount.toFixed(2)} USDT virtuales.`)}catch(e){toast(e.message)}});
$('emergencyBtn')?.addEventListener('click',async()=>{try{await post('/api/testnet-auto/toggle',{enabled:false});toast('🛑 Emergency Stop: no se abrirán nuevas operaciones automáticas.')}catch(e){toast(e.message)}});
$('checkBinanceTestnet')?.addEventListener('click',async()=>{try{const r=await fetch('/api/binance-testnet/check',{method:'POST'});const d=await r.json();if(r.status===401){authOkay=false;showLogin('Tu sesión expiró.');return;}if(!r.ok)throw new Error(d.detail||'No se pudo verificar');render(d);toast(d.binance_testnet?.connected?'🟡 Binance Spot Testnet conectado.':'Revisa Binance Testnet.')}catch(e){toast(e.message)}});
$('depositBtn')?.addEventListener('click',async()=>{try{await post('/api/sim/deposit',{amount:Number($('depositAmount').value)});toast('✅ Depósito PAPER agregado.')}catch(e){toast(e.message)}});
$('withdrawBtn')?.addEventListener('click',async()=>{try{await post('/api/sim/withdraw',{amount:Number($('withdrawAmount').value)});toast('💰 Retiro PAPER realizado.')}catch(e){toast(e.message)}});
$('reinvestPct')?.addEventListener('input',e=>syncStrategyUi(Number(e.target.value)));
$('saveSettings')?.addEventListener('click',async()=>{try{await post('/api/settings',{reinvest_pct:Number($('reinvestPct').value)/100,max_daily_loss_pct:Number($('dailyLossPct').value)/100,max_position_pct:Number($('positionPct').value)/100});toast('✅ Ajustes guardados.')}catch(e){toast(e.message)}});
document.querySelectorAll('.strategy-btn').forEach(btn=>btn.addEventListener('click',async()=>{try{const pct=Number(btn.dataset.reinvest);syncStrategyUi(pct);await post('/api/settings',{reinvest_pct:pct/100,max_daily_loss_pct:Number($('dailyLossPct').value)/100,max_position_pct:Number($('positionPct').value)/100});toast(`💰 Estrategia ${strategyLabel(pct)} guardada.`)}catch(e){toast(e.message)}}));
$('arbitragePreview')?.addEventListener('click',()=>toast('⚡ Arbitraje sigue pendiente de Bybit y validación de costes.'));
$('copyReferral')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText('JORGE-LT');toast('👥 Código JORGE-LT copiado.')}catch(_){toast('Código: JORGE-LT')}});
document.querySelectorAll('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.section').forEach(s=>s.classList.remove('active-section'));btn.classList.add('active');document.getElementById(btn.dataset.section).classList.add('active-section')}));
window.addEventListener('resize',()=>latest&&drawChart(latest.equity_history));

// Manual V3 sigue disponible.
const MANUAL_STORAGE_KEY='lunatrade_manual_v3_steps';
function getManualDone(){try{return new Set(JSON.parse(localStorage.getItem(MANUAL_STORAGE_KEY)||'[]').map(Number))}catch(_){return new Set()}}
function saveManualDone(done){localStorage.setItem(MANUAL_STORAGE_KEY,JSON.stringify([...done].sort((a,b)=>a-b)))}
function updateManualUi(focusNext=false){const done=getManualDone();document.querySelectorAll('.manual-step').forEach(step=>{const n=Number(step.dataset.manualStep);step.classList.toggle('completed',done.has(n));step.classList.remove('current')});const next=[1,2,3,4,5,6,7,8].find(n=>!done.has(n));if(next){const el=document.querySelector(`.manual-step[data-manual-step="${next}"]`);el?.classList.add('current');if(focusNext)el?.scrollIntoView({behavior:'smooth',block:'center'})}const pct=(done.size/8)*100;if($('manualProgressBar'))$('manualProgressBar').style.width=`${pct}%`;if($('manualProgressText'))$('manualProgressText').textContent=`${done.size} de 8 pasos`}
function completeManualStep(n,focusNext=true){const done=getManualDone();done.add(Number(n));saveManualDone(done);updateManualUi(focusNext)}
function goSection(id){document.querySelector(`.nav-item[data-section="${id}"]`)?.click();window.scrollTo({top:0,behavior:'smooth'})}
document.querySelectorAll('.manual-done').forEach(btn=>btn.addEventListener('click',()=>{completeManualStep(btn.dataset.complete,true);toast('✅ Paso completado.')}));
document.querySelectorAll('.manual-go').forEach(btn=>btn.addEventListener('click',()=>{completeManualStep(btn.dataset.complete,false);goSection(btn.dataset.goSection);toast('👉 Sigue la indicación de esta pantalla.')}));
$('resetManual')?.addEventListener('click',()=>{localStorage.removeItem(MANUAL_STORAGE_KEY);updateManualUi(false);toast('📘 Guía reiniciada.')});
updateManualUi(false);

// ===== V7 PWA / móvil =====
let deferredInstallPrompt = null;
const installBtn = $('installAppBtn');

function updateNetworkUi(){
  const online = navigator.onLine;
  if($('networkStatus')) $('networkStatus').textContent = online ? '🟢 En línea' : '🔴 Sin conexión';
  if($('installStatus')) $('installStatus').textContent = online ? 'Acceso móvil disponible' : 'Reconecta a internet o Wi‑Fi';
}
window.addEventListener('online', updateNetworkUi);
window.addEventListener('offline', updateNetworkUi);
updateNetworkUi();

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  if(installBtn){ installBtn.classList.add('ready'); installBtn.textContent = '📱 Instalar LunaTrade'; }
});

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  if(installBtn){ installBtn.textContent = '✅ LunaTrade instalado'; installBtn.disabled = true; }
  toast('✅ LunaTrade quedó instalado en tu teléfono.');
});

installBtn?.addEventListener('click', async () => {
  if(window.matchMedia('(display-mode: standalone)').matches){
    toast('✅ Ya estás usando LunaTrade como app.');
    return;
  }
  if(deferredInstallPrompt){
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    return;
  }
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isSecure = window.isSecureContext || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  if(isIOS){
    toast('📱 Safari: Compartir → Añadir a pantalla de inicio.');
  }else if(!isSecure){
    toast('📱 En esta red local usa Chrome ⋮ → Añadir a pantalla de inicio. Con HTTPS se instalará como PWA completa.');
  }else{
    toast('📱 Abre el menú del navegador y elige Instalar app / Añadir a pantalla de inicio.');
  }
});

if('serviceWorker' in navigator){
  window.addEventListener('load', async () => {
    try{
      await navigator.serviceWorker.register('/service-worker.js', {scope:'/'});
    }catch(err){
      // En IP local por HTTP algunos navegadores bloquean service workers; el acceso directo sigue funcionando.
      console.info('PWA pendiente de HTTPS:', err?.message || err);
    }
  });
}

(async()=>{ if(await checkAuth()) connectWs(); })();
