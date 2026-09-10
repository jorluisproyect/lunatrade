let latest = null;
let ws;

const $ = (id) => document.getElementById(id);
const money = (n, d=2) => `$${Number(n || 0).toFixed(d)}`;
const num = (n, d=2) => n == null ? '—' : Number(n).toFixed(d);

function toast(msg){
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2600);
}

function drawChart(history){
  const canvas = $('equityChart');
  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(500, rect.width * dpr);
  canvas.height = 300 * dpr;
  ctx.scale(dpr,dpr);
  const w = rect.width, h = 300;
  ctx.clearRect(0,0,w,h);

  ctx.strokeStyle = '#1f2a40'; ctx.lineWidth = 1;
  for(let i=0;i<5;i++){
    const y = 20 + i*((h-40)/4);
    ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();
  }
  if(!history || history.length < 2) return;
  const data = history.slice(-150);
  const vals = data.map(x=>x.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  if(max === min){max += .01; min -= .01;}
  const pad = (max-min)*.12; min -= pad; max += pad;
  const pts = data.map((x,i)=>({x:(i/(data.length-1))*w,y:h-20-((x.value-min)/(max-min))*(h-40)}));
  const grad = ctx.createLinearGradient(0,0,0,h);
  grad.addColorStop(0,'rgba(124,58,237,.38)'); grad.addColorStop(1,'rgba(124,58,237,0)');
  ctx.beginPath();ctx.moveTo(pts[0].x,h-20);pts.forEach(p=>ctx.lineTo(p.x,p.y));ctx.lineTo(pts.at(-1).x,h-20);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle='#a855f7';ctx.lineWidth=2.3;ctx.stroke();
}

function render(data){
  latest = data;
  $('equity').textContent = money(data.equity);
  $('profit').textContent = `${data.total_profit >= 0 ? '+' : ''}${money(data.total_profit)}`;
  $('profit').className = data.total_profit >= 0 ? 'positive' : 'neg';
  $('profitPct').textContent = `${data.profit_pct >= 0 ? '+' : ''}${num(data.profit_pct)}%`;
  $('btcPrice').textContent = data.price ? `$${Number(data.price).toLocaleString(undefined,{maximumFractionDigits:2})}` : '—';
  $('signal').textContent = data.signal || 'ESPERAR';
  $('reserve').textContent = money(data.reserve);
  $('cash').textContent = money(data.cash);
  $('walletReserve').textContent = money(data.reserve);
  $('walletEquity').textContent = money(data.equity);

  $('marketStatus').textContent = data.connection_message;
  $('marketDot').className = `status-dot ${data.connected ? 'online' : ''}`;
  $('botStatus').textContent = data.bot_enabled ? 'Activo' : (data.bot_pause_reason || 'Pausado');
  $('botBadge').textContent = data.bot_enabled ? 'ON' : 'OFF';
  $('botBadge').className = `badge ${data.bot_enabled ? 'on' : ''}`;
  $('toggleBot').textContent = data.bot_enabled ? 'Pausar Bot PAPER' : 'Activar Bot PAPER';

  $('emaFast').textContent = data.ema_fast ? `$${Number(data.ema_fast).toLocaleString(undefined,{maximumFractionDigits:2})}`:'—';
  $('emaSlow').textContent = data.ema_slow ? `$${Number(data.ema_slow).toLocaleString(undefined,{maximumFractionDigits:2})}`:'—';
  $('rsi').textContent = data.rsi == null ? '—' : num(data.rsi);
  $('lossStreak').textContent = data.consecutive_losses;

  if(data.settings){
    $('reinvestPct').value = Math.round(data.settings.reinvest_pct*100);
    $('reinvestLabel').textContent = `${Math.round(data.settings.reinvest_pct*100)}%`;
    $('dailyLossPct').value = (data.settings.max_daily_loss_pct*100).toFixed(1);
    $('positionPct').value = Math.round(data.settings.max_position_pct*100);
  }

  $('eventList').innerHTML = (data.events || []).map(e=>`<div class="event-item ${e.level}"><b>${escapeHtml(e.title)}</b><small>${escapeHtml(e.message)}</small></div>`).join('') || '<div class="event-item"><small>Sin actividad todavía.</small></div>';
  $('tradeRows').innerHTML = (data.trades || []).map(t=>`<tr><td>${t.symbol}</td><td>$${Number(t.entry_price).toFixed(2)}</td><td>$${Number(t.exit_price).toFixed(2)}</td><td>$${Number(t.amount_usdt).toFixed(2)}</td><td class="${t.net_pnl>=0?'pos':'neg'}">${t.net_pnl>=0?'+':''}$${Number(t.net_pnl).toFixed(4)}</td><td>${t.reason}</td></tr>`).join('') || '<tr><td colspan="6">Todavía no hay operaciones cerradas.</td></tr>';
  drawChart(data.equity_history);
}

function escapeHtml(s=''){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

async function post(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await r.json();
  if(!r.ok) throw new Error(data.detail || 'Error');
  render(data);
  return data;
}

function connectWs(){
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`);
  ws.onmessage = e => render(JSON.parse(e.data));
  ws.onclose = ()=>setTimeout(connectWs,1500);
}

$('toggleBot').addEventListener('click', async()=>{
  try{await post('/api/bot/toggle',{enabled:!latest.bot_enabled});toast(latest.bot_enabled?'Bot activado':'Bot pausado');}catch(e){toast(e.message)}
});
$('emergencyBtn').addEventListener('click', async()=>{
  try{await post('/api/bot/toggle',{enabled:false});toast('Emergency Stop: no se abrirán nuevas operaciones.');}catch(e){toast(e.message)}
});
$('depositBtn').addEventListener('click', async()=>{
  try{await post('/api/sim/deposit',{amount:Number($('depositAmount').value)});toast('Depósito PAPER agregado.');}catch(e){toast(e.message)}
});
$('withdrawBtn').addEventListener('click', async()=>{
  try{await post('/api/sim/withdraw',{amount:Number($('withdrawAmount').value)});toast('Retiro PAPER realizado.');}catch(e){toast(e.message)}
});
$('reinvestPct').addEventListener('input',e=>$('reinvestLabel').textContent=`${e.target.value}%`);
$('saveSettings').addEventListener('click', async()=>{
  try{
    await post('/api/settings',{
      reinvest_pct:Number($('reinvestPct').value)/100,
      max_daily_loss_pct:Number($('dailyLossPct').value)/100,
      max_position_pct:Number($('positionPct').value)/100,
    });toast('Ajustes PAPER guardados.');
  }catch(e){toast(e.message)}
});

document.querySelectorAll('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active-section'));
  btn.classList.add('active'); document.getElementById(btn.dataset.section).classList.add('active-section');
}));

window.addEventListener('resize',()=>latest && drawChart(latest.equity_history));
connectWs();
