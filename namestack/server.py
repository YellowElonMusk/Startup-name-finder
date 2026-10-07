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
from .inpi import check_names as check_fr_names
from .inspire import DEFAULT_VIBES, VIBES, Idea, expand, ideas_for
from .trademark import check_words

__all__ = ["INDEX_HTML", "Handler", "serve", "main"]

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>namestack</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap">
<script>
try{ const t=localStorage.getItem('namestack.theme'); if(t==='light'||t==='dark') document.documentElement.dataset.theme=t; }catch{}
</script>
<style>
:root{
  --bg:#fff; --card:#fff; --field:#f1f3f4; --hover:rgba(60,64,67,.08); --sep:#dadce0; --text:#202124; --muted:#5f6368;
  --accent:#1a73e8; --on-accent:#fff; --accent-soft:#e8f0fe; --accent-text:#1967d2; --link:#1a0dab;
  --green:#188038; --red:#d93025; --orange:#b06000; --gray:#5f6368;
  --lift:0 1px 6px rgba(32,33,36,.28); --menu-shadow:0 2px 10px rgba(32,33,36,.2);
  --tip-bg:#3c4043; --tip-text:#fff; color-scheme:light;
}
:root[data-theme="dark"]{
  --bg:#202124; --card:#303134; --field:#303134; --hover:rgba(232,234,237,.08); --sep:#5f6368; --text:#e8eaed; --muted:#9aa0a6;
  --accent:#8ab4f8; --on-accent:#202124; --accent-soft:#394457; --accent-text:#d2e3fc; --link:#8ab4f8;
  --green:#81c995; --red:#f28b82; --orange:#fdd663; --gray:#9aa0a6;
  --lift:0 1px 6px rgba(0,0,0,.5); --menu-shadow:0 2px 10px rgba(0,0,0,.5);
  --tip-bg:#e8eaed; --tip-text:#202124; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);min-height:100vh;transition:background .2s,color .2s;
  font-family:"Google Sans",Roboto,Arial,sans-serif}
button,input,select{font-family:inherit;color:inherit}
.topbar{display:flex;justify-content:flex-end;align-items:center;padding:10px 16px}
.icon-btn{width:40px;height:40px;border-radius:50%;border:0;background:transparent;display:grid;place-items:center;cursor:pointer;color:var(--muted)}
.icon-btn:hover{background:var(--hover)}
.icon-btn svg{width:22px;height:22px;fill:currentColor}
.wrap{max-width:780px;margin:0 auto;padding:28px 16px 80px}
.hero{text-align:center;margin-bottom:26px}
.logo{font-size:64px;line-height:1;font-weight:500;letter-spacing:-.02em;margin:0 0 14px}
.logo span{color:var(--accent)}
.hero p{font-size:16px;color:var(--muted);margin:0 auto;max-width:560px;line-height:1.5}

.search{display:flex;align-items:flex-start;gap:14px;background:var(--card);border:1px solid var(--sep);border-radius:24px;
  padding:4px 22px;transition:box-shadow .15s,border-color .15s}
.search:hover,.search:focus-within{box-shadow:var(--lift);border-color:transparent}
.search .mag{width:20px;height:20px;fill:var(--muted);flex:none;margin-top:30px}
.fields{flex:1;min-width:0}
.fld{display:block;padding:10px 0;cursor:text}
.fld+.fld{border-top:1px solid var(--sep)}
.fld .lbl{display:block;font-size:12px;font-weight:500;color:var(--muted)}
.search input{width:100%;border:0;outline:0;background:transparent;font-size:16px;padding:4px 0 0}
.search input::placeholder{color:var(--muted);opacity:.75}
.actions{display:flex;justify-content:center;margin-top:24px}
.btn{border:0;border-radius:20px;font-size:14px;font-weight:500;cursor:pointer;transition:background .15s,box-shadow .15s;letter-spacing:.01em}
.btn-primary{background:var(--accent);color:var(--on-accent);padding:0 26px;height:40px;white-space:nowrap}
.btn-primary:hover{box-shadow:0 1px 3px rgba(60,64,67,.3),0 4px 8px 3px rgba(60,64,67,.15)}
.btn-primary.stop{background:var(--field);color:var(--text);border:1px solid var(--sep)}
.btn-plain{background:transparent;border:1px solid var(--sep);color:var(--accent);padding:0 18px;height:36px}
.btn-plain:hover{background:var(--hover)}
.btn-plain:disabled{opacity:.4;cursor:default}
.words{min-height:20px;margin:14px 4px 0;font-size:13px;color:var(--muted);text-align:center;line-height:1.7}
.words b{font-weight:500;color:var(--text);margin-right:4px}
.words .w{white-space:nowrap}

.section-label{font-size:14px;font-weight:500;color:var(--muted);text-align:center;margin:30px 4px 12px}
.styles{display:flex;flex-wrap:wrap;gap:8px;justify-content:center}
.chip{cursor:pointer;user-select:none;border:1px solid var(--sep);background:transparent;border-radius:8px;height:32px;padding:0 14px;
  font-size:14px;font-weight:500;color:var(--muted);transition:background .15s,border-color .15s,color .15s;display:inline-flex;align-items:center}
.chip:hover{background:var(--hover)}
.chip.on{background:var(--accent-soft);border-color:transparent;color:var(--accent-text)}
.chip.on::before{content:"\2713";margin-right:6px;font-weight:700}
.chip .flag{font-size:11px;font-weight:700;opacity:.7;margin-left:6px;letter-spacing:.03em}

.group{background:var(--card);border:1px solid var(--sep);border-radius:8px;overflow:hidden;margin-top:30px}
.group details+details{border-top:1px solid var(--sep)}
.group summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:14px 18px;font-size:15px}
.group summary:hover{background:var(--hover)}
.group summary::-webkit-details-marker{display:none}
.group summary .t{font-weight:500}
.group summary .v{margin-left:auto;color:var(--muted);font-size:14px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.group summary .v.ok{color:var(--green)}
.group summary::after{content:"";width:7px;height:7px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);
  transform:rotate(45deg);transition:transform .2s;flex:none;margin:0 2px 4px 4px}
.group details[open] summary::after{transform:rotate(-135deg);margin-bottom:-4px}
.panel{padding:6px 18px 18px;display:grid;gap:14px}
.panel .hint{font-size:13px;color:var(--muted);margin:0;line-height:1.5}
.line{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.line label{font-size:14px}
.line .grow{flex:1}
.field{background:transparent;border:1px solid var(--sep);border-radius:4px;padding:9px 12px;font-size:14px;outline:0}
.field:focus{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
select.field{background:var(--card)}
input[type=range]{accent-color:var(--accent);width:150px}
input[type=number].field{width:84px}
.val{font-variant-numeric:tabular-nums;color:var(--muted);font-size:14px;min-width:28px}
.switch{position:relative;display:inline-flex;align-items:center;gap:12px;cursor:pointer;font-size:14px}
.switch input{appearance:none;-webkit-appearance:none;width:36px;height:14px;border-radius:999px;background:var(--sep);
  position:relative;cursor:pointer;transition:background .2s;margin:0 4px;flex:none;border:0}
.switch input::after{content:"";position:absolute;top:-3px;left:-4px;width:20px;height:20px;border-radius:50%;background:#fff;
  box-shadow:0 1px 3px rgba(0,0,0,.4);transition:transform .2s,background .2s}
.switch input:checked{background:color-mix(in srgb,var(--accent) 50%,transparent)}
.switch input:checked::after{transform:translateX(24px);background:var(--accent)}
.switch input:disabled{opacity:.4;cursor:default}
.tlds{display:flex;flex-wrap:wrap;gap:6px}
.tlds .chip{height:30px;padding:0 11px;font-size:13px}
.ai-grid{display:grid;grid-template-columns:110px 1fr;gap:10px;align-items:center}
.ai-grid label{font-size:14px;color:var(--muted)}

#results{display:none;margin-top:44px}
#results.show{display:block}
.progress{height:4px;background:var(--accent-soft);border-radius:999px;overflow:hidden}
#bar{height:100%;width:0;background:var(--accent);transition:width .25s}
.meta{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin:8px 2px 18px}
.picks{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:26px}
.pick{background:var(--card);border:1px solid var(--sep);border-radius:8px;padding:16px 18px}
.pick .d{font-size:20px;color:var(--link);word-break:break-all}
.pick .s{font-size:13px;color:var(--muted);margin-top:6px;line-height:1.45}
.pick .tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.toolbar{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;margin-bottom:14px;border-bottom:1px solid var(--sep)}
.seg{display:inline-flex;flex-wrap:wrap}
.seg button{border:0;background:transparent;padding:10px 14px 9px;font-size:14px;cursor:pointer;color:var(--muted);
  border-bottom:3px solid transparent;margin-bottom:-1px}
.seg button:hover{color:var(--text)}
.seg button.on{color:var(--accent);border-bottom-color:var(--accent);font-weight:500}
.seg .n{font-variant-numeric:tabular-nums;margin-left:6px;opacity:.75}
.menu{position:relative;margin:0 0 7px auto}
.menu summary{list-style:none;display:inline-flex;align-items:center}
.menu summary::-webkit-details-marker{display:none}
.menu .items{position:absolute;right:0;top:calc(100% + 6px);background:var(--card);border-radius:4px;
  box-shadow:var(--menu-shadow);padding:8px 0;min-width:200px;z-index:20}
.menu .items button{display:block;width:100%;text-align:left;border:0;background:transparent;padding:10px 16px;font-size:14px;cursor:pointer}
.menu .items button:hover{background:var(--hover)}
.menu.disabled summary{opacity:.4;pointer-events:none}
.table-card{background:var(--card);border:1px solid var(--sep);border-radius:8px;overflow:hidden}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
thead th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:12px 14px;border-bottom:1px solid var(--sep);white-space:nowrap}
tbody td{padding:11px 14px;border-bottom:1px solid var(--sep);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--hover)}
.dom{color:var(--link);font-size:16px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.why{font-size:12px;color:var(--muted);margin-top:2px}
.badge{display:inline-block;padding:3px 9px;border-radius:4px;font-size:12px;font-weight:500;white-space:nowrap}
.b-green{background:color-mix(in srgb,var(--green) 14%,transparent);color:var(--green)}
.b-red{background:color-mix(in srgb,var(--red) 13%,transparent);color:var(--red)}
.b-orange{background:color-mix(in srgb,var(--orange) 16%,transparent);color:var(--orange)}
.b-gray{background:color-mix(in srgb,var(--gray) 15%,transparent);color:var(--gray)}
.b-none{color:var(--gray)}
.ext{font-size:12px;color:var(--link);text-decoration:none;margin-left:6px;white-space:nowrap}
.ext:hover{text-decoration:underline}
.col-fr{display:none}
.has-fr .col-fr{display:table-cell}
.rowcount{color:var(--muted);font-size:12px;padding:10px 14px}
.empty{padding:28px;text-align:center;color:var(--muted);font-size:14px}

#tip{position:fixed;z-index:100;max-width:280px;background:var(--tip-bg);color:var(--tip-text);font-size:12px;line-height:1.45;
  padding:7px 10px;border-radius:4px;pointer-events:none;opacity:0;transition:opacity .15s}
#tip.show{opacity:1}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--tip-bg);color:var(--tip-text);
  border-radius:4px;padding:14px 16px;font-size:14px;display:none;max-width:calc(100vw - 32px);z-index:60;box-shadow:var(--menu-shadow)}
@media (max-width:640px){
  .wrap{padding-top:12px}
  .logo{font-size:44px}.hero p{font-size:15px}
  .search{padding:4px 16px}
  .search .mag{display:none}
  .btn-primary{width:100%}
  .ai-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="topbar">
  <button class="icon-btn" id="themeBtn" type="button" aria-label="Switch to dark mode" data-tip="Switch to dark mode.">
    <svg id="iconMoon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12.3 22c-5.6 0-10.1-4.5-10.1-10.1 0-4.6 3-8.5 7.3-9.7.5-.1.9.4.7.9-.4 1-.6 2.1-.6 3.2 0 4.9 4 8.9 8.9 8.9 1.1 0 2.2-.2 3.2-.6.5-.2 1 .2.9.7C21.4 19.2 17.2 22 12.3 22z"/></svg>
    <svg id="iconSun" viewBox="0 0 24 24" aria-hidden="true" style="display:none"><path d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0-5a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0V3a1 1 0 0 1 1-1zm0 17a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0v-2a1 1 0 0 1 1-1zM3 11h2a1 1 0 1 1 0 2H3a1 1 0 1 1 0-2zm16 0h2a1 1 0 1 1 0 2h-2a1 1 0 1 1 0-2zM5.6 4.2l1.4 1.4a1 1 0 0 1-1.4 1.4L4.2 5.6a1 1 0 0 1 1.4-1.4zm12.8 12.8 1.4 1.4a1 1 0 0 1-1.4 1.4L17 18.4a1 1 0 0 1 1.4-1.4zM4.2 18.4 5.6 17A1 1 0 0 1 7 18.4l-1.4 1.4a1 1 0 0 1-1.4-1.4zM17 5.6l1.4-1.4a1 1 0 0 1 1.4 1.4L18.4 7A1 1 0 0 1 17 5.6z"/></svg>
  </button>
</div>
<div class="wrap">
  <div class="hero">
    <h1 class="logo">name<span>stack</span></h1>
    <p>Find your startup name. Give us words you love and three words about what you're building: we'll invent names, check the domains and screen trademarks.</p>
  </div>

  <div class="search">
    <svg class="mag" viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 9.5 16a6.5 6.5 0 0 0 4.2-1.6l.3.3v.8l5 5 1.5-1.5-5-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"/></svg>
    <div class="fields">
      <label class="fld" data-tip="Your favorite words: ones that mean something to you or just sound cool. Separate them with commas.">
        <span class="lbl">Words you love</span>
        <input type="text" id="loves" placeholder="aurora, wolf, velvet, jazz" autocomplete="off"></label>
      <label class="fld" data-tip="Three words that best describe what you're building, not a pitch. Separate them with commas.">
        <span class="lbl">What you're building, in 3 words</span>
        <input type="text" id="seeds" placeholder="coffee, friends, morning" autocomplete="off"></label>
    </div>
  </div>
  <div class="words" id="related"></div>
  <div class="actions">
    <button class="btn btn-primary" id="run" data-tip="Generate names in the styles below, check every domain live, then screen the free ones for trademarks.">Find names</button>
  </div>

  <div class="section-label">Naming styles</div>
  <div class="styles" id="vibes"></div>

  <div class="group">
    <details>
      <summary data-tip="Which domain endings to check (.com, .io, ...)."><span class="t">Domains</span><span class="v" id="sumTlds"></span></summary>
      <div class="panel">
        <div class="tlds" id="tlds"></div>
        <input type="text" class="field" id="customTlds" placeholder="Other endings, comma separated (e.g. eu, studio)"
          data-tip="Add any other domain endings to check, separated by commas.">
        <label class="switch" data-tip="Also try names that spell a word across the dot, like spoti.fi or bit.ly."><input type="checkbox" id="hacks" checked> Domain hacks (spoti.fi)</label>
      </div>
    </details>
    <details>
      <summary data-tip="How many names to make and which safety checks to run."><span class="t">Search settings</span><span class="v" id="sumSettings"></span></summary>
      <div class="panel">
        <div class="line"><label for="perVibe" class="grow" data-tip="How many names to create for each selected style.">Names per style</label>
          <input type="range" id="perVibe" min="5" max="50" value="20"><span class="val" id="perVibeVal">20</span></div>
        <div class="line"><label for="minScore" class="grow" data-tip="Hide names below this brandability score (short, pronounceable, easy to spell).">Minimum brand score</label>
          <input type="range" id="minScore" min="0" max="100" value="0"><span class="val" id="minScoreVal">0</span></div>
        <div class="line"><label class="switch grow" data-tip="Check names with a free domain against the US trademark office (USPTO).">
          <input type="checkbox" id="trademark" checked> US trademark screen</label>
          <label for="tmLimit" data-tip="How many names to screen for trademarks. 0 means every available name.">Screen up to</label>
          <input type="number" class="field" id="tmLimit" value="20" min="0"></div>
        <div class="line"><label for="limit" class="grow" data-tip="Cap the total number of domains checked. 0 means no cap.">Max domains to check</label>
          <input type="number" class="field" id="limit" value="0" min="0"></div>
        <div class="line"><label for="concurrency" class="grow" data-tip="How many domains to check at once. Higher is faster but registries may throttle you.">Parallel checks</label>
          <input type="range" id="concurrency" min="1" max="100" value="20"><span class="val" id="concurrencyVal">20</span></div>
        <label class="switch" data-tip="Simulate every check without touching the network. Useful for trying the app; results are fake."><input type="checkbox" id="offline"> Offline demo (fake results)</label>
      </div>
    </details>
    <details id="aiCard">
      <summary data-tip="Optional: plug in your own AI key for smarter, more creative names."><span class="t">AI boost</span><span class="v" id="aiStatus">Off</span></summary>
      <div class="panel">
        <p class="hint">Paste an API key from your AI provider to brainstorm open-vocabulary names in every style. The key stays on this computer and is only sent to the provider you pick. Each run costs a few cents at most.</p>
        <div class="ai-grid">
          <label for="aiProvider">Provider</label><select class="field" id="aiProvider" data-tip="The company whose AI model will brainstorm names."></select>
          <label for="aiKey">API key</label><input type="password" class="field" id="aiKey" placeholder="sk-..." autocomplete="off" data-tip="Your secret key from the provider's dashboard.">
          <label for="aiModel">Model</label><input type="text" class="field" id="aiModel" data-tip="Which model to use. The default is a good choice.">
          <label for="aiBase" id="aiBaseLabel">Base URL</label><input type="text" class="field" id="aiBase" data-tip="API address. Only change it for self-hosted or custom providers.">
        </div>
        <div class="line">
          <label class="switch" data-tip="Keep the key in this browser so AI unlocks automatically next time."><input type="checkbox" id="aiRemember"> Remember on this device</label>
          <span class="grow"></span>
          <button class="btn btn-plain" id="aiClear" disabled data-tip="Forget the key and turn AI off.">Disconnect</button>
          <button class="btn btn-primary" id="aiConfirm" data-tip="Test the key with your provider and turn AI on.">Connect</button>
        </div>
        <label class="switch" data-tip="Turn AI ideas on or off for the next search without removing your key."><input type="checkbox" id="useAi" disabled> Use AI for the next search</label>
      </div>
    </details>
  </div>

  <div id="results">
    <div class="progress"><div id="bar"></div></div>
    <div class="meta"><span id="stage"></span><span id="elapsed"></span></div>
    <div class="section-label" id="picksLabel" style="display:none;margin-top:0">Top picks</div>
    <div class="picks" id="picks"></div>
    <div class="toolbar">
      <div class="seg" id="filters">
        <button class="on" data-f="ALL" data-tip="Show every domain checked.">All<span class="n" id="nAll">0</span></button>
        <button data-f="AVAILABLE" data-tip="Domains nobody owns: you can register these today.">Available<span class="n" id="nAvailable">0</span></button>
        <button data-f="REGISTERED" data-tip="Domains someone already owns.">Taken<span class="n" id="nRegistered">0</span></button>
        <button data-f="OTHER" data-tip="The registry didn't give a clear answer (rate-limited or unreachable). Try again later.">Unclear<span class="n" id="nOther">0</span></button>
      </div>
      <details class="menu disabled" id="exportMenu">
        <summary class="btn btn-plain" data-tip="Download the results as a spreadsheet (CSV) or as JSON.">Export</summary>
        <div class="items">
          <button id="exportCsv">Spreadsheet (.csv)</button>
          <button id="exportJson">JSON (.json)</button>
        </div>
      </details>
    </div>
    <div class="table-card" id="tableCard">
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Domain</th><th>Status</th>
          <th class="num"><span data-tip="Brandability from 0 to 100: short, pronounceable, easy to spell.">Score</span></th>
          <th>Style</th>
          <th><span data-tip="US trademark office (USPTO) screen of names with a free domain.">Trademark</span></th>
          <th class="col-fr"><span data-tip="French company register check (the national register shown on data.inpi.fr). Click INPI to confirm trademarks.">France</span></th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
      </div>
      <div class="rowcount" id="rowCount"></div>
    </div>
  </div>
</div>
<div id="tip" role="tooltip"></div>
<div id="toast" role="status"></div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { results:new Map(), tm:new Map(), fr:new Map(), france:false, total:0, filter:'ALL', controller:null, running:false, vibes:{}, providers:{}, ai:null };
const ORDER = { AVAILABLE:0, RATE_LIMITED:1, UNKNOWN:2, REGISTERED:3 };
const TLD_ORDER = ['com','io','ai','fr','dev','app','co','net','org','tech','xyz','me','sh','ly','gg','fm','us','it','to','tv'];
const selectedTlds = new Set(['com','io','ai']);
const selectedVibes = new Set();
const STATUS = { AVAILABLE:['Available','b-green'], REGISTERED:['Taken','b-red'], RATE_LIMITED:['Busy','b-orange'], UNKNOWN:['Unclear','b-gray'] };
const TM = { NONE:['Clear','b-green','No similar US trademark found'], LOW:['Low risk','b-green','Related US trademarks exist, none look alike'],
  MEDIUM:['Similar','b-orange','A US trademark sounds alike'], HIGH:['Exact match','b-red','A US trademark with this exact name exists'],
  UNKNOWN:['?','b-gray','The USPTO did not answer'] };
const FR = { FREE:['Free','b-green'], CLOSED:['Used before','b-orange'], TAKEN:['Taken','b-red'], UNKNOWN:['?','b-gray'] };
const LS_KEY = 'namestack.ai';
const store = {
  get(){ try{ return JSON.parse(localStorage.getItem(LS_KEY)||'null'); }catch{ return null; } },
  set(v){ try{ localStorage.setItem(LS_KEY, JSON.stringify(v)); }catch{} },
  del(){ try{ localStorage.removeItem(LS_KEY); }catch{} },
};

// Hover help: show an element's data-tip after 2 s of hovering, hide as soon as the cursor leaves it.
const tip = { el:null, timer:null, target:null };
function hideTip(){ clearTimeout(tip.timer); tip.timer=null; tip.target=null; tip.el.classList.remove('show'); }
function showTip(target){
  const text=target.dataset.tip; if(!text || !document.contains(target)) return;
  tip.el.textContent=text; tip.el.classList.add('show');
  const r=target.getBoundingClientRect(), t=tip.el.getBoundingClientRect(), gap=8;
  let top=r.top-t.height-gap; if(top<8) top=r.bottom+gap;
  let left=r.left+r.width/2-t.width/2; left=Math.max(8,Math.min(left,window.innerWidth-t.width-8));
  tip.el.style.top=top+'px'; tip.el.style.left=left+'px';
}
document.addEventListener('mouseover',(e)=>{
  const target=e.target.closest('[data-tip]');
  if(target===tip.target) return;
  hideTip();
  if(!target) return;
  tip.target=target; tip.timer=setTimeout(()=>showTip(target),2000);
});
document.addEventListener('mouseout',(e)=>{
  if(tip.target && !tip.target.contains(e.relatedTarget)) hideTip();
});
['mousedown','scroll','keydown'].forEach(ev=>window.addEventListener(ev,()=>{ if(tip.target) hideTip(); },true));

function toast(msg){ const t=$('toast'); t.textContent=msg; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',5000); }
async function postJson(url, body){
  const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  let data={}; try{ data=await res.json(); }catch{}
  if(!res.ok) throw new Error(data.error||('HTTP '+res.status));
  return data;
}

function customTlds(){ return $('customTlds').value.split(',').map(x=>x.trim().replace(/^\./,'').toLowerCase()).filter(Boolean); }
function updateSummaries(){
  const tlds=[...selectedTlds, ...customTlds()];
  $('sumTlds').textContent=tlds.length?tlds.map(t=>'.'+t).join(' '):'none';
  const checks=[$('trademark').checked?'US trademarks':null, selectedVibes.has('french')?'France':null].filter(Boolean);
  $('sumSettings').textContent=`${$('perVibe').value} per style · ${checks.length?checks.join(' + '):'no screening'}${$('offline').checked?' · offline':''}`;
}
function buildTlds(){
  const wrap=$('tlds'); wrap.innerHTML='';
  for(const t of TLD_ORDER){
    const b=document.createElement('button'); b.type='button'; b.className='chip'+(selectedTlds.has(t)?' on':''); b.dataset.tld=t;
    b.textContent='.'+t; b.dataset.tip=`Check .${t} domains.`;
    b.onclick=()=>{ selectedTlds.has(t)?selectedTlds.delete(t):selectedTlds.add(t); b.classList.toggle('on');
      if(t==='fr') frAutoAdded=false;  // the user's own choice now; French style won't undo it
      updateSummaries(); };
    wrap.appendChild(b);
  }
}
// .fr added by turning on the French style (removed again only if it was us who added it).
let frAutoAdded=false;
function setTld(t,on){
  on?selectedTlds.add(t):selectedTlds.delete(t);
  const b=document.querySelector(`#tlds [data-tld="${t}"]`); if(b) b.classList.toggle('on',on);
}
function buildVibes(){
  const wrap=$('vibes'); wrap.innerHTML='';
  for(const [key,v] of Object.entries(state.vibes)){
    const b=document.createElement('button'); b.type='button'; b.className='chip'+(selectedVibes.has(key)?' on':'');
    b.dataset.tip=`${v.blurb} Like ${v.examples}.`; b.setAttribute('aria-pressed', selectedVibes.has(key));
    b.innerHTML=esc(v.label)+(key==='french'?'<span class="flag">FR</span>':'');
    b.onclick=()=>{
      const on=!selectedVibes.has(key); on?selectedVibes.add(key):selectedVibes.delete(key);
      b.classList.toggle('on',on); b.setAttribute('aria-pressed',on);
      if(key==='french'){
        if(on && !selectedTlds.has('fr')){ setTld('fr',true); frAutoAdded=true; }
        else if(!on && frAutoAdded){ setTld('fr',false); frAutoAdded=false; }
        scheduleInspire(); if(on) toast('French names will also be checked against the French company register.'); }
      updateSummaries();
    };
    wrap.appendChild(b);
  }
}
function seedWords(){
  const words=($('loves').value+','+$('seeds').value).split(/[,;]/).map(s=>s.trim()).filter(Boolean);
  return [...new Set(words.map(w=>w.toLowerCase()))];
}

function renderRelated(c){
  if(!c || !c.seeds.length){ $('related').innerHTML=''; return; }
  const row=(k,words)=>words.length?`<span class="w"><b>${k}</b>${words.slice(0,8).map(esc).join(', ')}</span>`:'';
  const parts=[row('Related',c.synonyms),row('Latin',c.latin),row('Greek',c.greek)];
  if(selectedVibes.has('french')) parts.push(row('French',c.french||[]));
  let html=parts.filter(Boolean).join(' &nbsp;·&nbsp; ');
  if(c.unknown.length) html+=(html?'<br>':'')+`No built-in match for ${c.unknown.map(esc).join(', ')}${state.ai?', AI will cover it.':'. Turn on AI boost for richer ideas.'}`;
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
    s.textContent=`${info.label} · On`; s.className='v ok';
    $('useAi').disabled=false; $('useAi').checked=true; $('aiClear').disabled=false;
  }else{
    s.textContent='Off'; s.className='v';
    $('useAi').disabled=true; $('useAi').checked=false; $('aiClear').disabled=true;
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
  $('aiConfirm').disabled=true; $('aiStatus').textContent='Checking key...'; $('aiStatus').className='v';
  try{
    const info=await postJson('/api/ai/config',body);
    if($('aiRemember').checked) store.set(body); else store.del();
    $('aiKey').value='';
    setAiState(info); toast('AI connected');
  }catch(err){ setAiState(null); toast(err.message); }
  finally{ $('aiConfirm').disabled=false; }
}
async function clearAi(){
  try{ await postJson('/api/ai/clear'); }catch{}
  store.del(); setAiState(null); toast('AI disconnected');
}

function badge(label, cls, tipText){ return `<span class="badge ${cls}"${tipText?` data-tip="${esc(tipText)}"`:''}>${esc(label)}</span>`; }
function tmBadge(name){
  const t=state.tm.get(name);
  if(!t) return '<span class="badge b-none">–</span>';
  const [label,cls,desc]=TM[t.risk]||[t.risk,'b-gray',''];
  return badge(label, cls, `${desc}. ${t.hits} related USPTO records.`);
}
function frCell(r){
  const f=state.fr.get(r.name);
  const link=`<a class="ext" href="${esc(f?f.url:inpiUrl(r.name))}" target="_blank" rel="noopener" data-tip="Open data.inpi.fr to confirm no French trademark uses this name.">INPI ↗</a>`;
  if(!f) return (r.status==='AVAILABLE'?'<span class="badge b-none">–</span>':'')+(r.status==='AVAILABLE'?link:'');
  const [label,cls]=FR[f.status]||[f.status,'b-gray'];
  const desc=f.status==='TAKEN'?`Used by an active French company: ${f.company}`:f.status==='CLOSED'?`Used by a French company that has closed: ${f.company}`:
    f.status==='FREE'?'No French company uses this exact name.':`Check failed (${f.detail}).`;
  return badge(label, cls, desc)+link;
}
function inpiUrl(name){
  const q=new URLSearchParams({advancedSearch:'{}',displayStyle:'List',filter:'{}',nbResultsPerPage:'20',order:'asc',page:'1',q:name,sort:'relevance',type:'brands'});
  return 'https://data.inpi.fr/search?'+q.toString();
}
function vibeLabel(k){ return (state.vibes[k]||{}).label || k; }

function sorted(rows){
  return rows.sort((a,b)=>(ORDER[a.status]-ORDER[b.status])||(b.score-a.score)||a.domain.localeCompare(b.domain));
}
function isSafe(r){
  const t=state.tm.get(r.name), f=state.fr.get(r.name);
  if(t && (t.risk==='HIGH' || t.risk==='MEDIUM')) return false;
  if(f && f.status==='TAKEN') return false;
  return true;
}
function renderPicks(){
  const picks=[], seen=new Set();
  for(const r of sorted([...state.results.values()].filter(r=>r.status==='AVAILABLE' && isSafe(r)))){
    if(seen.has(r.name)) continue; seen.add(r.name); picks.push(r);
    if(picks.length===3) break;
  }
  $('picksLabel').style.display=picks.length?'':'none';
  $('picks').innerHTML=picks.map(r=>{
    const tags=[badge('Domain free','b-green','Nobody owns this domain yet.')];
    if(state.tm.has(r.name)) tags.push(tmBadge(r.name));
    const f=state.fr.get(r.name); if(f){ const [l,c]=FR[f.status]; tags.push(badge('France: '+l,c)); }
    return `<div class="pick"><div class="d">${esc(r.domain)}</div><div class="s">${esc(vibeLabel(r.kind))}${r.why?' · '+esc(r.why):''}</div><div class="tags">${tags.join('')}</div></div>`;
  }).join('');
}

let pending=false;
function bump(){ if(pending) return; pending=true; requestAnimationFrame(()=>{ pending=false; render(); }); }

function render(){
  const counts={AVAILABLE:0,REGISTERED:0,OTHER:0};
  for(const r of state.results.values()) counts[r.status in counts?r.status:'OTHER']++;
  $('nAll').textContent=state.results.size; $('nAvailable').textContent=counts.AVAILABLE;
  $('nRegistered').textContent=counts.REGISTERED; $('nOther').textContent=counts.OTHER;
  const pct=state.total?Math.round(state.results.size/state.total*100):0;
  $('bar').style.width=(state.running?Math.max(pct,3):100)+'%';
  $('tableCard').classList.toggle('has-fr', state.france);

  let rows=[...state.results.values()];
  if(state.filter==='OTHER') rows=rows.filter(r=>r.status!=='AVAILABLE' && r.status!=='REGISTERED');
  else if(state.filter!=='ALL') rows=rows.filter(r=>r.status===state.filter);
  sorted(rows);
  const cap=400, shown=rows.slice(0,cap);
  const frag=document.createDocumentFragment();
  for(const r of shown){
    const tr=document.createElement('tr');
    const [sl,sc]=STATUS[r.status]||[r.status,'b-gray'];
    tr.innerHTML=`<td class="dom">${esc(r.domain)}</td>
      <td>${badge(sl, sc, r.detail?`${r.detail} (via ${r.source||'registry'})`:`Checked via ${r.source||'registry'}`)}</td>
      <td class="num">${r.score}</td>
      <td>${esc(vibeLabel(r.kind))}${r.why?`<div class="why">${esc(r.why)}</div>`:''}</td>
      <td>${tmBadge(r.name)}</td>
      <td class="col-fr">${frCell(r)}</td>`;
    frag.appendChild(tr);
  }
  $('tbody').replaceChildren(frag);
  $('rowCount').innerHTML=shown.length?`Showing ${shown.length} of ${rows.length}`:
    (state.results.size?'<div class="empty">Nothing in this filter.</div>':'');
  renderPicks();
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
  else if(ev==='meta'){ state.total=p.total; if(p.concepts) renderRelated(p.concepts); $('stage').textContent=`Checking ${p.total} domains...`; bump(); }
  else if(ev==='result'){ state.results.set(p.domain,p); bump(); }
  else if(ev==='tm'){ state.tm.set(p.name,p); bump(); }
  else if(ev==='fr'){ state.fr.set(p.name,p); bump(); }
  else if(ev==='warn' || ev==='error'){ toast(p.message); }
  else if(ev==='done'){ $('stage').textContent=''; }
}

function setRunning(on){
  state.running=on;
  const b=$('run'); b.textContent=on?'Stop':'Find names'; b.classList.toggle('stop',on);
  b.dataset.tip=on?'Stop checking. Results found so far are kept.':'Generate names in the styles below, check every domain live, then screen the free ones for trademarks.';
}
async function run(){
  if(state.running){ if(state.controller) state.controller.abort(); return; }
  const seeds=seedWords();
  if(!seeds.length){ toast("Add a few words you love, or three words about what you're building"); $('loves').focus(); return; }
  if(!selectedVibes.size){ toast('Pick at least one style'); return; }
  const tlds=[...selectedTlds, ...customTlds()];
  if(!tlds.length){ toast('Pick at least one domain ending under Domains'); return; }
  const payload={ seeds, tlds, vibes:[...selectedVibes], per_vibe:+$('perVibe').value,
    use_ai:$('useAi').checked, salt:Math.floor(Math.random()*1e9),
    concurrency:+$('concurrency').value, trademark:$('trademark').checked,
    trademark_limit:+$('tmLimit').value, offline:$('offline').checked, hacks:$('hacks').checked,
    min_score:+$('minScore').value, limit:(+$('limit').value)||0 };
  state.results.clear(); state.tm.clear(); state.fr.clear(); state.total=0; state.filter='ALL';
  state.france=selectedVibes.has('french');
  document.querySelectorAll('#filters button').forEach(p=>p.classList.toggle('on',p.dataset.f==='ALL'));
  document.querySelectorAll('.group details').forEach(d=>d.open=false);
  $('results').classList.add('show'); $('exportMenu').classList.add('disabled'); $('exportMenu').open=false;
  $('elapsed').textContent='';
  setRunning(true); render();
  $('results').scrollIntoView({behavior:'smooth',block:'start'});
  $('stage').textContent=payload.use_ai?'Asking AI for ideas...':'Inventing names...';
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
    setRunning(false); $('stage').textContent=state.results.size?'Done':'';
    $('elapsed').textContent=((performance.now()-t0)/1000).toFixed(1)+'s';
    if(state.results.size) $('exportMenu').classList.remove('disabled');
    bump();
  }
}

function rowsForExport(){
  return sorted([...state.results.values()]).map(r=>{
    const t=state.tm.get(r.name)||{}, f=state.fr.get(r.name)||{};
    const row={domain:r.domain,name:r.name,tld:r.tld,status:r.status,score:r.score,style:vibeLabel(r.kind),why:r.why||'',
      trademark:t.risk||'', tm_hits:t.hits||''};
    if(state.france){ row.france=f.status||''; row.france_company=f.company||''; row.inpi=inpiUrl(r.name); }
    return row;
  });
}
function download(name, content, type){
  const blob=new Blob([content],{type}); const url=URL.createObjectURL(blob);
  const a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
  $('exportMenu').open=false;
}
function toCsv(rows){
  if(!rows.length) return '';
  const keys=Object.keys(rows[0]);
  const q=(v)=>'"'+String(v).replace(/"/g,'""')+'"';
  return keys.join(',')+'\n'+rows.map(r=>keys.map(k=>q(r[k])).join(',')).join('\n');
}

for(const id of ['loves','seeds']){
  $(id).addEventListener('input',scheduleInspire);
  $(id).addEventListener('keydown',(e)=>{ if(e.key==='Enter' && !state.running) run(); });
}
for(const id of ['perVibe','concurrency','minScore']) $(id).addEventListener('input',()=>{ $(id+'Val').textContent=$(id).value; updateSummaries(); });
for(const id of ['trademark','offline','customTlds']) $(id).addEventListener('input',updateSummaries);
$('run').addEventListener('click',run);
$('exportCsv').addEventListener('click',()=>download('namestack.csv',toCsv(rowsForExport()),'text/csv'));
$('exportJson').addEventListener('click',()=>download('namestack.json',JSON.stringify(rowsForExport(),null,2),'application/json'));
$('aiConfirm').addEventListener('click',confirmAi);
$('aiClear').addEventListener('click',clearAi);
$('filters').addEventListener('click',(e)=>{
  const p=e.target.closest('button'); if(!p) return;
  document.querySelectorAll('#filters button').forEach(x=>x.classList.toggle('on',x===p));
  state.filter=p.dataset.f; render();
});
document.addEventListener('click',(e)=>{ if(!e.target.closest('#exportMenu')) $('exportMenu').open=false; });

// Light / dark switch. Light by default; the user's pick is remembered.
const THEME_KEY='namestack.theme';
function currentTheme(){ return document.documentElement.dataset.theme==='dark'?'dark':'light'; }
function paintThemeButton(){
  const dark=currentTheme()==='dark', label=dark?'Switch to light mode':'Switch to dark mode';
  $('iconMoon').style.display=dark?'none':''; $('iconSun').style.display=dark?'':'none';
  $('themeBtn').setAttribute('aria-label',label); $('themeBtn').dataset.tip=label+'.';
}
$('themeBtn').addEventListener('click',()=>{
  const next=currentTheme()==='dark'?'light':'dark';
  document.documentElement.dataset.theme=next;
  try{ localStorage.setItem(THEME_KEY,next); }catch{}
  hideTip(); paintThemeButton();
});

(async function init(){
  tip.el=$('tip'); paintThemeButton();
  buildTlds(); updateSummaries();
  try{
    const meta=await (await fetch('/api/meta')).json();
    state.vibes=meta.vibes; state.providers=meta.providers;
    meta.default_vibes.forEach(v=>selectedVibes.add(v));
    buildVibes(); buildProviders(); applyProviderDefaults(true); updateSummaries();
    if(meta.ai){ setAiState(meta.ai); return; }
    const saved=store.get();
    if(saved){
      $('aiProvider').value=saved.provider; applyProviderDefaults(true);
      $('aiModel').value=saved.model||$('aiModel').value; $('aiBase').value=saved.base_url||$('aiBase').value;
      $('aiRemember').checked=true;
      try{ setAiState(await postJson('/api/ai/config',saved)); }catch(err){ setAiState(null); toast('Saved AI key: '+err.message); }
    }
  }catch(err){ toast('Could not load settings: '+err.message); }
  $('loves').focus();
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
    france = "french" in vibes
    asyncio.run(_async_checks(candidates, by_domain, checker, trademark, trademark_limit, france, offline, emit))


async def _async_checks(candidates, by_domain, checker, trademark, trademark_limit, france, offline, emit) -> None:
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

    available = [
        c for c in candidates
        if results.get(c.domain) and results[c.domain].status is Status.AVAILABLE
    ]
    screens = []
    if trademark:
        names = list(dict.fromkeys(c.name for c in available))
        targets = names[:trademark_limit] if trademark_limit > 0 else names
        if targets:
            async def on_tm(tres) -> None:
                emit(
                    "tm",
                    {"name": tres.word, "risk": tres.risk.value,
                     "hits": tres.total_hits, "exact": tres.exact_match},
                )

            screens.append(check_words(
                targets,
                concurrency=min(5, checker.concurrency),
                dry_run=offline,
                on_result=on_tm,
            ))
    if france:
        # Every French-style name with a free domain; the register is fast and free.
        fr_targets = list(dict.fromkeys(c.name for c in available if c.kind == "french"))
        if fr_targets:
            async def on_fr(fres) -> None:
                emit(
                    "fr",
                    {"name": fres.word, "status": fres.status.value, "matches": fres.matches,
                     "company": fres.company, "detail": fres.detail, "url": fres.url},
                )

            screens.append(check_fr_names(fr_targets, dry_run=offline, on_result=on_fr))
    if screens:
        emit("stage", {"message": "screening trademarks and the French register..." if france else "screening trademarks..."})
        await asyncio.gather(*screens)

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
