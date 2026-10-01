"""namestack web UI - a zero-dependency localhost interface.

Serves a single-page app and streams availability/trademark results to the
browser over Server-Sent Events. Only the Python standard library is required
on the server side (the pipeline itself uses httpx + the other runtime deps).

Launch it with ``python -m namestack.server`` or double-click
``start_namestack.bat``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import threading
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import ai
from .checker import AvailabilityChecker, Status
from .generator import generate
from .inspire import DEFAULT_VIBES, VIBES, Idea, expand, ideas_for
from .trademark import check_words

__all__ = ["INDEX_HTML", "Handler", "serve", "main"]

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>namestack</title>
<style>
:root{
  --bg:#0b0f17; --panel:#111827; --panel2:#0d1420; --border:rgba(255,255,255,.08);
  --text:#e6edf3; --muted:#8b98a9; --accent:#6366f1; --accent2:#22d3ee;
  --green:#3fb950; --red:#f85149; --yellow:#d29922; --gray:#6e7681; --cyan:#39c5cf;
}
*{box-sizing:border-box}
body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:radial-gradient(1100px 520px at 18% -12%,#1b2340 0%,var(--bg) 55%);color:var(--text);min-height:100vh}
.wrap{max-width:1080px;margin:0 auto;padding:26px 20px 70px}
header{display:flex;align-items:baseline;gap:14px;margin-bottom:22px;flex-wrap:wrap}
.logo{font-size:30px;font-weight:800;letter-spacing:-.5px;background:linear-gradient(90deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.tag{color:var(--muted);font-size:14px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:18px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 14px;font-weight:700}
.card h3{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:18px 0 10px;font-weight:700}
.hint{color:var(--muted);font-size:13px;margin:0 0 12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
label{font-size:13px;color:var(--muted)}
input[type=text],input[type=number],input[type=password],select{background:var(--panel2);border:1px solid var(--border);border-radius:9px;
  color:var(--text);padding:10px 12px;font-size:14px;outline:none;font-family:inherit}
input:focus,select:focus{border-color:var(--accent)}
input[type=text],input[type=password]{flex:1;min-width:220px}
input[type=number]{width:80px}
.pill{cursor:pointer;user-select:none;background:var(--panel2);border:1px solid var(--border);border-radius:999px;
  padding:7px 14px;font-size:13px;color:var(--muted);transition:.12s;font-family:inherit}
.pill:hover{border-color:var(--accent2);color:var(--text)}
.pill.on{background:linear-gradient(90deg,var(--accent),var(--accent2));color:#fff;border-color:transparent}
.vibes{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.vibe{cursor:pointer;text-align:left;background:var(--panel2);border:1px solid var(--border);border-radius:11px;
  padding:10px 12px;color:var(--text);font-family:inherit;transition:.12s}
.vibe:hover{border-color:var(--accent2)}
.vibe .vl{font-weight:700;font-size:14px}
.vibe .ve{font-size:12px;color:var(--muted);margin-top:3px}
.vibe.on{border-color:transparent;background:linear-gradient(135deg,rgba(99,102,241,.35),rgba(34,211,238,.22));
  box-shadow:inset 0 0 0 1px rgba(34,211,238,.6)}
.vibe.on .ve{color:#c9d4e3}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;min-height:22px}
.chip{background:rgba(99,102,241,.15);color:#c7c9ff;border:1px solid rgba(99,102,241,.4);border-radius:999px;
  padding:3px 11px;font-size:12px}
.related{margin-top:14px;display:grid;gap:8px}
.rel-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px}
.rel-row .k{color:var(--muted);width:64px;flex:none;text-transform:uppercase;letter-spacing:.06em;font-size:11px}
.w{border-radius:999px;padding:2px 9px;border:1px solid var(--border);color:#c9d4e3;background:var(--panel2)}
.w.la{border-color:rgba(210,153,34,.4);color:#e8c77a}
.w.gr{border-color:rgba(57,197,207,.4);color:#8fe3ea}
.w.ai{border-style:dashed}
.opt{display:flex;align-items:center;gap:7px;margin-right:18px}
.opt input[type=checkbox]{accent-color:var(--accent);width:16px;height:16px;cursor:pointer}
.opt input[type=checkbox]:disabled + label{opacity:.5}
.slider{width:130px;accent-color:var(--accent2)}
.btn{border:0;border-radius:10px;padding:12px 22px;font-size:15px;font-weight:700;cursor:pointer;transition:.12s;font-family:inherit}
.btn-sm{padding:9px 16px;font-size:14px}
.btn-run{background:linear-gradient(90deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 6px 22px rgba(99,102,241,.35)}
.btn-run:hover{filter:brightness(1.08)}
.btn-run:disabled{opacity:.5;cursor:not-allowed}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{color:var(--text);border-color:var(--muted)}
.btn-ghost:disabled{opacity:.45;cursor:not-allowed}
.ai-card summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px;justify-content:space-between}
.ai-card summary::-webkit-details-marker{display:none}
.ai-card summary h2{margin:0}
.ai-status{font-size:13px;color:var(--muted)}
.ai-status.ok{color:var(--green)}
.ai-body{margin-top:14px;display:grid;gap:10px}
.ai-grid{display:grid;grid-template-columns:170px 1fr;gap:10px;align-items:center}
.ai-grid label{font-size:13px}
.note{font-size:12px;color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.stat .n{font-size:26px;font-weight:800;line-height:1}
.stat .l{font-size:12px;color:var(--muted);margin-top:6px;letter-spacing:.04em}
.stat.total .n{color:#fff}.stat.available .n{color:var(--green)}.stat.registered .n{color:var(--red)}
.stat.rate .n{color:var(--yellow)}.stat.unknown .n{color:var(--gray)}
.progress{height:7px;background:var(--panel2);border:1px solid var(--border);border-radius:999px;overflow:hidden;margin-bottom:6px}
#bar{height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .2s}
.bar-meta{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:14px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filters .pill.active{color:#fff;border-color:var(--accent2)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
thead th{text-align:left;color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em;
  padding:10px 12px;border-bottom:1px solid var(--border)}
tbody td{padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top}
tbody tr:hover{background:rgba(255,255,255,.03)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#9fd7ff}
.num{text-align:right;font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.why{font-size:12px;color:var(--muted);margin-top:2px}
.badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.03em;border:1px solid}
.st-available{background:rgba(63,185,80,.14);color:var(--green);border-color:rgba(63,185,80,.4)}
.st-registered{background:rgba(248,81,73,.12);color:var(--red);border-color:rgba(248,81,73,.35)}
.st-rate_limited{background:rgba(210,153,34,.12);color:var(--yellow);border-color:rgba(210,153,34,.35)}
.st-unknown{background:rgba(110,118,129,.12);color:var(--gray);border-color:rgba(110,118,129,.3)}
.tm-none{background:rgba(63,185,80,.14);color:var(--green);border-color:rgba(63,185,80,.4)}
.tm-low{background:rgba(57,197,207,.14);color:var(--cyan);border-color:rgba(57,197,207,.4)}
.tm-med{background:rgba(210,153,34,.14);color:var(--yellow);border-color:rgba(210,153,34,.4)}
.tm-high{background:rgba(248,81,73,.14);color:var(--red);border-color:rgba(248,81,73,.4)}
.tm-unk{background:rgba(110,118,129,.12);color:var(--gray);border-color:rgba(110,118,129,.3)}
.tm-wait{color:var(--gray);border-color:transparent}
.src{font-size:11px;color:var(--gray);margin-left:6px}
#toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#1c2434;border:1px solid var(--border);
  border-radius:10px;padding:12px 18px;font-size:14px;display:none;max-width:80vw;z-index:50}
.rowcount{color:var(--muted);font-size:12px;margin-top:10px}
@media (max-width:720px){
  .stats{grid-template-columns:repeat(2,1fr)}
  .ai-grid{grid-template-columns:1fr}
  input[type=text],input[type=password]{min-width:0}
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">namestack</div>
    <div class="tag">find a startup name &middot; check the domain &middot; screen trademarks</div>
  </header>

  <div class="card">
    <h2>Seed words</h2>
    <p class="hint">Describe your idea in a few words. They're used as a theme: namestack looks for synonyms and Latin / Greek roots, then mixes them in the styles you pick.</p>
    <input type="text" id="seeds" placeholder="coffee, friends, morning" autocomplete="off">
    <div class="chips" id="chips"></div>
    <div class="related" id="related"></div>

    <h3>Naming style</h3>
    <div class="vibes" id="vibes"></div>
    <div class="row" style="margin-top:14px">
      <div class="opt"><label>Names per style</label>
        <input type="range" id="perVibe" min="5" max="50" value="20" class="slider">
        <span id="perVibeVal" class="muted">20</span></div>
      <div class="opt"><input type="checkbox" id="useAi" disabled><label for="useAi" id="useAiLabel">Use AI brainstorm (locked, add an API key below)</label></div>
    </div>
  </div>

  <details class="card ai-card" id="aiCard">
    <summary><h2>AI boost (optional)</h2><span class="ai-status" id="aiStatus">Locked</span></summary>
    <div class="ai-body">
      <p class="hint" style="margin:0">Paste an API key from your LLM provider to unlock AI brainstorming: open-vocabulary synonyms, real Latin/Greek words and smarter names in every style. The key stays on this computer; it's only sent to the provider you pick.</p>
      <div class="ai-grid">
        <label for="aiProvider">Provider</label><select id="aiProvider"></select>
        <label for="aiKey">API key</label><input type="password" id="aiKey" placeholder="sk-..." autocomplete="off">
        <label for="aiModel">Model</label><input type="text" id="aiModel">
        <label for="aiBase" id="aiBaseLabel">Base URL</label><input type="text" id="aiBase">
      </div>
      <div class="row">
        <div class="opt"><input type="checkbox" id="aiRemember"><label for="aiRemember">Remember on this device</label></div>
        <button class="btn btn-run btn-sm" id="aiConfirm">Confirm &amp; unlock</button>
        <button class="btn btn-ghost btn-sm" id="aiClear" disabled>Disconnect</button>
      </div>
      <div class="note">Each run with AI makes one request to your provider (a few cents at most).</div>
    </div>
  </details>

  <div class="card">
    <h2>TLDs</h2>
    <div class="row" id="tlds"></div>
    <div class="row" style="margin-top:10px">
      <input type="text" id="customTlds" placeholder="other TLDs (comma separated)" style="flex:1">
    </div>
  </div>

  <div class="card">
    <h2>Options</h2>
    <div class="row">
      <div class="opt"><label>Concurrency</label>
        <input type="range" id="concurrency" min="1" max="100" value="20" class="slider">
        <span id="concurrencyVal" class="muted">20</span></div>
      <div class="opt"><input type="checkbox" id="hacks" checked><label for="hacks">Domain hacks</label></div>
      <div class="opt"><input type="checkbox" id="trademark" checked><label for="trademark">Trademark screen</label></div>
      <div class="opt"><input type="checkbox" id="offline"><label for="offline">Offline (dry-run)</label></div>
      <div class="opt"><label>Trademark limit</label><input type="number" id="tmLimit" value="20" min="0" title="0 = every available name"></div>
      <div class="opt"><label>Max candidates</label><input type="number" id="limit" value="0" min="0" title="0 = all"></div>
      <div class="opt"><label>Min brand score</label><input type="range" id="minScore" min="0" max="100" value="0" class="slider">
        <span id="minScoreVal" class="muted">0</span></div>
    </div>
    <div class="row" style="margin-top:16px">
      <button class="btn btn-run" id="run">Generate &amp; Check</button>
      <button class="btn btn-ghost" id="cancel" disabled>Cancel</button>
      <button class="btn btn-ghost" id="exportCsv" disabled>Export CSV</button>
      <button class="btn btn-ghost" id="exportJson" disabled>Export JSON</button>
    </div>
  </div>

  <div class="stats" id="stats">
    <div class="stat total"><div class="n" id="nTotal">0</div><div class="l">TOTAL</div></div>
    <div class="stat available"><div class="n" id="nAvailable">0</div><div class="l">AVAILABLE</div></div>
    <div class="stat registered"><div class="n" id="nRegistered">0</div><div class="l">REGISTERED</div></div>
    <div class="stat rate"><div class="n" id="nRate">0</div><div class="l">RATE-LIMITED</div></div>
    <div class="stat unknown"><div class="n" id="nUnknown">0</div><div class="l">UNKNOWN</div></div>
  </div>

  <div class="card">
    <div class="progress"><div id="bar"></div></div>
    <div class="bar-meta"><span id="barPct">0 / 0</span><span id="stage"></span><span id="elapsed"></span></div>
    <div class="filters" id="filters">
      <button class="pill active" data-f="ALL">All</button>
      <button class="pill" data-f="AVAILABLE">Available</button>
      <button class="pill" data-f="REGISTERED">Registered</button>
      <button class="pill" data-f="RATE_LIMITED">Rate-limited</button>
      <button class="pill" data-f="UNKNOWN">Unknown</button>
    </div>
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Domain</th><th>Status</th><th style="text-align:right" title="Brandability: short, pronounceable, easy to spell">Score</th><th>Style</th><th>Trademark</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    </div>
    <div class="rowcount" id="rowCount"></div>
  </div>
</div>
<div id="toast"></div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { results:new Map(), tm:new Map(), total:0, filter:'ALL', controller:null, vibes:{}, providers:{}, ai:null };
const ORDER = { AVAILABLE:0, RATE_LIMITED:1, UNKNOWN:2, REGISTERED:3 };
const TLD_ORDER = ['com','io','ai','dev','app','co','net','org','tech','xyz','me','sh','ly','gg','fm','us','it','to','tv'];
const selectedTlds = new Set(['com','io','ai']);
const selectedVibes = new Set();
const TM_LABEL = { NONE:['clear','tm-none'], LOW:['LOW','tm-low'], MEDIUM:['MED','tm-med'], HIGH:['HIGH','tm-high'], UNKNOWN:['?','tm-unk'] };
const LS_KEY = 'namestack.ai';
const store = {
  get(){ try{ return JSON.parse(localStorage.getItem(LS_KEY)||'null'); }catch{ return null; } },
  set(v){ try{ localStorage.setItem(LS_KEY, JSON.stringify(v)); }catch{} },
  del(){ try{ localStorage.removeItem(LS_KEY); }catch{} },
};

function toast(msg){ const t=$('toast'); t.textContent=msg; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',5000); }
async function postJson(url, body){
  const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  let data={}; try{ data=await res.json(); }catch{}
  if(!res.ok) throw new Error(data.error||('HTTP '+res.status));
  return data;
}

function buildTlds(){
  const wrap=$('tlds'); wrap.innerHTML='';
  for(const t of TLD_ORDER){
    const b=document.createElement('button'); b.type='button'; b.className='pill'+(selectedTlds.has(t)?' on':'');
    b.textContent='.'+t;
    b.onclick=()=>{ selectedTlds.has(t)?selectedTlds.delete(t):selectedTlds.add(t); b.classList.toggle('on'); };
    wrap.appendChild(b);
  }
}
function buildVibes(){
  const wrap=$('vibes'); wrap.innerHTML='';
  for(const [key,v] of Object.entries(state.vibes)){
    const b=document.createElement('button'); b.type='button'; b.className='vibe'+(selectedVibes.has(key)?' on':'');
    b.title=v.blurb; b.setAttribute('aria-pressed', selectedVibes.has(key));
    b.innerHTML=`<div class="vl">${esc(v.label)}</div><div class="ve">like ${esc(v.examples)}</div>`;
    b.onclick=()=>{ selectedVibes.has(key)?selectedVibes.delete(key):selectedVibes.add(key);
      b.classList.toggle('on'); b.setAttribute('aria-pressed', selectedVibes.has(key)); };
    wrap.appendChild(b);
  }
}
function seedWords(){ return $('seeds').value.split(/[,;]/).map(s=>s.trim()).filter(Boolean); }
function renderChips(){ $('chips').innerHTML=seedWords().map(w=>`<span class="chip">${esc(w)}</span>`).join(''); }

function renderRelated(c){
  if(!c || !c.seeds.length){ $('related').innerHTML=''; return; }
  const row=(k,words,cls)=>words.length?`<div class="rel-row"><span class="k">${k}</span>${words.slice(0,18).map(w=>`<span class="w ${cls}">${esc(w)}</span>`).join('')}</div>`:'';
  let html=row('Related',c.synonyms,'')+row('Latin',c.latin,'la')+row('Greek',c.greek,'gr');
  if(c.unknown.length){
    html+=`<div class="rel-row"><span class="k">&nbsp;</span><span class="muted">No built-in match for ${c.unknown.map(esc).join(', ')}${state.ai?' - AI will cover it when "Use AI" is on.':' - unlock AI boost for richer ideas.'}</span></div>`;
  }
  $('related').innerHTML=html;
}
let inspireTimer=null;
function scheduleInspire(){
  clearTimeout(inspireTimer);
  inspireTimer=setTimeout(async()=>{
    const seeds=seedWords();
    if(!seeds.length){ renderRelated(null); return; }
    try{ renderRelated((await postJson('/api/inspire',{seeds})).concepts); }catch{}
  },250);
}

function setAiState(info){
  state.ai=info;
  const s=$('aiStatus');
  if(info){
    s.textContent=`Unlocked - ${info.label} - ${info.model} - key ${info.key_hint}`; s.className='ai-status ok';
    $('useAi').disabled=false; $('useAi').checked=true;
    $('useAiLabel').textContent=`Use AI brainstorm (${info.label})`;
    $('aiClear').disabled=false;
  }else{
    s.textContent='Locked'; s.className='ai-status';
    $('useAi').disabled=true; $('useAi').checked=false;
    $('useAiLabel').textContent='Use AI brainstorm (locked, add an API key below)';
    $('aiClear').disabled=true;
  }
  scheduleInspire();
}
function buildProviders(){
  const sel=$('aiProvider'); sel.innerHTML='';
  for(const [k,p] of Object.entries(state.providers)){
    const o=document.createElement('option'); o.value=k; o.textContent=p.label; sel.appendChild(o);
  }
  sel.onchange=()=>applyProviderDefaults(true);
}
function applyProviderDefaults(force){
  const p=state.providers[$('aiProvider').value]; if(!p) return;
  if(force || !$('aiModel').value) $('aiModel').value=p.model;
  if(force || !$('aiBase').value) $('aiBase').value=p.base_url;
  const hideBase=$('aiProvider').value==='anthropic';
  $('aiBase').style.display=hideBase?'none':''; $('aiBaseLabel').style.display=hideBase?'none':'';
}
async function confirmAi(){
  const body={provider:$('aiProvider').value, api_key:$('aiKey').value.trim(), model:$('aiModel').value.trim(), base_url:$('aiBase').value.trim()};
  $('aiConfirm').disabled=true; $('aiStatus').textContent='Checking key...'; $('aiStatus').className='ai-status';
  try{
    const info=await postJson('/api/ai/config',body);
    if($('aiRemember').checked) store.set(body); else store.del();
    $('aiKey').value='';
    setAiState(info); toast('AI unlocked');
  }catch(err){ setAiState(null); toast(err.message); }
  finally{ $('aiConfirm').disabled=false; }
}
async function clearAi(){
  try{ await postJson('/api/ai/clear'); }catch{}
  store.del(); setAiState(null); toast('AI disconnected');
}

function tmBadge(name){
  const t=state.tm.get(name);
  if(!t) return '<span class="badge tm-wait">-</span>';
  const [label,cls]=TM_LABEL[t.risk]||[t.risk,'tm-unk'];
  return `<span class="badge ${cls}" title="${esc(t.hits+' USPTO hits')}">${label}</span>`;
}
function vibeLabel(k){ return (state.vibes[k]||{}).label || k; }

let pending=false;
function bump(){ if(pending) return; pending=true; requestAnimationFrame(()=>{ pending=false; render(); }); }

function render(){
  const counts={AVAILABLE:0,REGISTERED:0,RATE_LIMITED:0,UNKNOWN:0};
  for(const r of state.results.values()) counts[r.status]++;
  $('nTotal').textContent=state.total;
  $('nAvailable').textContent=counts.AVAILABLE;
  $('nRegistered').textContent=counts.REGISTERED;
  $('nRate').textContent=counts.RATE_LIMITED;
  $('nUnknown').textContent=counts.UNKNOWN;
  const pct=state.total?Math.round(state.results.size/state.total*100):0;
  $('bar').style.width=pct+'%';
  $('barPct').textContent=state.results.size+' / '+state.total;

  let rows=[...state.results.values()];
  if(state.filter!=='ALL') rows=rows.filter(r=>r.status===state.filter);
  rows.sort((a,b)=>(ORDER[a.status]-ORDER[b.status])||(b.score-a.score)||a.domain.localeCompare(b.domain));
  const cap=400, shown=rows.slice(0,cap);
  const frag=document.createDocumentFragment();
  for(const r of shown){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="mono">${esc(r.domain)}</td>
      <td><span class="badge st-${r.status.toLowerCase()}" title="${esc(r.detail||'')}">${r.status}</span><span class="src">${esc(r.source||'')}</span></td>
      <td class="num">${r.score}</td>
      <td>${esc(vibeLabel(r.kind))}${r.why?`<div class="why">${esc(r.why)}</div>`:''}</td>
      <td>${tmBadge(r.name)}</td>`;
    frag.appendChild(tr);
  }
  $('tbody').replaceChildren(frag);
  $('rowCount').textContent=shown.length?`showing ${shown.length} of ${rows.length}`:'';
}

function handleFrame(frame){
  let ev='message', data='';
  for(const line of frame.split('\n')){
    const l=line.trim();
    if(l.startsWith('event:')) ev=l.slice(6).trim();
    else if(l.startsWith('data:')) data+=l.slice(5).trim();
  }
  if(!data) return;
  let p; try{ p=JSON.parse(data); }catch{ return; }
  if(ev==='stage'){ $('stage').textContent=p.message; }
  else if(ev==='meta'){ state.total=p.total; if(p.concepts) renderRelated(p.concepts); $('stage').textContent='checking domains...'; bump(); }
  else if(ev==='result'){ state.results.set(p.domain,p); bump(); }
  else if(ev==='tm'){ state.tm.set(p.name,p); $('stage').textContent='screening trademarks...'; bump(); }
  else if(ev==='warn'){ toast(p.message); }
  else if(ev==='error'){ toast(p.message); }
  else if(ev==='done'){ $('stage').textContent=''; }
}

async function run(){
  const seeds=seedWords();
  if(!seeds.length){ toast('Add at least one seed word'); return; }
  if(!selectedVibes.size){ toast('Pick at least one naming style'); return; }
  const tlds=[...selectedTlds, ...$('customTlds').value.split(',').map(x=>x.trim().replace(/^\./,'')).filter(Boolean)];
  if(!tlds.length){ toast('Pick at least one TLD'); return; }
  const payload={ seeds, tlds, vibes:[...selectedVibes], per_vibe:+$('perVibe').value,
    use_ai:$('useAi').checked, salt:Math.floor(Math.random()*1e9),
    concurrency:+$('concurrency').value, trademark:$('trademark').checked,
    trademark_limit:+$('tmLimit').value, offline:$('offline').checked, hacks:$('hacks').checked,
    min_score:+$('minScore').value, limit:(+$('limit').value)||0 };
  state.results.clear(); state.tm.clear(); state.total=0; state.filter='ALL';
  document.querySelectorAll('#filters .pill').forEach(p=>p.classList.toggle('active',p.dataset.f==='ALL'));
  render();
  $('run').disabled=true; $('cancel').disabled=false;
  $('exportCsv').disabled=true; $('exportJson').disabled=true;
  $('stage').textContent=payload.use_ai?'asking AI for ideas...':'generating names...';
  const t0=performance.now();
  state.controller=new AbortController();
  try{
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload),signal:state.controller.signal});
    if(!res.ok){ toast('Error: '+res.status); return; }
    const reader=res.body.getReader(); const dec=new TextDecoder(); let buf='';
    for(;;){
      const {done,value}=await reader.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      let i;
      while((i=buf.indexOf('\n\n'))>=0){ handleFrame(buf.slice(0,i)); buf=buf.slice(i+2); }
    }
  }catch(err){
    if(err.name!=='AbortError') toast('Error: '+err.message);
  }finally{
    $('run').disabled=false; $('cancel').disabled=true; $('stage').textContent='';
    $('elapsed').textContent=((performance.now()-t0)/1000).toFixed(1)+'s';
    if(state.results.size){ $('exportCsv').disabled=false; $('exportJson').disabled=false; }
    bump();
  }
}

function rowsForExport(){
  let rows=[...state.results.values()];
  rows.sort((a,b)=>(ORDER[a.status]-ORDER[b.status])||(b.score-a.score)||a.domain.localeCompare(b.domain));
  return rows.map(r=>({domain:r.domain,name:r.name,tld:r.tld,status:r.status,score:r.score,style:vibeLabel(r.kind),why:r.why||'',
    trademark:(state.tm.get(r.name)||{}).risk||'', tm_hits:(state.tm.get(r.name)||{}).hits||''}));
}
function download(name, content, type){
  const blob=new Blob([content],{type}); const url=URL.createObjectURL(blob);
  const a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}
function toCsv(rows){
  if(!rows.length) return '';
  const keys=Object.keys(rows[0]);
  const q=(v)=>'"'+String(v).replace(/"/g,'""')+'"';
  return keys.join(',')+'\n'+rows.map(r=>keys.map(k=>q(r[k])).join(',')).join('\n');
}

$('seeds').addEventListener('input',()=>{ renderChips(); scheduleInspire(); });
$('perVibe').addEventListener('input',()=>$('perVibeVal').textContent=$('perVibe').value);
$('concurrency').addEventListener('input',()=>$('concurrencyVal').textContent=$('concurrency').value);
$('minScore').addEventListener('input',()=>$('minScoreVal').textContent=$('minScore').value);
$('run').addEventListener('click',run);
$('cancel').addEventListener('click',()=>{ if(state.controller){state.controller.abort();} });
$('exportCsv').addEventListener('click',()=>download('namestack.csv',toCsv(rowsForExport()),'text/csv'));
$('exportJson').addEventListener('click',()=>download('namestack.json',JSON.stringify(rowsForExport(),null,2),'application/json'));
$('aiConfirm').addEventListener('click',confirmAi);
$('aiClear').addEventListener('click',clearAi);
$('filters').addEventListener('click',(e)=>{
  const p=e.target.closest('.pill'); if(!p) return;
  document.querySelectorAll('#filters .pill').forEach(x=>x.classList.toggle('active',x===p));
  state.filter=p.dataset.f; render();
});

(async function init(){
  buildTlds(); renderChips(); render();
  try{
    const meta=await (await fetch('/api/meta')).json();
    state.vibes=meta.vibes; state.providers=meta.providers;
    meta.default_vibes.forEach(v=>selectedVibes.add(v));
    buildVibes(); buildProviders(); applyProviderDefaults(true);
    if(meta.ai){ setAiState(meta.ai); return; }
    const saved=store.get();
    if(saved){
      $('aiProvider').value=saved.provider; applyProviderDefaults(true);
      $('aiModel').value=saved.model||$('aiModel').value; $('aiBase').value=saved.base_url||$('aiBase').value;
      $('aiRemember').checked=true;
      try{ setAiState(await postJson('/api/ai/config',saved)); }catch(err){ setAiState(null); toast('Saved AI key: '+err.message); }
    }
  }catch(err){ toast('Could not load settings: '+err.message); }
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "namestack/0.2"

    def log_message(self, _fmt: str, *_args) -> None:  # keep the console quiet
        return

    # -- helpers ----------------------------------------------------------
    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status: int = 200) -> None:
        self._send_bytes(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def _same_origin(self) -> bool:
        """Reject cross-site POSTs so other web pages can't drive the local API."""
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/health":
            self._send_json({"ok": True, "app": "namestack", "version": "0.2.0"})
        elif path == "/api/meta":
            cfg = ai.current()
            self._send_json({
                "vibes": {k: {"label": v.label, "examples": v.examples, "blurb": v.blurb} for k, v in VIBES.items()},
                "default_vibes": list(DEFAULT_VIBES),
                "providers": ai.PROVIDERS,
                "ai": cfg.public() if cfg else None,
            })
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._same_origin():
            self._send_json({"error": "cross-origin request refused"}, 403)
            return
        try:
            params = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"bad request: {exc}"}, 400)
            return

        if path == "/api/inspire":
            seeds = _normalize_seeds(params.get("seeds", ""))
            self._send_json({"concepts": expand(seeds).as_dict()})
        elif path == "/api/ai/config":
            try:
                cfg = ai.configure(
                    str(params.get("provider", "")), str(params.get("api_key", "")),
                    str(params.get("model", "")), str(params.get("base_url", "")),
                )
            except ai.AIError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(cfg.public())
        elif path == "/api/ai/clear":
            ai.clear()
            self._send_json({"ok": True})
        elif path == "/api/run":
            self._stream_run(params)
        else:
            self.send_error(404)

    def _stream_run(self, params: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

        closed = threading.Event()

        def emit(event: str, data) -> None:
            if closed.is_set():
                return
            frame = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
            try:
                self.wfile.write(frame)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                closed.set()

        try:
            _run_pipeline(params, emit)
        except Exception as exc:  # noqa: BLE001 - surface anything to the UI
            emit("error", {"message": f"{type(exc).__name__}: {exc}"})


def _normalize_seeds(raw) -> list[str]:
    if isinstance(raw, str):
        return [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
    return [str(s).strip() for s in raw if str(s).strip()]


def _normalize_tlds(raw) -> list[str]:
    if isinstance(raw, str):
        items = raw.replace(";", ",").split(",")
    else:
        items = [str(t) for t in raw]
    return [t.strip().lstrip(".").lower() for t in items if t.strip()]


def _build_ideas(seeds, vibes, per_vibe, salt, use_ai, emit) -> tuple[list[Idea], dict]:
    """Local vibe ideas, plus LLM ideas (listed first in each vibe) when enabled."""
    ai_data = None
    if use_ai and ai.current() is not None:
        emit("stage", {"message": "asking AI for ideas..."})
        try:
            ai_data = ai.brainstorm(seeds, vibes, per_vibe=max(5, per_vibe // 2))
        except ai.AIError as exc:
            emit("warn", {"message": f"AI brainstorm failed, using built-in ideas only: {exc}"})
    concepts = expand(seeds, ai_data)
    local = ideas_for(concepts, vibes, per_vibe=per_vibe, salt=salt)

    ideas: list[Idea] = []
    for vibe in vibes:
        if ai_data:
            ideas += [Idea(n["name"], vibe, f"AI: {n['why']}" if n["why"] else "AI idea")
                      for n in ai_data["names"] if n["vibe"] == vibe]
        ideas += [i for i in local if i.vibe == vibe]
    return ideas, concepts.as_dict()


def _run_pipeline(params: dict, emit) -> None:
    seeds = _normalize_seeds(params.get("seeds", ""))
    tlds = _normalize_tlds(params.get("tlds", ["com", "io", "ai"]))
    if not seeds:
        emit("error", {"message": "Add at least one seed word."})
        return
    if not tlds:
        tlds = ["com", "io", "ai"]
    vibes = [v for v in params.get("vibes") or DEFAULT_VIBES if v in VIBES]
    if not vibes:
        emit("error", {"message": "Pick at least one naming style."})
        return

    concurrency = max(1, int(params.get("concurrency", 20)))
    offline = bool(params.get("offline", False))
    trademark = bool(params.get("trademark", True))
    trademark_limit = int(params.get("trademark_limit", 20))
    min_score = int(params.get("min_score", 0))
    include_hacks = bool(params.get("hacks", True))
    limit = int(params.get("limit") or 0) or None
    per_vibe = max(1, min(100, int(params.get("per_vibe", 20))))
    salt = int(params.get("salt") or random.randrange(1 << 30))
    use_ai = bool(params.get("use_ai", False)) and not offline

    ideas, concepts = _build_ideas(seeds, vibes, per_vibe, salt, use_ai, emit)
    candidates = generate(
        seeds,
        tlds,
        include_hacks=include_hacks,
        min_score=min_score,
        max_candidates=limit,
        ideas=ideas,
    )
    emit("meta", {"total": len(candidates), "seeds": seeds, "tlds": tlds, "concepts": concepts})
    if not candidates:
        emit("error", {"message": "No candidates generated. Lower min score or add seeds."})
        return

    by_domain = {c.domain: c for c in candidates}
    checker = AvailabilityChecker(concurrency=concurrency, dry_run=offline)
    asyncio.run(_async_checks(candidates, by_domain, checker, trademark, trademark_limit, offline, emit))


async def _async_checks(candidates, by_domain, checker, trademark, trademark_limit, offline, emit) -> None:
    results: dict[str, object] = {}

    async def on_result(res) -> None:
        results[res.domain] = res
        c = by_domain[res.domain]
        emit(
            "result",
            {
                "domain": res.domain,
                "name": c.name,
                "tld": c.tld,
                "status": res.status.value,
                "score": c.score,
                "kind": c.kind,
                "why": c.why,
                "source": res.source,
                "detail": res.detail,
            },
        )

    await checker.check_many([c.domain for c in candidates], on_result=on_result)

    if trademark:
        available = [
            c for c in candidates
            if results.get(c.domain) and results[c.domain].status is Status.AVAILABLE
        ]
        names = list(dict.fromkeys(c.name for c in available))
        targets = names[:trademark_limit] if trademark_limit > 0 else names
        if targets:
            async def on_tm(tres) -> None:
                emit(
                    "tm",
                    {"name": tres.word, "risk": tres.risk.value,
                     "hits": tres.total_hits, "exact": tres.exact_match},
                )

            await check_words(
                targets,
                concurrency=min(5, checker.concurrency),
                dry_run=offline,
                on_result=on_tm,
            )

    counts = Counter(r.status.value for r in results.values())
    emit(
        "done",
        {"summary": dict(counts), "checked": len(results), "total": len(candidates)},
    )


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"namestack web UI: http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _open_browser(url: str, delay: float = 0.6) -> None:
    import time

    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - browser opening is best-effort
        pass


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Launch the namestack web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8787, help="Port (default 8787).")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
