"""
dashboard.py — FastAPI dashboard for Sentinel Earn
Dark-themed single-page dashboard at http://localhost:8765
Live earnings counter, opportunity queue, activity feed, action buttons.
"""
import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse

import db

logger = logging.getLogger(__name__)

app = FastAPI(title="Sentinel Earn", version="1.0.0", docs_url=None, redoc_url=None)

# ─── HTML Dashboard ───────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel Earn — Bounty Agent</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'JetBrains Mono','Fira Code',monospace;background:#0d1117;color:#e6edf3;min-height:100vh;padding:24px}
a{color:#58a6ff;text-decoration:none}a:hover{text-decoration:underline}

/* Header */
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;padding-bottom:16px;border-bottom:1px solid #30363d}
.hdr h1{font-size:22px;color:#58a6ff;font-weight:700;letter-spacing:-.5px}
.live{display:flex;align-items:center;gap:8px;color:#3fb950;font-size:12px}
.dot{width:8px;height:8px;background:#3fb950;border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* Earnings hero */
.hero{text-align:center;padding:28px 0 8px}
.hero-val{font-size:52px;font-weight:700;color:#3fb950;text-shadow:0 0 24px rgba(63,185,80,.35);transition:text-shadow .4s}
.hero-val.flash{text-shadow:0 0 60px rgba(63,185,80,.9)}
.hero-sub{font-size:12px;color:#8b949e;margin-top:6px}

/* Stats grid */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:24px 0}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:18px;transition:border-color .2s}
.card:hover{border-color:#58a6ff}
.card .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:#8b949e;margin-bottom:6px}
.card .val{font-size:28px;font-weight:700;color:#f0f6fc}
.val.g{color:#3fb950}.val.y{color:#d29922}.val.b{color:#58a6ff}.val.r{color:#f85149}

/* Action bar */
.actions{display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.btn{padding:9px 18px;border-radius:6px;border:1px solid #30363d;font-family:inherit;font-size:13px;cursor:pointer;font-weight:600;transition:all .15s}
.btn:hover{transform:translateY(-1px)}.btn:active{transform:translateY(0)}
.btn-g{background:#238636;border-color:#2ea043;color:#fff}.btn-g:hover{background:#2ea043}
.btn-b{background:#1f4287;border-color:#388bfd;color:#58a6ff}.btn-b:hover{background:#388bfd;color:#fff}
.act-msg{font-size:12px;color:#8b949e}

/* Sections */
.sec{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:20px;overflow:hidden}
.sec-hdr{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid #30363d;background:#1c2128}
.sec-hdr h2{font-size:13px;font-weight:600}
.note{font-size:11px;color:#8b949e}

/* Badges */
.badge{font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600}
.bb{background:#1f4287;color:#58a6ff}.bg{background:#1a3823;color:#3fb950}
.by{background:#3a2900;color:#d29922}.br{background:#3d1616;color:#f85149}

/* Table */
table{width:100%;border-collapse:collapse}
th{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#8b949e;padding:10px 18px;text-align:left;border-bottom:1px solid #30363d;background:#1c2128}
td{padding:10px 18px;font-size:12px;border-bottom:1px solid #21262d;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1c2128}
.tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:3px;background:#21262d;color:#8b949e}

/* Log feed */
.feed{padding:14px 18px;max-height:280px;overflow-y:auto}
.log{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #21262d;font-size:11px}
.log:last-child{border-bottom:none}
.lt{color:#8b949e;white-space:nowrap;min-width:135px}
.le{color:#58a6ff;min-width:110px;font-weight:600}
.ld{color:#c9d1d9;opacity:.8}

.empty{padding:36px;text-align:center;color:#8b949e;font-size:13px}
</style>
</head>
<body>

<div class="hdr">
  <h1>🎯 Sentinel Earn</h1>
  <div class="live"><div class="dot"></div>Agent Active &mdash; <span id="clock"></span></div>
</div>

<div class="hero">
  <div class="hero-val" id="hero-val">$0.00</div>
  <div class="hero-sub" id="hero-sub">Confirmed Earnings</div>
</div>

<div class="grid">
  <div class="card"><div class="lbl">Confirmed</div><div class="val g" id="s-conf">$0.00</div></div>
  <div class="card"><div class="lbl">Pending PRs</div><div class="val y" id="s-pend">0</div></div>
  <div class="card"><div class="lbl">Merge Rate</div><div class="val b" id="s-rate">0%</div></div>
  <div class="card"><div class="lbl">Opportunities</div><div class="val" id="s-opps">0</div></div>
  <div class="card"><div class="lbl">Total Submitted</div><div class="val" id="s-subs">0</div></div>
</div>

<div class="actions">
  <button class="btn btn-g" onclick="runScan()">&#9654; Scan Now</button>
  <button class="btn btn-b" onclick="runExec()">&#9889; Execute Fix</button>
  <span class="act-msg" id="act-msg"></span>
</div>

<div class="sec">
  <div class="sec-hdr"><h2>Opportunity Queue</h2><span class="badge bb" id="opp-cnt">0</span></div>
  <div id="opp-tbl"><div class="empty">Loading…</div></div>
</div>

<div class="sec">
  <div class="sec-hdr"><h2>Submissions</h2><span class="badge bg" id="sub-cnt">0</span></div>
  <div id="sub-tbl"><div class="empty">Loading…</div></div>
</div>

<div class="sec">
  <div class="sec-hdr"><h2>Activity Feed</h2><span class="note">Refreshes every 10 s</span></div>
  <div class="feed" id="feed"><div class="empty">No activity yet</div></div>
</div>

<script>
const $=id=>document.getElementById(id);
let prevEarnings=0;

function fmt(v){return'$'+parseFloat(v||0).toFixed(2)}

function badge(s){
  const m={new:'bb',in_progress:'by',submitted:'bg',merged:'bg',
           failed:'br',skipped:'by',closed:'br',rejected:'br',
           pending:'by',open:'bb'};
  return`<span class="badge ${m[s]||'bb'}">${s}</span>`;
}

async function loadEarnings(){
  const d=await fetch('/api/earnings').then(r=>r.json()).catch(()=>({}));
  const e=d.confirmed_earnings||0;
  $('hero-val').textContent=fmt(e);
  $('s-conf').textContent=fmt(e);
  $('s-pend').textContent=d.pending_count||0;
  $('s-rate').textContent=(d.merge_rate||0)+'%';
  $('s-subs').textContent=d.total_submissions||0;
  $('hero-sub').textContent=
    `Confirmed · ${d.pending_count||0} pending (~${fmt(d.pending_value)} est)`;
  if(e>prevEarnings&&prevEarnings>0){
    $('hero-val').classList.add('flash');
    setTimeout(()=>$('hero-val').classList.remove('flash'),900);
  }
  prevEarnings=e;
}

async function loadOpps(){
  const data=await fetch('/api/opportunities').then(r=>r.json()).catch(()=>[]);
  $('opp-cnt').textContent=data.length;
  $('s-opps').textContent=data.length;
  if(!data.length){$('opp-tbl').innerHTML='<div class="empty">No opportunities yet — run a scan</div>';return}
  let h='<table><thead><tr><th>Source</th><th>Title</th><th>Bounty</th><th>Complexity</th><th>Status</th><th>Found</th></tr></thead><tbody>';
  for(const o of data.slice(0,25)){
    const t=(o.title||'').substring(0,58);
    h+=`<tr>
      <td><span class="tag">${o.source||'-'}</span></td>
      <td><a href="${o.issue_url}" target="_blank" title="${o.title||''}">${t}${o.title&&o.title.length>58?'…':''}</a></td>
      <td style="color:#3fb950;font-weight:600">${fmt(o.bounty_amount)}</td>
      <td>${o.complexity_score?o.complexity_score.toFixed(1)+'/10':'-'}</td>
      <td>${badge(o.status)}</td>
      <td style="color:#8b949e;font-size:10px">${(o.created_at||'').substring(0,16)}</td>
    </tr>`;
  }
  h+='</tbody></table>';
  $('opp-tbl').innerHTML=h;
}

async function loadSubs(){
  const data=await fetch('/api/submissions').then(r=>r.json()).catch(()=>[]);
  $('sub-cnt').textContent=data.length;
  if(!data.length){$('sub-tbl').innerHTML='<div class="empty">No submissions yet</div>';return}
  let h='<table><thead><tr><th>Title</th><th>PR</th><th>Status</th><th>Value</th><th>Submitted</th></tr></thead><tbody>';
  for(const s of data){
    const earned=s.earnings>0?s.earnings:s.bounty_amount;
    h+=`<tr>
      <td>${(s.title||'').substring(0,50)}</td>
      <td>${s.pr_url?`<a href="${s.pr_url}" target="_blank">View ↗</a>`:'-'}</td>
      <td>${badge(s.status)}</td>
      <td style="color:${s.earnings>0?'#3fb950':'#8b949e'}">${fmt(earned)}</td>
      <td style="color:#8b949e;font-size:10px">${(s.submitted_at||'').substring(0,16)}</td>
    </tr>`;
  }
  h+='</tbody></table>';
  $('sub-tbl').innerHTML=h;
}

async function loadFeed(){
  const data=await fetch('/api/activity').then(r=>r.json()).catch(()=>[]);
  if(!data.length){$('feed').innerHTML='<div class="empty">No activity yet</div>';return}
  $('feed').innerHTML=data.map(l=>`
    <div class="log">
      <span class="lt">${(l.timestamp||'').substring(0,19)}</span>
      <span class="le">${l.event||''}</span>
      <span class="ld">${(l.detail||'').substring(0,90)}</span>
    </div>`).join('');
}

async function runScan(){
  $('act-msg').textContent='⏳ Starting scan…';
  const d=await fetch('/api/run-scan',{method:'POST'}).then(r=>r.json()).catch(()=>({}));
  $('act-msg').textContent='✓ '+( d.message||'Scan started');
  setTimeout(loadAll,3500);
}

async function runExec(){
  $('act-msg').textContent='⏳ Executing fix…';
  const d=await fetch('/api/run-executor',{method:'POST'}).then(r=>r.json()).catch(()=>({}));
  $('act-msg').textContent='✓ '+(d.message||'Executor started');
  setTimeout(loadAll,5000);
}

function tick(){$('clock').textContent=new Date().toLocaleTimeString()}

function loadAll(){loadEarnings();loadOpps();loadSubs();loadFeed()}

loadAll();tick();
setInterval(tick,1000);
setInterval(loadAll,10000);
</script>
</body>
</html>"""


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return _HTML


@app.get("/api/opportunities")
async def api_opportunities():
    try:
        return db.list_opportunities(limit=100)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/submissions")
async def api_submissions():
    try:
        return db.list_submissions()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/earnings")
async def api_earnings():
    try:
        return db.get_earnings_summary()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/activity")
async def api_activity():
    try:
        return db.get_recent_logs(limit=50)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/run-scan")
async def api_run_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(_bg_scan)
    return {"status": "started", "message": "Scan running in background"}


@app.post("/api/run-executor")
async def api_run_executor(background_tasks: BackgroundTasks):
    background_tasks.add_task(_bg_executor)
    return {"status": "started", "message": "Executor running in background"}


# ─── Background task helpers ──────────────────────────────────────────────────

async def _bg_scan():
    try:
        from scanner import run_scan
        count = await run_scan()
        logger.info(f"Background scan done: {count} new opportunities")
    except Exception as e:
        logger.error(f"Background scan error: {e}")


async def _bg_executor():
    try:
        from executor import run_executor
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_executor)
        logger.info(f"Background executor done: {result}")
    except Exception as e:
        logger.error(f"Background executor error: {e}")


def create_app() -> FastAPI:
    """Factory for use by uvicorn / tests."""
    return app
