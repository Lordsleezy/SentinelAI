#!/usr/bin/env python3
"""Capture Earn Discovery Dashboard screenshots (requires backend on :5001)."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots" / "earn_dashboard"
API = "http://127.0.0.1:5001/api/earn/discovery/dashboard"
PREVIEW = OUT / "preview.html"


def _fetch_dashboard() -> dict:
    try:
        with urllib.request.urlopen(API, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    # Offline / stale server — build payload from workers
    from workers.earn.dashboard_service import fetch_dashboard_programs

    programs, overview, extra = fetch_dashboard_programs(refresh=False, force=False)
    return {
        "status": "ok",
        "programs": programs,
        "overview": overview,
        "metrics": extra.get("metrics"),
    }


def _write_preview(data: dict, html_path: Path | None = None) -> None:
    programs = data.get("programs") or []
    ov = data.get("overview") or {}
    metrics = data.get("metrics") or {}
    sample = programs[:40]
    twilio = next((p for p in programs if (p.get("handle") or "").lower() == "twilio"), programs[0] if programs else {})
    detail_handle = (twilio.get("handle") or twilio.get("program") or "")

    rows_html = ""
    for p in sample:
        h = p.get("handle") or p.get("program") or ""
        sel = " selected" if h == detail_handle else ""
        rows_html += f"""<div class="earn-dash-row{sel}">
          <span>{p.get('title','')[:28]}</span><span>{p.get('platform','')}</span>
          <span>{(p.get('bounty_display') or p.get('reward') or '')[:16]}</span>
          <span>{p.get('asset_count',0)}</span>
          <span class="chk">{'✓' if p.get('has_web') else '✗'}</span>
          <span class="chk">{'✓' if p.get('has_mobile') else '✗'}</span>
          <span class="chk">{'✓' if p.get('has_api') else '✗'}</span>
          <span>{(p.get('last_updated') or '')[:10]}</span><span>{(p.get('source') or 'api')[:6]}</span>
        </div>"""

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dashboard_snapshot.json").write_text(
        json.dumps({"overview": ov, "metrics": metrics, "program_count": len(programs)}, indent=2),
        encoding="utf-8",
    )

    (html_path or PREVIEW).write_text(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Earn Discovery Dashboard</title>
<style>
body {{ background:#000; color:#e0e0e0; font-family:Segoe UI,sans-serif; padding:16px; margin:0; }}
.earn-dash-overview {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }}
.earn-dash-card {{ background:#0a0a0f; border:1px solid rgba(0,255,136,0.12); border-radius:6px; padding:8px 10px; }}
.earn-dash-card .label {{ font-size:9px; color:#555; text-transform:uppercase; }}
.earn-dash-card .value {{ font-size:13px; color:#00ff88; font-weight:600; }}
.earn-dash-metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:10px; }}
.earn-dash-layout {{ display:flex; gap:10px; }}
.earn-dash-table-wrap {{ flex:1; border:1px solid rgba(255,255,255,0.06); border-radius:6px; }}
.earn-dash-table-header,.earn-dash-row {{ display:grid; grid-template-columns:1.4fr 0.7fr 0.9fr 0.45fr 0.35fr 0.35fr 0.35fr 0.7fr 0.5fr; gap:4px; padding:6px 8px; font-size:10px; }}
.earn-dash-table-header {{ background:#0d0d12; color:#666; text-transform:uppercase; }}
.earn-dash-row {{ height:36px; align-items:center; border-bottom:1px solid rgba(255,255,255,0.03); }}
.earn-dash-row.selected {{ background:rgba(0,207,255,0.1); border-left:2px solid #00cfff; }}
.earn-dash-detail {{ width:240px; background:#0a0a0f; border:1px solid rgba(0,207,255,0.15); border-radius:6px; padding:10px; font-size:10px; }}
h1 {{ color:#00ff88; font-size:14px; letter-spacing:1px; }}
</style></head><body>
<h1>EARN DISCOVERY DASHBOARD</h1>
<div class="earn-dash-overview">
  <div class="earn-dash-card"><div class="label">Programs Available</div><div class="value">{ov.get('programs_available','—')}</div></div>
  <div class="earn-dash-card"><div class="label">Active Programs</div><div class="value">{ov.get('active_programs','—')}</div></div>
  <div class="earn-dash-card"><div class="label">Web / Mobile / API</div><div class="value">{ov.get('web_targets')} / {ov.get('mobile_targets')} / {ov.get('api_targets')}</div></div>
  <div class="earn-dash-card"><div class="label">Highest / Avg</div><div class="value">{ov.get('highest_bounty_display')} / {ov.get('average_bounty_display')}</div></div>
</div>
<div class="earn-dash-metrics">
  <div class="earn-dash-card"><div class="label">Discovered</div><div class="value">{metrics.get('programs_discovered','—')}</div></div>
  <div class="earn-dash-card"><div class="label">Analyzed</div><div class="value">{metrics.get('programs_analyzed','—')}</div></div>
  <div class="earn-dash-card"><div class="label">Reports</div><div class="value">{metrics.get('reports_generated','—')}</div></div>
  <div class="earn-dash-card"><div class="label">Reward Pool</div><div class="value">{metrics.get('potential_reward_pool_display','—')}</div></div>
</div>
<div class="earn-dash-layout">
  <div class="earn-dash-table-wrap">
    <div class="earn-dash-table-header"><span>Program</span><span>Platform</span><span>Bounty</span><span>Assets</span><span>Web</span><span>Mob</span><span>API</span><span>Updated</span><span>Src</span></div>
    {rows_html}
  </div>
  <div class="earn-dash-detail">
    <h4>{twilio.get('title', detail_handle)}</h4>
    <p>Platform: {twilio.get('platform','HackerOne')}</p>
    <p>Bounty: {twilio.get('bounty_display') or twilio.get('reward','')}</p>
    <p>Assets: {twilio.get('asset_count',0)} · Web/Mob/API: {'✓' if twilio.get('has_web') else '✗'} / {'✓' if twilio.get('has_mobile') else '✗'} / {'✓' if twilio.get('has_api') else '✗'}</p>
    <p style="color:#888;margin-top:8px;">Detail panel + top 5 recommendations load live in orb Earn tab.</p>
  </div>
</div>
</body></html>""",
        encoding="utf-8",
    )


def _screenshot_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed")
        return False

    shots = [
        ("01_overview_table.png", PREVIEW.as_uri()),
    ]
    search_preview = OUT / "preview_search.html"
    if search_preview.exists():
        shots.append(("02_search_filtered.png", search_preview.as_uri()))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 720})
        for name, url in shots:
            page.goto(url, wait_until="networkidle")
            page.screenshot(path=str(OUT / name), full_page=True)
            print(f"Wrote {OUT / name}")
        browser.close()
    return True


def main() -> int:
    try:
        data = _fetch_dashboard()
    except urllib.error.URLError as e:
        print(f"Cannot reach {API}: {e}")
        print("Start backend: python desktop_app.py")
        return 1

    if data.get("status") != "ok":
        print("Dashboard API error:", data.get("error"))
        return 1

    _write_preview(data)
    print(f"Snapshot: {OUT / 'dashboard_snapshot.json'}")

    # Search-filtered preview
    programs = data.get("programs") or []
    filtered = [p for p in programs if "twilio" in (p.get("search_blob") or "")]
    if filtered:
        sub = dict(data)
        sub["programs"] = filtered
        _write_preview(sub, OUT / "preview_search.html")

    if not _screenshot_playwright():
        print("Preview HTML only (no PNG). Open:", PREVIEW)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
