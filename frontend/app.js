const $ = (id) => document.getElementById(id);
const state = {
  last: null,
  suggestions: [],
  directory: [],
  watchlist: JSON.parse(localStorage.getItem("india-candle-watchlist") || "[]")
};

const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
function fmt(x,d=2){ return Number.isFinite(Number(x)) ? Number(x).toLocaleString("en-IN",{minimumFractionDigits:d,maximumFractionDigits:d}) : "—"; }
function setBusy(btn,busy,label){ if(!btn)return; btn.disabled=busy; if(busy){btn.dataset.old=btn.textContent;btn.textContent=label;}else{btn.textContent=btn.dataset.old||btn.textContent;} }
async function api(path, opts={}) {
  const attempts = opts.retry === false ? 1 : 2;
  let lastErr = null;
  for(let attempt=0; attempt<attempts; attempt++){
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(), opts.timeout || 25000);
    try{
      const r=await fetch(path,{...opts,signal:controller.signal,headers:{"Content-Type":"application/json",...(opts.headers||{})}});
      const text=await r.text();
      let data={};
      try{ data=text?JSON.parse(text):{} }catch{ data={detail:text||"Invalid server response"} }
      if(!r.ok) throw new Error(data.detail||`Request failed (${r.status})`);
      return data;
    }catch(e){
      lastErr=e;
      if(attempt===attempts-1){
        throw new Error(e.name==="AbortError" ? "The request timed out. The server is still safe to retry." : e.message);
      }
      await new Promise(resolve=>setTimeout(resolve,350));
    } finally { clearTimeout(timer); }
  }
  throw lastErr || new Error("Request failed");
}
function message(target,text,kind="ok"){ const el=$(target); if(!el)return; el.textContent=text; el.className=`message ${kind}`; }
function clearMessage(target){ const el=$(target); if(el){el.className="message hidden";el.textContent="";} }
function saveWatchlist(){ localStorage.setItem("india-candle-watchlist", JSON.stringify(state.watchlist)); }

function switchTab(name){
  document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));
  document.querySelectorAll(".tab-panel").forEach(p=>p.classList.toggle("active",p.id===name));
  if(name==="repository") { loadAudit().catch(()=>{}); }
  if(name==="journal") { loadJournal().catch(()=>{}); }
}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>switchTab(b.dataset.tab)));

function setMarketBadge(status){
  const el=$("providerBadge");
  const value=String(status||"").toUpperCase();
  let text="MARKET DATA: READY", cls="badge-green";
  if(value==="LIVE") text="MARKET DATA: LIVE";
  else if(value==="CACHED") { text="MARKET DATA: CACHED"; cls="badge-amber"; }
  else if(value==="STALE") { text="MARKET DATA: STALE"; cls="badge-red"; }
  else if(value==="UNAVAILABLE" || value==="UNVERIFIED" || value==="FALLBACK") { text="MARKET DATA: RECHECK"; cls="badge-red"; }
  el.textContent=text; el.className=`badge ${cls}`;
}

async function boot(){
  try{
    const b=await api("/api/bootstrap");
    setMarketBadge("READY");
    const c=b.catalog||{};
    $("catalogBadge").textContent=c.count?`UNIVERSE: ${c.count.toLocaleString("en-IN")}`:"UNIVERSE: EXCHANGE DIRECTORY";
    $("catalogBadge").className="badge badge-green";
    renderRepository(b.repository);
    renderWatchChips();
  }catch(e){
    setMarketBadge("UNAVAILABLE");
    message("marketMessage",e.message,"err");
  }
}

function chartRows(){
  const rows=state.last?.candles||[];
  let requested=Number($("chartWindow")?.value||36);
  const interval=state.last?.interval||"5m";
  if(!$("chartWindow")?.dataset.userSet){ requested=interval==="5m"?18:interval==="15m"?24:interval==="30m"?30:interval==="60m"?40:52; }
  return rows.slice(-requested);
}
function labelTime(v, interval){
  const d=new Date(v);
  if(Number.isNaN(d.getTime())) return "";
  return interval==="1d" ? d.toLocaleDateString("en-IN",{day:"2-digit",month:"short"}) : d.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"});
}
function drawChart(rows=chartRows()){
  const c=$("chart"),ctx=c?.getContext("2d");
  if(!c||!ctx) return;
  const dpr=window.devicePixelRatio||1;
  const rect=c.getBoundingClientRect();
  c.width=Math.max(1,Math.floor(rect.width*dpr)); c.height=Math.max(1,Math.floor(rect.height*dpr));
  ctx.setTransform(dpr,0,0,dpr,0,0);
  const w=rect.width,h=rect.height;ctx.clearRect(0,0,w,h);
  if(!rows?.length){ return; }
  const pad={l:78,r:24,t:20,b:54}, volumeH=Math.min(74,h*0.18), priceH=h-pad.t-pad.b-volumeH;
  const plotW=w-pad.l-pad.r;
  const predicted=Number(state.last?.prediction?.predicted_close);
  const values=predicted?rows.flatMap(r=>[Number(r.high),Number(r.low)]).concat([predicted]):rows.flatMap(r=>[Number(r.high),Number(r.low)]);
  const hi=Math.max(...values),lo=Math.min(...values);
  const span=(hi-lo)||1;
  const py=v=>pad.t+(hi-v)/span*priceH;
  const sx=i=>rows.length===1?pad.l+plotW/2:pad.l+i/(rows.length-1)*plotW;
  ctx.font="11px Inter,Arial";ctx.fillStyle="#6d7e93";ctx.strokeStyle="#e3e9f0";ctx.lineWidth=1;
  for(let i=0;i<5;i++){
    const y=pad.t+i/4*priceH;
    ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();
    const val=hi-(span*i/4);ctx.fillText(fmt(val,2),8,y+4);
  }
  const maxVol=Math.max(...rows.map(r=>Number(r.volume||0)),1);
  const candleW=Math.max(4,Math.min(18,plotW/rows.length*0.58));
  rows.forEach((r,i)=>{
    const x=sx(i),up=Number(r.close)>=Number(r.open),col=up?"#07966a":"#dd4050";
    ctx.strokeStyle=col;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,py(r.high));ctx.lineTo(x,py(r.low));ctx.stroke();
    const y1=py(Math.max(r.open,r.close)),y2=py(Math.min(r.open,r.close));
    ctx.fillStyle=up?"#ddf7ee":"#ffe5e9";ctx.strokeStyle=col;
    ctx.fillRect(x-candleW/2,y1,candleW,Math.max(3,y2-y1));ctx.strokeRect(x-candleW/2,y1,candleW,Math.max(3,y2-y1));
    const vh=(Number(r.volume||0)/maxVol)*volumeH;
    ctx.globalAlpha=.24;ctx.fillStyle=col;ctx.fillRect(x-candleW/2,h-pad.b-vh,candleW,vh);ctx.globalAlpha=1;
  });
  const last=rows[rows.length-1];
  ctx.strokeStyle="#1769ff";ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(pad.l,py(last.close));ctx.lineTo(w-pad.r,py(last.close));ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle="#1769ff";ctx.beginPath();ctx.arc(sx(rows.length-1),py(last.close),4.5,0,Math.PI*2);ctx.fill();
  if(Number.isFinite(predicted)){
    ctx.strokeStyle="#5c6cff";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(Math.max(pad.l,sx(rows.length-1)+candleW),py(predicted));ctx.lineTo(w-pad.r,py(predicted));ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#5c6cff";ctx.font="11px Inter,Arial";ctx.fillText(`NEXT ${fmt(predicted,2)}`,Math.max(pad.l+4,w-pad.r-92),Math.max(pad.t+12,py(predicted)-5));
  }
  ctx.fillStyle="#60758e";ctx.font="10px Inter,Arial";
  const ticks=Math.min(6,rows.length);
  for(let i=0;i<ticks;i++){
    const idx=Math.round(i*(rows.length-1)/Math.max(1,ticks-1));
    ctx.fillText(labelTime(rows[idx].time,state.last?.interval||"5m"),Math.max(pad.l, sx(idx)-28),h-20);
  }
  $("chartWindowLabel").textContent=`${rows.length} candles`;
}
$("chart")?.addEventListener("mousemove",(event)=>{
  const c=$("chart"),rows=chartRows(); if(!c||!rows.length)return;
  const rect=c.getBoundingClientRect(),padL=68,padR=18,plotW=rect.width-padL-padR;
  const x=Math.max(0,Math.min(plotW,event.clientX-rect.left-padL));
  const idx=rows.length===1?0:Math.round(x/plotW*(rows.length-1));
  const r=rows[idx], tip=$("chartTip"); if(!r||!tip)return;
  tip.innerHTML=`<b>${labelTime(r.time,state.last?.interval||"5m")}</b><br>O ${fmt(r.open,2)} · H ${fmt(r.high,2)} · L ${fmt(r.low,2)} · C ${fmt(r.close,2)}`;
  tip.style.left=`${Math.min(rect.width-220,Math.max(8,event.clientX-rect.left+12))}px`;
  tip.style.top=`${Math.max(8,event.clientY-rect.top-74)}px`;
  tip.classList.remove("hidden");
});
$("chart")?.addEventListener("mouseleave",()=>$("chartTip")?.classList.add("hidden"));
window.addEventListener("resize",()=>{ if(state.last)drawChart(); });
$("chartWindow")?.addEventListener("change",()=>{ if($("chartWindow")) $("chartWindow").dataset.userSet="1"; if(state.last)drawChart(); });

function renderValidation(v){
  const items=[
    ["Direction accuracy",`${v.direction_accuracy}%`],
    ["Signal precision",`${v.signal_precision}%`],
    ["Signal coverage",`${v.signal_coverage}%`],
    ["Return MAE",v.next_return_mae],
    ["Return R²",v.next_return_r2],
    ["Validation rows",v.validation_rows],
    ["Training rows",v.train_rows],
    ["Threshold",v.threshold],
    ["Classifier",v.classifier_name],
  ];
  $("validation").innerHTML=items.map(([a,b])=>`<div class="val"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
  const pass=v.gate_pass;
  $("gatePill").textContent=pass?`90% GATE: PASS · ${v.signal_precision}%`:`90% GATE: FAIL · ${v.signal_precision}%`;
  $("gatePill").className=`gate-pill ${pass?"gate-pass":"gate-fail"}`;
}
function renderBacktest(b){
  const items=[
    ["Validation period",b.validation_period],
    ["Signals",b.signals],["Winning signals",b.wins],["Losing signals",b.losses],
    ["Signal precision",`${b.signal_precision}%`],["Coverage",`${b.coverage_pct}%`],
    ["Strategy return",`${b.strategy_return_pct}%`],["Buy & hold",`${b.buy_hold_return_pct}%`],
    ["Max drawdown",`${b.max_drawdown_pct}%`],["Profit factor",b.profit_factor],
  ];
  $("backtest").innerHTML=items.map(([a,b])=>`<div class="val"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
  $("backtestPeriod").textContent=b.validation_period||"—";
}
function renderNews(n){
  const s=n?.summary||{};
  $("newsImpact").textContent=`Impact ${Number(s.impact||0)>=0?"+":""}${Number(s.impact||0).toFixed(2)}`;
  $("newsSummary").innerHTML=[
    ["Headlines",s.headline_count||0],["Positive",s.positive||0],["Negative",s.negative||0],["Neutral",s.neutral||0]
  ].map(([a,b])=>`<div><b>${esc(b)}</b><span>${esc(a)}</span></div>`).join("");
  $("newsList").innerHTML=(n.articles||[]).map(a=>`<article class="news-item"><strong>${esc(a.title)}</strong><div class="news-meta"><span>${esc(a.publisher||"")}</span><span>${Number(a.sentiment)>=0?"positive":"negative"}</span></div></article>`).join("") || '<div class="muted">No contextual headlines available.</div>';
}
function renderExplain(p){
  $("reasons").innerHTML=(p.explanation?.reasons||["No dominant evidence cluster."]).map(x=>`<div class="reason">✓ ${esc(x)}</div>`).join("");
  $("risks").innerHTML=(p.explanation?.risks||["No major rule-based risk flag."]).map(x=>`<div class="reason risk">⚠ ${esc(x)}</div>`).join("");
  $("regime").textContent=p.regime||"REGIME —";
  const sig=p.signal;
  $("decisionNote").textContent=sig==="REVALIDATE"
    ? "This result remains inspectable, but the environment or market-data freshness gate requires revalidation before treating the action as trusted."
    : sig==="BUY" ? "BUY is eligible because the validation gate passed and current context does not block the directional signal."
    : sig==="SELL" ? "SELL is eligible because the validation gate passed and current context does not block the directional signal."
    : "HOLD means the system is deliberately refusing to force a directional trade under the current evidence.";
}
function renderRisk(r){
  $("riskPill").textContent=`${r.level} · ${r.score}/100`;
  $("riskPill").className=`gate-pill ${r.score>=70?"gate-pass":r.score>=45?"gate-amber":"gate-fail"}`;
  const items=[
    ["Risk level",r.level],["Risk score",`${r.score}/100`],["ATR",`${r.atr_pct}%`],["Realized volatility",`${r.realized_volatility_pct}%`],
    ["Stop loss",r.stop_loss==null?"Not applicable":fmt(r.stop_loss)], ["Take profit",r.take_profit==null?"Not applicable":fmt(r.take_profit)],
    ["Risk / reward",r.risk_reward],["Capital action",r.capital_action],
  ];
  $("riskGrid").innerHTML=items.map(([a,b])=>`<div class="val"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
  const note=$("decisionNote"); if(note && r.guidance) note.dataset.risk=r.guidance;
}
function renderModelOps(d){
  const m=d.model_operations||{};
  const cacheLabel = m.cache_state === "cache" ? "Memory cache" : m.cache_state === "disk-cache" ? "Disk cache" : m.retrained ? "Freshly trained" : "New model";
  const reason = m.retrained ? (m.cache_state === "forced-retrain" ? "Manual retrain requested" : "Prediction environment or data changed") : "Safe cached model reuse";
  const items=[
    ["Mode",cacheLabel],
    ["Why",reason],
    ["Model version",m.model_version||d.model?.model_version||"—"],
    ["Training time",`${m.training_seconds??d.model?.training_seconds??0}s`],
    ["Training rows",d.model?.train_rows||"—"],
    ["Validation precision",`${d.model?.signal_precision ?? "—"}%`],
    ["Data fingerprint",m.dataset_fingerprint||"—"],
    ["Code environment",m.environment_fingerprint||"—"],
  ];
  $("modelOps").innerHTML=items.map(([a,b])=>`<div class="val"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
}
function renderFreshness(d){
  const data=d.data||{};
  const current=data.status==="CURRENT"||data.status==="LIVE";
  $("dataFreshPill").textContent=current?"CURRENT":"RECHECK";
  $("dataFreshPill").className=`pill ${current?"pill-good":"pill-warn"}`;
  const items=[
    ["Status",data.status],["Last candle",new Date(d.last_timestamp).toLocaleString()],
    ["Freshness",`${fmt((data.freshness_seconds||0)/60,1)} min`],["History rows",data.history_rows],
  ];
  $("dataFreshness").innerHTML=items.map(([a,b])=>`<div class="val"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
}
function setTrust(t){
  $("trustScore").textContent=`${t.score}/100`;
  $("trustStatus").textContent=t.status;
  $("overallBadge").textContent=`TRUST: ${t.status}`;
  const good=t.status==="TRUSTED";const warn=/REVALIDATION|NO-TRADE|CAUTION/.test(t.status);
  $("overallBadge").className=`badge ${good?"badge-green":warn?"badge-amber":"badge-red"}`;
  $("trustChecks").innerHTML=(t.checks||[]).map(x=>{
    const cls=x.status==="PASS"?"status-pass":x.status==="FAIL"?"status-fail":x.status==="WARN"?"status-warn":"status-info";
    return `<div class="trust-node"><span class="eyebrow">${esc(x.name)}</span><div class="status ${cls}">${esc(x.status)}</div><p>${esc(x.detail)}</p></div>`;
  }).join("");
}
function renderTrustReport(d){
  const p=d.prediction,repo=p.environment.repository,data=p.environment.data;
  $("trustHeadline").textContent=`${d.instrument.symbol} · ${d.interval}`;
  $("trustReport").textContent=[
    "TRUSTGRAPH REPORT",
    "-----------------",
    `Market data       : ${data}`,
    `Repository        : ${repo}`,
    `Repository scope  : ${p.environment.repository_scope}`,
    `Model precision   : ${p.validation.signal_precision}%`,
    `90% gate          : ${p.validation.gate_pass?"PASS":"FAIL"}`,
    `Model version     : ${p.validation.model_version}`,
    `Regime            : ${d.regime.regime}`,
    `Risk               : ${p.risk.level} (${p.risk.score}/100)`,
    `Signal             : ${p.signal}`,
    `Confidence         : ${p.confidence}%`,
    "",
    "Decision:",
    p.signal==="REVALIDATE"
      ? "Re-scan and accept the updated environment before treating this result as trusted."
      : p.signal==="HOLD"
        ? "The model intentionally held instead of forcing a trade."
        : "All required trust conditions currently support this paper-analysis signal."
  ].join("\n");
}

function renderLatestCandle(d){
  const rows=d.candles||[];
  const r=rows[rows.length-1];
  if(!r){ $("latestCandle").innerHTML='<span>Latest candle</span><b>—</b><small>No candle data</small>'; return; }
  const up=Number(r.close)>=Number(r.open);
  $("latestCandle").innerHTML=`<span>Latest ${esc(d.interval)} candle · ${new Date(r.time).toLocaleString()}</span><b class="${up?"latest-up":"latest-down"}">O ${fmt(r.open,2)} · H ${fmt(r.high,2)} · L ${fmt(r.low,2)} · C ${fmt(r.close,2)}</b><small>Volume ${Number(r.volume||0).toLocaleString("en-IN")}</small>`;
}

async function analyze(force=false,full=false){
  const symbol=$("symbol").value.trim(),interval=$("interval").value;
  if(!symbol){message("marketMessage","Choose or enter a stock symbol first.","err");return;}
  const btn=force?$("retrainBtn"):full?$("fullBtn"):$(`analyzeBtn`);
  setBusy(btn,true,force?"RETRAINING…":full?"RUNNING FULL CHECK…":"ANALYZING…");
  clearMessage("marketMessage");
  $("signal").textContent="ANALYZING…";
  try{
    const url=full?`/api/full-analysis?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`:`/api/analyze?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&retrain=${force}`;
    const d=await api(url,{timeout: force?45000:35000});
    state.last=d;
    setMarketBadge(d.data.status==="LIVE"?"LIVE":d.data.status==="CACHED"?"CACHED":d.data.status);
    $("dataState").textContent=d.data.status;
    $("modelState").textContent=d.model.gate_pass?"PASS":"FAIL";
    $("modelVersion").textContent=d.model.model_version;
    $("current").textContent=fmt(d.current_price);$("nextClose").textContent=fmt(d.prediction.predicted_close);
    $("nextHigh").textContent=fmt(d.prediction.predicted_high);$("nextLow").textContent=fmt(d.prediction.predicted_low);
    $("eodClose").textContent=fmt(d.prediction.predicted_eod_close);$("signal").textContent=d.prediction.signal;
    $("signal").className=`signal-${String(d.prediction.signal).toLowerCase()}`;
    $("confidence").textContent=`Confidence ${d.prediction.confidence}% · UP ${(d.prediction.probability_up*100).toFixed(1)}%`;
    $("probability").textContent=`UP ${(d.prediction.probability_up*100).toFixed(1)}%`;
    renderLatestCandle(d);
    const intervalLabel={"5m":"5-minute candles","15m":"15-minute candles","30m":"30-minute candles","60m":"60-minute candles","1d":"Daily candles"}[interval]||interval;
    $("chartTitle").textContent=`${d.instrument.symbol} · ${d.instrument.name} · ${intervalLabel}`;
    drawChart();renderValidation(d.model);renderBacktest(d.backtest);renderNews(d.news);renderExplain({...d.prediction,regime:d.regime.regime});renderRisk(d.prediction.risk);renderModelOps(d);renderFreshness(d);
    setTrust(d.prediction.trust);renderTrustReport(d);
    message("marketMessage",`Analysis complete · ${d.retrained?"model freshly trained":"cached model reused"} · ${d.elapsed_ms} ms` ,"ok");
  }catch(e){
    $("signal").textContent="RETRY";$("signal").className="signal-error";
    message("marketMessage",e.message,"err");
  } finally { setBusy(btn,false); }
}
$("analyzeBtn").onclick=()=>analyze(false,false);
$("retrainBtn").onclick=()=>analyze(true,false);
$("fullBtn").onclick=()=>analyze(false,true);
$("backtestBtn").onclick=()=>state.last?renderBacktest(state.last.backtest):analyze(false,false);

async function loadPulse(){
  setBusy($("pulseBtn"),true,"LOADING…");
  try{
    const symbols=state.watchlist.length?state.watchlist:undefined;
    const d=await api(symbols?`/api/pulse?symbols=${encodeURIComponent(symbols.join(","))}&limit=24`:`/api/pulse?limit=12`);
    $("pulseGrid").innerHTML=(d.results||[]).map(x=>`<div class="pulse-item" data-symbol="${esc(x.symbol)}"><b>${esc(x.symbol)}</b><span>${esc(x.name)}</span><div class="${x.change_pct>=0?"pulse-up":"pulse-down"}">${x.change_pct>=0?"+":""}${Number(x.change_pct).toFixed(2)}%</div><small>${fmt(x.price)}</small></div>`).join("") || '<div class="muted">No market quotes returned.</div>';
    document.querySelectorAll(".pulse-item").forEach(el=>el.onclick=()=>{ $("symbol").value=el.dataset.symbol; switchTab("market"); analyze(false,false); });
  }catch(e){message("marketMessage",e.message,"err")}finally{setBusy($("pulseBtn"),false)}
}
$("pulseBtn").onclick=loadPulse;

function renderWatchChips(){
  const defaults=state.watchlist.length?state.watchlist:["TCS","RELIANCE","INFY","HDFCBANK","ICICIBANK","SBIN"];
  $("watchChips").innerHTML=defaults.map(s=>`<button class="watch-chip" data-symbol="${esc(s)}">${esc(s)}</button>`).join("");
  document.querySelectorAll(".watch-chip").forEach(el=>el.onclick=()=>{ $("symbol").value=el.dataset.symbol; switchTab("market"); analyze(false,false); });
}
$("watchAddBtn").onclick=()=>{
  const v=$("watchInput").value.trim().toUpperCase(); if(!v)return;
  if(!state.watchlist.includes(v)) state.watchlist.push(v);
  state.watchlist=state.watchlist.slice(-12);saveWatchlist();renderWatchChips();$("watchInput").value="";loadPulse();
};
$("watchInput").addEventListener("keydown",e=>{if(e.key==="Enter")$("watchAddBtn").click();});

let searchTimer;
async function searchStocks(q){
  clearTimeout(searchTimer);
  if((q||"").trim().length<2){$("stockSuggestions").classList.add("hidden");return;}
  searchTimer=setTimeout(async()=>{
    try{
      const d=await api(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=24`,{timeout:10000,retry:false});
      state.suggestions=d.results||[];
      $("stockSuggestions").innerHTML=state.suggestions.map((x,i)=>`<div class="suggestion" data-index="${i}"><b>${esc(x.symbol)} · ${esc(x.name)}</b><span>${esc(x.exchange||"")} ${x.segment?`· ${esc(x.segment)}`:""}</span></div>`).join("") || '<div class="suggestion"><span>No security matched. You can still enter the exact symbol.</span></div>';
      $("stockSuggestions").classList.remove("hidden");
      document.querySelectorAll(".suggestion[data-index]").forEach(el=>el.onclick=()=>{const x=state.suggestions[Number(el.dataset.index)];$("symbol").value=x.symbol;$("stockSuggestions").classList.add("hidden");});
    }catch(e){$("stockSuggestions").classList.add("hidden");}
  },250);
}
$("symbol").addEventListener("input",e=>searchStocks(e.target.value));
$("symbol").addEventListener("keydown",e=>{if(e.key==="Enter"){$("stockSuggestions").classList.add("hidden");analyze(false,false);}});
document.addEventListener("click",e=>{if(!e.target.closest(".search-wrap"))$("stockSuggestions")?.classList.add("hidden");});

async function openDirectory(){
  $("stockModal").classList.remove("hidden");
  if(!state.directory.length){
    $("directoryList").innerHTML='<div class="muted">Loading the current listed-security directory…</div>';
    try{const d=await api("/api/stocks/catalog?full=true&limit=10000",{timeout:30000});state.directory=d.results||[];}catch(e){$("directoryList").innerHTML=`<div class="message err">${esc(e.message)}</div>`;return;}
  }
  renderDirectory($("directorySearch").value);
}
function renderDirectory(q=""){
  const query=q.trim().toLowerCase();
  const rows=query?state.directory.filter(x=>`${x.symbol} ${x.name}`.toLowerCase().includes(query)):state.directory;
  $("directoryCount").textContent=`${rows.length.toLocaleString("en-IN")} matches · ${state.directory.length.toLocaleString("en-IN")} indexed`;
  const visible=rows.slice(0,240);
  $("directoryList").innerHTML=visible.map(x=>`<button class="directory-row" data-symbol="${esc(x.symbol)}"><span><b>${esc(x.symbol)}</b><small>${esc(x.name)}</small></span><em>${esc(x.exchange||"")} · ${esc(x.segment||"")}</em></button>`).join("") || '<div class="muted">No security matched the current search.</div>';
  document.querySelectorAll(".directory-row").forEach(btn=>btn.onclick=()=>{ $("symbol").value=btn.dataset.symbol;$("stockModal").classList.add("hidden");switchTab("market");analyze(false,false); });
}
$("browseBtn").onclick=openDirectory;
$("directorySearch").addEventListener("input",e=>renderDirectory(e.target.value));
$("closeModalBtn").onclick=()=>$("stockModal").classList.add("hidden");
$("stockModal").addEventListener("click",e=>{if(e.target.id==="stockModal")$("stockModal").classList.add("hidden");});

function renderRepository(d){
  const source=d.source||{};
  const scope=source.scope||d.scope||"model";
  $("repoSourceTitle").textContent=source.type==="github-public"?"Public GitHub repository":"Model workspace";
  $("repoScope").textContent=scope==="model"?"MODEL-BOUND":"EXTERNAL AUDIT";
  $("repoPath").textContent=source.path||"—";
  $("baselineDefinition").textContent=d.baseline_definition||"—";
  $("monitoringDefinition").textContent=d.monitoring_definition||"—";
  $("repoStateBig").textContent=d.state||"—";
  $("repoFiles").textContent=Object.keys(d.current?.files||{}).length;
  $("securityScore").textContent=`${d.security_score}/100`;
  $("depChange").textContent=d.impact?.dependency_change?"YES":"NO";
  $("revalidation").textContent=d.impact?.revalidation||"—";
  const comps=d.current?.components||{};
  $("components").innerHTML=Object.entries(comps).map(([k,v])=>`<div class="component"><b>${esc(k.toUpperCase())}</b><div class="hash">${esc(v)}</div></div>`).join("")||"<div class='muted'>No tracked components.</div>";
  const items=d.impact?.items||[];
  $("impactList").innerHTML=items.length?items.slice(0,50).map(x=>`<div class="impact"><span class="tag ${String(x.impact).toLowerCase()}">${esc(x.impact)}</span><b>${esc(x.kind.toUpperCase())} · ${esc(x.path)}</b><div class="muted">${esc(x.component)} · ${esc(x.reason)}</div></div>`).join(""):`<div class='muted'>No changes detected. The live fingerprint matches the accepted baseline when a baseline exists.</div>`;
  $("findings").innerHTML=(d.findings||[]).map(f=>`<div class="finding ${String(f.severity).toLowerCase()}"><b>${esc(f.severity)}</b> · ${esc(f.message)}<code>${esc(f.file)}:${esc(f.line)}</code></div>`).join("")||"<div class='muted'>No findings.</div>";
  $("repoStateBig").style.color=d.state==="CURRENT"?"var(--green)":d.state==="STALE"?"var(--red)":"var(--amber)";
  $("bindBtn").disabled=scope==="model";
  $("bindBtn").textContent=scope==="model"?"MODEL TRUST ACTIVE":"BIND TO MODEL TRUST";
  $("simulateBtn").disabled=scope!=="model";
}
async function repoAction(path,button,label){
  setBusy(button,true,label);clearMessage("repoMessage");
  try{const d=await api(path,{method:"POST",timeout:45000});renderRepository(d);await loadAudit();message("repoMessage",d.message||`Repository state: ${d.state}.` ,"ok");}
  catch(e){message("repoMessage",e.message,"err")} finally{setBusy(button,false);}
}
$("acceptBtn").onclick=()=>repoAction("/api/repository/accept",$("acceptBtn"),"ACCEPTING…");
$("checkBtn").onclick=()=>repoAction("/api/repository/check",$("checkBtn"),"CHECKING…");
$("simulateBtn").onclick=()=>repoAction("/api/repository/simulate",$("simulateBtn"),"SIMULATING…");
$("resetBtn").onclick=()=>repoAction("/api/repository/reset",$("resetBtn"),"RETURNING…");

$("githubBtn").onclick=async ()=>{
  const url=$("githubUrl").value.trim();
  if(!url) return message("repoMessage","Enter a public GitHub HTTPS URL.","err");
  setBusy($("githubBtn"),true,"CLONING…");clearMessage("repoMessage");
  try{const d=await api(`/api/repository/source/github?url=${encodeURIComponent(url)}`,{method:"POST",timeout:210000,retry:false});const fresh=await api("/api/repository/check",{method:"POST"});renderRepository(fresh);message("repoMessage","Repository cloned. It is now an external audit target. Accept a baseline to start drift monitoring; bind to model trust only when you want repository changes to affect prediction trust.","ok");}
  catch(e){message("repoMessage",e.message,"err")}finally{setBusy($("githubBtn"),false);}
};
$("githubRefreshBtn").onclick=()=>repoAction("/api/repository/source/github/refresh",$("githubRefreshBtn"),"REFRESHING…");
$("bindBtn").onclick=()=>repoAction("/api/repository/bind-model",$("bindBtn"),"BINDING…");

async function loadAudit(){
  try{const d=await api("/api/audit?limit=40");$("audit").innerHTML=(d.results||[]).map(x=>`<div class="audit-row"><div><b>${esc(x.event)}</b><div class="muted">${esc(x.status)}</div></div><span>${new Date(x.ts).toLocaleString()}</span></div>`).join("")||'<div class="muted">No repository events yet.</div>';}catch(e){$("audit").innerHTML=`<div class="message err">${esc(e.message)}</div>`;}
}
async function loadJournal(){
  try{
    const d=await api("/api/journal?limit=80"),rows=d.results||[];
    $("journalTable").innerHTML=rows.length?`<table class="table"><thead><tr><th>TIME</th><th>SYMBOL</th><th>TF</th><th>ACTION</th><th>CONFIDENCE</th><th>PRECISION</th><th>MODEL</th><th>REPO</th><th>DATA</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${new Date(x.ts).toLocaleString()}</td><td>${esc(x.symbol)}</td><td>${esc(x.interval)}</td><td>${esc(x.signal)}</td><td>${x.confidence??"—"}%</td><td>${x.precision?Number(x.precision*100).toFixed(2):"—"}%</td><td>${esc(x.model_version)}</td><td>${esc(x.repo_state)}</td><td>${esc(x.data_state)}</td></tr>`).join("")}</tbody></table>`:'<div class="muted">No signals recorded yet.</div>';
  }catch(e){$("journalTable").innerHTML=`<div class="message err">${esc(e.message)}</div>`;}
}
$("journalBtn").onclick=loadJournal;

boot();
