"""
desktop_app.py — SentinelAI Desktop Application
Lightweight desktop shell using Flask + system tray
Launches backend, provides UI, system tray controls
"""
import os
import sys
import subprocess
import threading
import webbrowser
import logging
import asyncio
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import pystray
from PIL import Image, ImageDraw
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import db
import learning_memory as lm
import queue_manager as qm
import worker_manager as wm
import watchdog as wd
import health_monitor as hm
import orchestration as orch
from internet_runtime import get_research_runtime
from memory.filesystem_index import get_filesystem_indexer
from memory.persistent_memory import get_memory
from model_router import get_model_router
from reflection import ReflectionEngine
from tool_registry import get_tool_registry
from tools.registry import find_tool_for_task, list_tools, register_builtin_tools
from executor import run_executor, execute_submit
from scanner import run_scan
from openclaw_integration import OpenClawCommandRouter
from workers.forge_worker import run_approved_forge_task
from workers.licensing.license_manager import get_license_manager
from workers.identity.identity_manager import get_identity_manager
from workers.memory.memory_manager_v2 import get_memory_manager_v2

# Register Scalp routes
try:
    from workers.scalp.scalp_worker import register_routes as _register_scalp_routes
    _register_scalp_routes_pending = True
except Exception as _scalp_import_err:
    _register_scalp_routes_pending = False
    import logging as _logging
    _logging.getLogger(__name__).warning("Scalp worker import failed: %s", _scalp_import_err)
from notifications import send_notification
from memory_manager import get_memory_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
CORS(app)

# License manager (initialized at startup)
license_manager = get_license_manager()

# Identity manager (credentials for Claude.ai / ChatGPT)
identity_manager = get_identity_manager()

# Browser sessions — populated after startup
browser_sessions = None

# Memory V2 — 3-layer memory system (initialized after socketio is ready)
memory_v2 = None

# ─── Real-time events (Task 4) — graceful fallback to polling ──────────────────
# When flask-socketio is installed we push events to the HUD instantly; if not,
# the HUD keeps working via its 2-second polling loop.
try:
    from flask_socketio import SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                        logger=False, engineio_logger=False)
    SOCKETIO_AVAILABLE = True
    logger.info("Socket.IO enabled (real-time HUD events)")
except Exception as _sio_exc:  # pragma: no cover
    socketio = None
    SOCKETIO_AVAILABLE = False
    logging.getLogger(__name__).warning("flask-socketio unavailable (%s) — polling fallback", _sio_exc)


def emit_event(event: str, payload: dict) -> None:
    """Emit a HUD event over Socket.IO. No-op when Socket.IO is unavailable.

    Events: orb_state, task_update, approval_needed, worker_status,
            log_line, earn_update.
    """
    if not SOCKETIO_AVAILABLE or socketio is None:
        return
    try:
        socketio.emit(event, payload)
    except Exception:
        pass


def log(message: str, level: str = 'info', source: str = 'system') -> None:
    """Emit a log_event to the Log tab via Socket.IO."""
    if SOCKETIO_AVAILABLE and socketio is not None:
        try:
            socketio.emit('log_event', {
                'type': source,
                'level': level,
                'message': message,
                'timestamp': datetime.now().isoformat(),
            })
        except Exception:
            pass
    logger.debug("[%s/%s] %s", source, level, message)


# ─── Live worker state (Issue 2/6) ────────────────────────────────────────────
# In-memory per-worker runtime state surfaced at /api/workers/status under `live`
# so the HUD dock + worker panels show real status/activity. Updated by the forge
# resume flow, guardian scans, and task routing; mirrored to the HUD over WS.
_live_lock = threading.Lock()
live_workers = {
    name: {"status": "idle", "current_task": None, "last_activity": None, "activity": []}
    for name in ("forge", "guardian", "web", "repair", "earn")
}


def set_worker(worker, status=None, current_task="__keep__", activity=None,
               extra=None, emit=True):
    """Update a worker's live state and (optionally) mirror it to the HUD."""
    with _live_lock:
        w = live_workers.setdefault(
            worker, {"status": "idle", "current_task": None, "last_activity": None, "activity": []})
        if status is not None:
            w["status"] = status
        if current_task != "__keep__":
            w["current_task"] = current_task
        if activity:
            entry = {"text": str(activity), "status": status or w["status"],
                     "ts": datetime.now().isoformat()}
            w["activity"].insert(0, entry)
            del w["activity"][10:]
            w["last_activity"] = entry["ts"]
        if extra:
            w.update(extra)
        snapshot = dict(w)
    if emit:
        emit_event("worker_status", {"worker": worker, "status": snapshot["status"],
                                     "current_task": snapshot["current_task"]})
        if activity:
            emit_event("task_update", {"worker": worker, "status": snapshot["status"],
                                       "message": str(activity)})
            emit_event("log_line", {"event": f"{worker}_activity", "detail": str(activity),
                                    "level": "error" if status == "error" else "info"})
    return snapshot

# Global state
backend_state = {
    "running": False,
    "paused": False,
    "startup_complete": False,
    "active_tasks": [],
    "ollama_status": "unknown",
    "last_scan": None,
    "total_earnings": 0.0
}

SCAN_INTERVAL_SECONDS = 30 * 60

# Set to True to scan immediately on Flask startup.
# Off by default — scan runs only on the APScheduler 4-hour schedule or when
# the user clicks "Scan Now" in the Earn window.
SCAN_ON_STARTUP = False

# ─── Sentinel Identity ────────────────────────────────────────────────────────

SENTINEL_SYSTEM_PROMPT = """You are Sentinel, an advanced AI assistant and orchestration system created by Sentinel Prime Inc. You are intelligent, helpful, and concise. Important rules:
- Your name is always Sentinel. Never say you are qwen, llama, mistral, or any other model.
- If asked who made you, say: Sentinel Prime Inc.
- If asked what you are, say: I am Sentinel, an AI assistant by Sentinel Prime Inc.
- Keep responses conversational and concise unless asked for detail.
- You have access to real-time data including weather, crypto prices, news, and more.
- You can control smart home devices, find freelance work, repair code, and much more."""


# ─── Real-Time Data Helpers ───────────────────────────────────────────────────

def geocode_city(city: str):
    """Resolve a city name to (lat, lon, name) via Open-Meteo geocoding API."""
    try:
        import requests
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=5,
        )
        results = r.json().get("results", [])
        if results:
            loc = results[0]
            return loc["latitude"], loc["longitude"], loc.get("name", city)
    except Exception:
        pass
    return None, None, city


def get_weather_data(lat=37.3382, lon=-121.8863, city_name="San Jose"):
    try:
        import requests
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weathercode,windspeed_10m,relativehumidity_2m,apparent_temperature",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "timezone": "America/Los_Angeles",
                "forecast_days": 3
            },
            timeout=5
        )
        d = r.json()
        c = d["current"]
        daily = d["daily"]
        codes = {0:"Clear",1:"Mostly clear",2:"Partly cloudy",3:"Overcast",45:"Foggy",51:"Light drizzle",61:"Light rain",63:"Moderate rain",71:"Light snow",80:"Rain showers",95:"Thunderstorm"}
        condition = codes.get(c["weathercode"], "Unknown")
        return {
            "temp": c["temperature_2m"],
            "feels_like": c["apparent_temperature"],
            "condition": condition,
            "wind": c["windspeed_10m"],
            "humidity": c["relativehumidity_2m"],
            "today_high": daily["temperature_2m_max"][0],
            "today_low": daily["temperature_2m_min"][0],
            "rain_chance": daily["precipitation_probability_max"][0],
            "tomorrow_high": daily["temperature_2m_max"][1],
            "tomorrow_low": daily["temperature_2m_min"][1],
            "city": city_name,
        }
    except Exception as e:
        return {"error": str(e)}


def get_crypto_price(symbol="bitcoin"):
    try:
        import requests
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbol, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=5
        )
        data = r.json()
        price = data[symbol]["usd"]
        change = data[symbol]["usd_24h_change"]
        return {"price": price, "change_24h": round(change, 2), "symbol": symbol}
    except Exception as e:
        return {"error": str(e)}


def get_news_headlines(limit=5):
    try:
        import feedparser
        feed = feedparser.parse("https://feeds.npr.org/1001/rss.xml")
        headlines = [{"title": e.title, "link": e.link} for e in feed.entries[:limit]]
        return headlines
    except Exception as e:
        return []


def get_stock_price(ticker="SPY"):
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        return {
            "ticker": ticker,
            "price": round(info.last_price, 2),
            "change": round(info.last_price - info.previous_close, 2),
            "change_pct": round((info.last_price - info.previous_close) / info.previous_close * 100, 2)
        }
    except Exception as e:
        return {"error": str(e)}


def enqueue_new_repair_opportunities() -> int:
    enqueued = 0
    opportunities = db.list_opportunities(status="approved", limit=100)
    tasks = qm.list_tasks(limit=500)
    queued_ids = {
        task.get("opportunity_id")
        for task in tasks
        if task.get("task_type") == "repair_execute"
        and task.get("status") in ("pending", "running")
    }

    for opp in opportunities:
        opp_id = opp["id"]
        if opp_id in queued_ids:
            continue
        qm.enqueue_task(
            "repair_execute",
            priority=3,
            opportunity_id=opp_id,
            task_data={"opportunity_id": opp_id},
        )
        enqueued += 1

    if enqueued:
        logger.info(f"Enqueued {enqueued} new repair opportunities")
    return enqueued


def handle_repair_execute(task):
    if backend_state.get("paused"):
        raise RuntimeError("Backend is paused")
    return run_executor(dry_run=False)


def handle_forge_build(task):
    if backend_state.get("paused"):
        raise RuntimeError("Backend is paused")
    forge_task_id = int((task.get("task_data") or {}).get("forge_task_id"))
    db.update_forge_task(forge_task_id, "running")
    try:
        result = run_approved_forge_task(task)
        db.update_forge_task(
            forge_task_id,
            "completed",
            output_path=str(result.get("output_path", "")),
            result_json=str(result)[:5000],
        )
        db.log_event("forge_completed", f"Forge task #{forge_task_id} completed")

        # Write to memory vault
        mm = get_memory_manager()
        mm.write_forge_log(
            task_id=str(forge_task_id),
            result_dict={
                "status": "completed",
                "description": task.get("description", ""),
                "prompt": (task.get("task_data") or {}).get("prompt", ""),
                "result": str(result)[:2000],
                "files_modified": result.get("files_modified", []),
                "execution_time": result.get("execution_time", "N/A"),
                "errors": None
            }
        )

        return result
    except Exception as exc:
        db.update_forge_task(forge_task_id, "failed", error=str(exc)[:2000])
        db.log_event("forge_failed", f"Forge task #{forge_task_id}: {exc}")
        send_notification(
            "SentinelAI Forge error",
            f"Forge task #{forge_task_id} failed: {exc}",
            priority="high",
            tags="rotating_light",
        )

        # Write failure to memory vault
        mm = get_memory_manager()
        mm.write_forge_log(
            task_id=str(forge_task_id),
            result_dict={
                "status": "failed",
                "description": task.get("description", ""),
                "prompt": (task.get("task_data") or {}).get("prompt", ""),
                "result": "Task failed",
                "files_modified": [],
                "execution_time": "N/A",
                "errors": str(exc)[:2000]
            }
        )

        raise


def background_scan_loop():
    """Periodic earn scanner.

    When SCAN_ON_STARTUP is False the first scan is deferred by
    SCAN_INTERVAL_SECONDS so it does not block or slow Flask startup.
    """
    import time

    if not SCAN_ON_STARTUP:
        # Skip the immediate scan; wait for the first scheduled window
        time.sleep(SCAN_INTERVAL_SECONDS)

    while backend_state.get("running"):
        try:
            inserted = asyncio.run(run_scan(dry_run=False))
            backend_state["last_scan"] = datetime.now().isoformat()
            logger.info(f"Background scan inserted {inserted} new opportunities")
            enqueue_new_repair_opportunities()
        except Exception as e:
            logger.exception(f"Background scan failed: {e}")

        time.sleep(SCAN_INTERVAL_SECONDS)

# Authentication
AUTH_TOKEN = os.getenv("SENTINELAI_AUTH_TOKEN", "sentinelai_default_token_change_me")


def verify_auth_token(token: str) -> bool:
    """Verify authentication token."""
    if not token:
        return False
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    return token == AUTH_TOKEN


# ─── System Tray Icon ─────────────────────────────────────────────────────────

def create_tray_icon():
    """Create a simple system tray icon."""
    # Create a simple icon (dark circle with 'S')
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), color='#1a1a2e')
    draw = ImageDraw.Draw(image)
    
    # Draw 'S' for Sentinel
    draw.ellipse([8, 8, 56, 56], fill='#16213e', outline='#0f3460')
    draw.text((20, 18), 'S', fill='#00d4ff')
    
    return image


def on_quit(icon, item):
    """Quit the application."""
    logger.info("Quitting SentinelAI...")
    backend_state["running"] = False
    icon.stop()
    os._exit(0)


def on_open_dashboard(icon, item):
    """Open dashboard in browser."""
    webbrowser.open('http://localhost:5001')


def on_pause_resume(icon, item):
    """Toggle pause/resume."""
    backend_state["paused"] = not backend_state["paused"]
    status = "paused" if backend_state["paused"] else "resumed"
    logger.info(f"SentinelAI {status}")


def create_system_tray():
    """Create system tray icon with menu."""
    icon_image = create_tray_icon()
    
    menu = pystray.Menu(
        pystray.MenuItem('Open Dashboard', on_open_dashboard),
        pystray.MenuItem('Pause/Resume', on_pause_resume),
        pystray.MenuItem('Quit', on_quit)
    )
    
    icon = pystray.Icon('SentinelAI', icon_image, 'SentinelAI', menu)
    return icon


# ─── Flask Routes ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Main dashboard — the SENTINEL PRIME HUD (Task 3)."""
    return render_template('desktop_dashboard_v2.html')


@app.route('/mobile')
def mobile():
    """Mobile-optimized dashboard."""
    return render_template('mobile_dashboard.html')


@app.route('/api/credentials/check/<worker_name>', methods=['GET'])
def api_credentials_check(worker_name: str):
    """Check if a worker's credentials are configured."""
    from workers.lazy_init import get_lazy_init
    li = get_lazy_init()
    missing = li.get_missing(worker_name)
    if not missing:
        return jsonify({"configured": True})
    return jsonify({"configured": False, "missing": missing, "worker": worker_name})


@app.route('/api/credentials/save', methods=['POST'])
def api_credentials_save():
    """Save a credential to .env and env immediately, then signal retry."""
    from workers.lazy_init import get_lazy_init
    data = request.get_json() or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"status": "error", "error": "key and value required"}), 400
    ok = get_lazy_init().save(key, value)
    if ok:
        return jsonify({"status": "saved", "key": key})
    return jsonify({"status": "error", "error": "Failed to write .env"}), 500


@app.route('/api/ping')
def api_ping():
    """Instant liveness probe — used by Electron readiness poll."""
    return jsonify({"ok": True, "running": backend_state.get("running", False)})


# ── Login / Identity Routes ───────────────────────────────────────────────────

@app.route('/api/login/status')
def api_login_status():
    """Return whether credentials are configured and connection status."""
    configured = identity_manager.has_credentials()
    user_name = identity_manager.get_user_name() if configured else None
    creds = identity_manager.load_credentials() or {}
    return jsonify({
        "configured": configured,
        "user_name": user_name,
        "claude_connected": bool(creds.get("claude_email")),
        "chatgpt_connected": bool(creds.get("chatgpt_email")),
        "claude_2fa_method": creds.get("claude_2fa_method", "none"),
        "chatgpt_2fa_method": creds.get("chatgpt_2fa_method", "none"),
        "gmail_configured": False,
        "adb_available": False,
        "stealth_active": False,
    })


@app.route('/api/login/save', methods=['POST'])
def api_login_save():
    """Encrypt and save credentials from login screen."""
    try:
        data = request.json or {}
        success = identity_manager.save_credentials(data)
        if not success:
            return jsonify({"error": "Failed to encrypt/save credentials"}), 500
        log(f"Credentials saved for {data.get('user_name', 'User')}", 'success', 'identity')
        return jsonify({
            "status": "ok",
            "user_name": data.get("user_name", ""),
            "claude": bool(data.get("claude_email")),
            "chatgpt": bool(data.get("chatgpt_email")),
        })
    except Exception as e:
        log(f"Login save error: {e}", 'error', 'identity')
        return jsonify({"error": str(e)}), 500


@app.route('/api/login/test', methods=['POST'])
def api_login_test():
    """Re-test saved credentials (placeholder — full browser test in Section 2)."""
    creds = identity_manager.load_credentials() or {}
    return jsonify({
        "status": "ok",
        "user_name": creds.get("user_name", ""),
        "claude_configured": bool(creds.get("claude_email")),
        "chatgpt_configured": bool(creds.get("chatgpt_email")),
        "gmail_configured": False,
        "adb_available": False,
    })


@app.route('/api/login/clear', methods=['POST'])
def api_login_clear():
    """Clear all saved credentials."""
    identity_manager.clear_credentials()
    log("Credentials cleared", 'info', 'identity')
    return jsonify({"status": "cleared"})


# ── Sync Routes ───────────────────────────────────────────────────────────────

@app.route('/sync/status')
def sync_status():
    try:
        from workers.sync.conversation_sync import get_conversation_sync
        sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
        return jsonify(sync.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/sync/trigger', methods=['POST'])
def sync_trigger():
    """Manually trigger a conversation sync."""
    def _do_sync():
        try:
            from workers.sync.conversation_sync import get_conversation_sync
            sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
            sync.sync_all()
        except Exception as e:
            log(f"Sync error: {e}", 'error', 'sync')
    threading.Thread(target=_do_sync, daemon=True).start()
    return jsonify({"status": "started"})


@app.route('/sync/conversations')
def sync_conversations():
    try:
        from workers.sync.conversation_sync import get_conversation_sync
        sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
        convos = sync.get_all_conversations()
        return jsonify({"conversations": convos, "count": len(convos)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Memory V2 Routes ──────────────────────────────────────────────────────────

@app.route('/memory/stats')
def memory_stats():
    if memory_v2 is None:
        return jsonify({"error": "Memory V2 not initialized"}), 503
    return jsonify(memory_v2.get_stats())


@app.route('/memory/recall')
def memory_recall():
    if memory_v2 is None:
        return jsonify({"error": "Memory V2 not initialized"}), 503
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 5))
    source_filter = request.args.get('source', None)
    sources = [source_filter] if source_filter else None
    results = memory_v2.recall(query, limit=limit, sources=sources)
    return jsonify({"results": [r.to_dict() for r in results], "count": len(results)})


@app.route('/memory/conversations')
def memory_conversations():
    try:
        from workers.sync.conversation_sync import get_conversation_sync
        sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
        convos = sync.get_all_conversations()
        return jsonify({"conversations": convos, "count": len(convos)})
    except Exception as e:
        return jsonify({"conversations": [], "count": 0, "error": str(e)})


@app.route('/memory/from/<source>')
def memory_from_source(source):
    if memory_v2 is None:
        return jsonify({"error": "Memory V2 not initialized"}), 503
    results = memory_v2.recall_from_source(source)
    return jsonify({"results": [r.to_dict() for r in results], "source": source, "count": len(results)})


@app.route('/memory/clear/hot', methods=['DELETE'])
def memory_clear_hot():
    if memory_v2 is None:
        return jsonify({"error": "Memory V2 not initialized"}), 503
    try:
        import sqlite3
        with sqlite3.connect(str(memory_v2._DB_PATH if hasattr(memory_v2, '_DB_PATH') else 'memory/hot_memory.db')) as conn:
            conn.execute("DELETE FROM hot_memory")
            conn.commit()
        return jsonify({"status": "cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/launch', methods=['POST'])
def api_launch():
    """Launch a built file (Python script, exe, bat, html) by absolute path."""
    try:
        data = request.json or {}
        file_path = data.get('file', '').strip()

        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 404

        ext = os.path.splitext(file_path)[1].lower()
        python_exe = str(Path(__file__).parent / "venv" / "Scripts" / "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"

        if ext == '.py':
            subprocess.Popen([python_exe, file_path],
                             creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        elif ext in ('.exe', '.bat', '.cmd'):
            subprocess.Popen([file_path], shell=True)
        elif ext == '.html':
            webbrowser.open(file_path)
        else:
            if os.name == 'nt':
                os.startfile(file_path)
            else:
                subprocess.Popen(['xdg-open', file_path])

        log(f"Launched: {os.path.basename(file_path)}", 'success', 'forge')
        return jsonify({"status": "launched", "file": os.path.basename(file_path)})
    except Exception as e:
        log(f"Launch error: {e}", 'error', 'forge')
        return jsonify({"error": str(e)}), 500


@app.route('/api/status')
def api_status():
    """Get current system status."""
    # Check Ollama
    try:
        import httpx
        response = httpx.get('http://127.0.0.1:11434/api/tags', timeout=2)
        backend_state["ollama_status"] = "running" if response.status_code == 200 else "error"
    except Exception:
        backend_state["ollama_status"] = "offline"
    
    # Get earnings
    try:
        earnings = db.get_earnings_summary()
        backend_state["total_earnings"] = earnings.get("confirmed_earnings", 0.0)
    except Exception:
        pass
    
    # Check SentinelWeb
    sentinel_web_status = "offline"
    try:
        import httpx as _hx
        _sw = _hx.get("http://localhost:8766/health", timeout=2)
        sentinel_web_status = "online" if _sw.status_code == 200 else "error"
    except Exception:
        sentinel_web_status = "offline"

    # Consultation worker status
    consultation_status = {"available": True, "chatgpt_reachable": False,
                           "claude_reachable": False, "codex_installed": False}
    try:
        from workers.consultation.consultant import get_consultant
        c = get_consultant()
        consultation_status["codex_installed"] = c.codex_available
        consultation_status["chatgpt_reachable"] = c._sentinelweb_available()
        consultation_status["claude_reachable"] = consultation_status["chatgpt_reachable"]
    except Exception:
        pass

    # Scalp worker status
    scalp_status = {"running": False, "feed_connected": False,
                    "active_model": "xgboost", "open_positions": 0}
    try:
        from workers.scalp.scalp_worker import _feed_running
        from workers.scalp.data.feed import get_feed
        from workers.scalp.execution.executor import get_executor
        scalp_status["running"] = _feed_running
        scalp_status["feed_connected"] = get_feed().is_connected
        scalp_status["open_positions"] = len(get_executor().get_open_positions())
    except Exception:
        pass

    data = {
        "running": backend_state["running"],
        "paused": backend_state["paused"],
        "ollama_status": backend_state["ollama_status"],
        "active_tasks": len(backend_state["active_tasks"]),
        "total_earnings": backend_state["total_earnings"],
        "last_scan": backend_state["last_scan"],
        "sentinel_web_status": sentinel_web_status,
        "consultation": consultation_status,
        "scalp": scalp_status,
    }
    return jsonify({**data, "status": "ok", "data": data, "error": None})


@app.route('/api/health/live')
def api_health_live():
    """Liveness probe — returns 200 as long as Flask is running."""
    return jsonify({"alive": True, "timestamp": datetime.now().isoformat()}), 200


@app.route('/api/health/ready')
def api_health_ready():
    """
    Readiness probe for Electron lifecycle polling.
    Returns 200 + ready=True only when all subsystems are initialized.
    """
    checks = {}
    try:
        db.get_recent_logs(limit=1)
        checks["database"] = True
    except Exception:
        checks["database"] = False

    try:
        qm.get_queue_stats()
        checks["queue"] = True
    except Exception:
        checks["queue"] = False

    try:
        manager = wm.get_manager()
        checks["workers"] = len(manager.workers) > 0
    except Exception:
        checks["workers"] = False

    try:
        watchdog = wd.get_watchdog()
        checks["watchdog"] = watchdog.running
    except Exception:
        checks["watchdog"] = False

    try:
        monitor = hm.get_monitor()
        checks["health_monitor"] = monitor.running
    except Exception:
        checks["health_monitor"] = False

    checks["startup_complete"] = bool(backend_state.get("startup_complete"))
    all_ready = all(checks.values())

    return jsonify({
        "ready": all_ready,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }), 200 if all_ready else 503


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """Graceful shutdown endpoint called by Electron before exiting."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401

        logger.info("Graceful shutdown requested via /api/shutdown")
        backend_state["running"] = False

        def _shutdown():
            import time
            time.sleep(0.5)
            try:
                manager = wm.get_manager()
                manager.pause_all()
            except Exception:
                pass
            try:
                watchdog = wd.get_watchdog()
                watchdog.stop()
            except Exception:
                pass
            try:
                monitor = hm.get_monitor()
                monitor.stop()
            except Exception:
                pass
            logger.info("Backend shutdown complete")
            os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        return jsonify({"status": "shutting_down"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tasks')
def api_tasks():
    """Get active tasks."""
    try:
        opportunities = db.list_opportunities(status="in_progress", limit=10)
        return jsonify({"tasks": opportunities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/opportunities')
def api_opportunities():
    try:
        return jsonify({"opportunities": db.list_opportunities(limit=100)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/submissions')
def api_submissions():
    try:
        return jsonify({"submissions": db.list_submissions()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/run-scan', methods=['POST'])
def api_run_scan():
    def _scan():
        try:
            inserted = asyncio.run(run_scan(dry_run=False))
            backend_state["last_scan"] = datetime.now().isoformat()
            db.log_event("manual_scan_complete", f"Inserted {inserted} opportunities")
            enqueue_new_repair_opportunities()
        except Exception as exc:
            logger.exception("Manual scan failed")
            db.log_event("manual_scan_failed", str(exc))

    threading.Thread(target=_scan, daemon=True).start()
    return jsonify({"status": "started", "message": "Scan running"})


@app.route('/api/run-executor', methods=['POST'])
def api_run_executor():
    def _execute():
        try:
            result = run_executor(dry_run=False)
            db.log_event("manual_executor_complete", str(result)[:1000])
        except Exception as exc:
            logger.exception("Manual executor failed")
            db.log_event("manual_executor_failed", str(exc))

    threading.Thread(target=_execute, daemon=True).start()
    return jsonify({"status": "started", "message": "Executor running"})


@app.route('/api/pending-approvals')
def api_pending_approvals():
    """Get tasks pending approval."""
    try:
        opportunities = db.list_opportunities(status="ready_to_submit", limit=25)
        return jsonify({"pending": opportunities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/forge/tasks')
def api_forge_tasks():
    try:
        return jsonify({"tasks": db.list_forge_tasks(limit=100)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/forge/request', methods=['POST'])
def api_forge_request():
    """Aider-powered code generation — streams output to Log tab via Socket.IO."""
    try:
        data = request.get_json() or {}
        task = (data.get('prompt') or data.get('task') or '').strip()
        output_dir = data.get('output_dir', None)
        files = data.get('files', [])

        if not task:
            return jsonify({"error": "No task provided"}), 400

        log(f'Starting forge task: {task[:120]}', 'info', 'forge')

        def run():
            try:
                from workers.aider_engine import AiderEngine
                engine = AiderEngine(socketio)
                result = engine.build_app(task, output_dir) if output_dir else engine.run_task(task, files)
                log(
                    'Task complete' if result.success else f'Task failed: {result.error}',
                    'success' if result.success else 'error',
                    'forge',
                )
                emit_event('forge_complete', {
                    'success': result.success,
                    'output': result.output[:2000],
                    'files_modified': result.files_modified,
                    'entry_point': result.entry_point,
                    'output_dir': result.output_dir,
                    'error': result.error,
                })
            except Exception as exc:
                log(f'Forge engine error: {exc}', 'error', 'forge')
                emit_event('forge_complete', {'success': False, 'output': str(exc), 'files_modified': [], 'entry_point': None, 'output_dir': None, 'error': str(exc)})

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return jsonify({"status": "started", "message": "Aider is working on your task"})

    except Exception as e:
        log(str(e), 'error', 'forge')
        return jsonify({"error": str(e)}), 500


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from Ollama output.

    Handles all variants:
      ```python ... ```   (with language tag)
      ```py    ... ```
      ```      ... ```   (bare)
      Plain code with no fences — returned unchanged.

    Also handles:
      - Explanation text before/after the fence block
      - Windows \\r\\n line endings
      - Missing closing fence (fence at top, no bottom)
    """
    import re as _re
    text = text.strip()
    if not text:
        return text

    # Case 1: Complete fence block — extract first code block content.
    # Non-greedy match so we stop at the FIRST closing fence.
    m = _re.search(r'```[a-zA-Z0-9]*[ \t]*\r?\n(.*?)\r?\n[ \t]*```', text, _re.DOTALL)
    if m:
        return m.group(1).strip()

    # Case 2: Opening fence but no closing fence (Ollama cut off or forgot to close).
    # Strip the opening fence line and return the rest.
    if _re.match(r'^```[a-zA-Z0-9]*[ \t]*\r?\n', text):
        text = _re.sub(r'^```[a-zA-Z0-9]*[ \t]*\r?\n?', '', text)
        # Also strip any stray trailing ``` that might be a remnant
        text = _re.sub(r'\r?\n?```[a-zA-Z0-9]*\s*$', '', text)
        return text.strip()

    # Case 3: Fence with no language tag and no newline after (edge case).
    text = _re.sub(r'^`{3}[a-zA-Z0-9]*\s*', '', text)
    text = _re.sub(r'\s*`{3}[a-zA-Z0-9]*\s*$', '', text)
    return text.strip()


@app.route('/api/forge/generate', methods=['POST'])
def api_forge_generate():
    """Direct Ollama code generation for the Forge window — no approval queue."""
    try:
        data = request.get_json() or {}
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "prompt required"}), 400

        import httpx as _hx
        ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        ollama_model = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')
        forge_sys = (
            "You are Sentinel Forge, an expert AI programmer. "
            "Write clean, working, well-commented code. "
            "Return ONLY the code with no prose before or after it."
        )
        full_prompt = f"Task: {prompt}\n\nWrite the complete code:"
        with _hx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{ollama_host}/api/generate",
                json={"model": ollama_model, "prompt": full_prompt,
                      "system": forge_sys, "stream": False},
            )
        if resp.status_code != 200:
            return jsonify({"error": f"Ollama HTTP {resp.status_code}"}), 500
        code = _strip_code_fences(resp.json().get("response", ""))
        db.log_event("forge_generated", f"Forge generated code for: {prompt[:80]}")
        return jsonify({"status": "complete", "code": code,
                        "model": ollama_model, "lines": code.count('\n') + 1})
    except Exception as e:
        logger.error("forge/generate failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/forge/approve/<int:forge_task_id>', methods=['POST'])
def api_forge_approve(forge_task_id):
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        forge_task = db.get_forge_task(forge_task_id)
        if not forge_task:
            return jsonify({"error": "Forge task not found"}), 404
        if forge_task.get("status") != "pending_approval":
            return jsonify({"error": f"Forge task status is {forge_task.get('status')}"}), 400
        db.update_forge_task(forge_task_id, "approved")
        qm.enqueue_task(
            "forge_build",
            priority=2,
            task_data={"forge_task_id": forge_task_id, "prompt": forge_task["prompt"]},
        )
        db.log_event("forge_approved", f"Forge task #{forge_task_id} approved")
        return jsonify({"status": "approved", "forge_task_id": forge_task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/forge/reject/<int:forge_task_id>', methods=['POST'])
def api_forge_reject(forge_task_id):
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        db.update_forge_task(forge_task_id, "rejected")
        db.log_event("forge_rejected", f"Forge task #{forge_task_id} rejected")
        return jsonify({"status": "rejected", "forge_task_id": forge_task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs')
def api_logs():
    """Get recent logs."""
    try:
        logs = db.get_recent_logs(limit=50)
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/earnings')
def api_earnings():
    """Get earnings summary."""
    try:
        earnings = db.get_earnings_summary()
        return jsonify(earnings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/approve/<int:opp_id>', methods=['POST'])
def api_approve(opp_id):
    """Approve a pending task."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        opp = db.get_opportunity(opp_id)
        if not opp:
            return jsonify({"error": "Opportunity not found"}), 404

        if opp.get("status") == "ready_to_submit":
            result = execute_submit(opp_id)
            if not result or not result.get("success"):
                return jsonify({
                    "status": "submit_failed",
                    "opportunity_id": opp_id,
                    "error": result.get("error") if result else "Unknown error"
                }), 500
            db.log_event("task_approved", f"Task #{opp_id} approved and submitted via API", opp_id)
            logger.info(f"Task #{opp_id} approved and submitted")
            return jsonify(result)

        db.update_opportunity_status(opp_id, "approved")
        db.log_event("task_approved", f"Task #{opp_id} approved via API", opp_id)
        enqueue_new_repair_opportunities()
        logger.info(f"Task #{opp_id} approved")
        return jsonify({"status": "approved", "opportunity_id": opp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/reject/<int:opp_id>', methods=['POST'])
def api_reject(opp_id):
    """Reject a pending task."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        # Update opportunity status
        db.update_opportunity_status(opp_id, "rejected")
        db.log_event("task_rejected", f"Task #{opp_id} rejected via API", opp_id)
        logger.info(f"Task #{opp_id} rejected")
        return jsonify({"status": "rejected", "opportunity_id": opp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pause', methods=['POST'])
def api_pause():
    """Pause operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["paused"] = True
    logger.info("Operations paused")
    return jsonify({"status": "paused"})


@app.route('/api/resume', methods=['POST'])
def api_resume():
    """Resume operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["paused"] = False
    logger.info("Operations resumed")
    return jsonify({"status": "running"})


@app.route('/api/emergency-stop', methods=['POST'])
def api_emergency_stop():
    """Emergency stop all operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["running"] = False
    backend_state["paused"] = True
    logger.warning("EMERGENCY STOP activated")
    return jsonify({"status": "stopped"})


@app.route('/api/openclaw/command', methods=['POST'])
def api_openclaw_command():
    """
    OpenClaw command endpoint.
    Allows OpenClaw to control SentinelAI through safe command routing.
    """
    try:
        data = request.get_json()
        command = data.get('command')
        parameters = data.get('parameters', {})
        auth_token = request.headers.get('Authorization')
        
        if not command:
            return jsonify({"error": "command required"}), 400
        
        # Initialize router with auth token
        router = OpenClawCommandRouter(auth_token=auth_token)
        
        # Route command
        result = router.route_command(command, parameters)
        
        return jsonify(result)
    except Exception as e:
        logger.exception("Error processing OpenClaw command")
        return jsonify({"error": str(e)}), 500


@app.route('/api/openclaw/commands', methods=['GET'])
def api_openclaw_commands():
    """Get list of available OpenClaw commands."""
    from openclaw_integration import OPENCLAW_COMMANDS, BLOCKED_COMMANDS
    
    return jsonify({
        "available_commands": OPENCLAW_COMMANDS,
        "blocked_commands": BLOCKED_COMMANDS
    })


# ─── Phase 7: Always-On Operations API Endpoints ──────────────────────────────

@app.route('/api/system/health')
def api_system_health():
    """Get system health metrics."""
    try:
        monitor = hm.get_monitor()
        return jsonify(monitor.get_current_metrics())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/health/summary')
def api_system_health_summary():
    """Get health metrics summary."""
    try:
        monitor = hm.get_monitor()
        return jsonify(monitor.get_metrics_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/workers')
def api_system_workers():
    """Get worker status."""
    try:
        manager = wm.get_manager()
        return jsonify({
            "workers": manager.get_all_worker_status(),
            "stats": manager.get_stats()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/queue')
def api_system_queue():
    """Get queue status."""
    try:
        stats = qm.get_queue_stats()
        tasks = qm.list_tasks(limit=50)
        return jsonify({
            "stats": stats,
            "tasks": tasks
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/watchdog')
def api_system_watchdog():
    """Get watchdog status."""
    try:
        watchdog = wd.get_watchdog()
        return jsonify(watchdog.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/integrity')
def api_system_integrity():
    """Verify system integrity."""
    try:
        status = wd.verify_system_integrity()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/pause', methods=['POST'])
def api_system_pause():
    """Pause all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        manager.pause_all()
        return jsonify({"status": "paused"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/resume', methods=['POST'])
def api_system_resume():
    """Resume all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        manager.resume_all()
        return jsonify({"status": "running"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/restart-workers', methods=['POST'])
def api_system_restart_workers():
    """Restart all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        for worker_id in list(manager.workers.keys()):
            manager.restart_worker(worker_id)
        
        return jsonify({"status": "restarted", "count": len(manager.workers)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Learning Memory API Endpoints ────────────────────────────────────────────

@app.route('/api/learning/summary')
def api_learning_summary():
    """Get learning system summary and analytics."""
    try:
        summary = lm.get_learning_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/recommendations')
def api_learning_recommendations():
    """Get AI-generated recommendations based on learned data."""
    try:
        recommendations = lm.get_recommendations()
        return jsonify({"recommendations": recommendations})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/platform-performance')
def api_platform_performance():
    """Get platform performance metrics."""
    try:
        platforms = lm.get_all_platform_performance()
        return jsonify({"platforms": platforms})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/patterns')
def api_learning_patterns():
    """Get learned patterns."""
    try:
        pattern_type = request.args.get('type', 'keyword')
        min_confidence = float(request.args.get('min_confidence', 0.6))
        patterns = lm.get_patterns_by_type(pattern_type, min_confidence)
        return jsonify({"patterns": patterns})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/complexity-accuracy')
def api_complexity_accuracy():
    """Get complexity estimation accuracy metrics."""
    try:
        accuracy = lm.get_complexity_accuracy()
        return jsonify(accuracy)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/events')
def api_learning_events():
    """Get recent learning events."""
    try:
        limit = int(request.args.get('limit', 50))
        events = lm.get_recent_learning_events(limit)
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/record-outcome', methods=['POST'])
def api_record_outcome():
    """Record task outcome for learning (requires auth)."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.get_json()
        opportunity_id = data.get('opportunity_id')
        success = data.get('success', False)
        actual_complexity = data.get('actual_complexity', 0)
        time_hours = data.get('time_hours', 0)
        earnings = data.get('earnings', 0)
        
        if not opportunity_id:
            return jsonify({"error": "opportunity_id required"}), 400
        
        # Get opportunity details
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            return jsonify({"error": "Opportunity not found"}), 404
        
        # Update platform performance
        lm.update_platform_performance(
            opp['source'],
            success,
            opp['bounty_amount'],
            actual_complexity or opp['complexity_score'],
            earnings
        )
        
        # Extract and learn patterns
        lm.extract_and_learn_patterns(
            opportunity_id,
            opp['title'],
            [],  # Labels not stored in current schema
            opp['repo_url'],
            success,
            actual_complexity,
            time_hours
        )
        
        # Update complexity feedback
        if actual_complexity > 0:
            lm.update_complexity_feedback(
                opportunity_id,
                actual_complexity,
                time_hours,
                success,
                data.get('notes', '')
            )
        
        logger.info(f"Recorded learning outcome for opportunity #{opportunity_id}")
        return jsonify({"status": "recorded", "opportunity_id": opportunity_id})
    except Exception as e:
        logger.exception("Error recording learning outcome")
        return jsonify({"error": str(e)}), 500


# ─── Orchestration Runtime API Endpoints ─────────────────────────────────────

@app.route('/api/orchestration/status')
def api_orchestration_status():
    """Get Sentinel orchestration runtime status."""
    try:
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows')
def api_orchestration_workflows():
    """List orchestration workflows."""
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        orchestrator = orch.get_orchestrator()
        return jsonify({"workflows": orchestrator.list_workflows(status=status, limit=limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>')
def api_orchestration_workflow(workflow_id):
    """Get a single orchestration workflow."""
    try:
        orchestrator = orch.get_orchestrator()
        workflow = orchestrator.get_workflow(workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        return jsonify(workflow)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows', methods=['POST'])
def api_orchestration_submit():
    """Submit a new supervised orchestration workflow."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json() or {}
        goal = data.get('goal')
        if not goal:
            return jsonify({"error": "goal required"}), 400

        orchestrator = orch.get_orchestrator()
        result = orchestrator.submit_workflow(
            goal=goal,
            workflow_type=data.get('workflow_type', 'general'),
            requires_approval=bool(data.get('requires_approval', True)),
            max_retries=int(data.get('max_retries', 3)),
            enqueue=bool(data.get('enqueue', True)),
        )
        return jsonify(result), 201
    except Exception as e:
        logger.exception("Error submitting orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/run', methods=['POST'])
def api_orchestration_run(workflow_id):
    """Run or resume a workflow through the orchestration graph."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.run_workflow(workflow_id))
    except Exception as e:
        logger.exception("Error running orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/approvals')
def api_orchestration_approvals():
    """List workflows waiting for human approval."""
    try:
        orchestrator = orch.get_orchestrator()
        return jsonify({"pending": orchestrator.pending_approvals()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/approve', methods=['POST'])
def api_orchestration_approve(workflow_id):
    """Approve an orchestration workflow checkpoint."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.approve_workflow(
            workflow_id,
            decided_by=data.get('decided_by', 'user'),
            reason=data.get('reason', ''),
        ))
    except Exception as e:
        logger.exception("Error approving orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/reject', methods=['POST'])
def api_orchestration_reject(workflow_id):
    """Reject an orchestration workflow checkpoint."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.reject_workflow(
            workflow_id,
            decided_by=data.get('decided_by', 'user'),
            reason=data.get('reason', ''),
        ))
    except Exception as e:
        logger.exception("Error rejecting orchestration workflow")
        return jsonify({"error": str(e)}), 500


# ─── Intelligence Runtime API Endpoints ──────────────────────────────────────

@app.route('/api/memory/search')
def api_memory_search():
    """Search persistent vector memory."""
    try:
        namespace = request.args.get('namespace', 'workflow')
        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 5))
        if not query:
            return jsonify({"error": "q required"}), 400
        return jsonify({"results": get_memory().recall(namespace, query, limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/memory/remember', methods=['POST'])
def api_memory_remember():
    """Persist a memory item. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        namespace = data.get('namespace', 'project')
        content = data.get('content')
        if not content:
            return jsonify({"error": "content required"}), 400
        memory_id = get_memory().remember(namespace, content, data.get('metadata') or {})
        return jsonify({"memory_id": memory_id, "namespace": namespace}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/research/search', methods=['POST'])
def api_research_search():
    """Run live internet research through configured providers. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        query = data.get('query')
        if not query:
            return jsonify({"error": "query required"}), 400
        result = get_research_runtime().search(
            query,
            limit=int(data.get('limit', 5)),
            persist=bool(data.get('persist', True)),
        )
        return jsonify(result)
    except Exception as e:
        logger.exception("Research search failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/filesystem/index', methods=['POST'])
def api_filesystem_index():
    """Index a workspace for persistent filesystem awareness. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        root = data.get('root')
        if not root:
            return jsonify({"error": "root required"}), 400
        result = get_filesystem_indexer().index_workspace(root, int(data.get('max_files', 1000)))
        return jsonify(result)
    except Exception as e:
        logger.exception("Filesystem indexing failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/model-router/route', methods=['POST'])
def api_model_route():
    """Route a task to the best configured model."""
    try:
        data = request.get_json() or {}
        selection = get_model_router().route(
            data.get('task_type', 'general'),
            data.get('prompt', ''),
            bool(data.get('prefer_local', True)),
        )
        return jsonify(selection)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/model-router/status')
def api_model_router_status():
    """Get model routing capability registry."""
    try:
        return jsonify(get_model_router().status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tools')
def api_tools():
    """List supervised tools."""
    try:
        return jsonify({"tools": get_tool_registry().list_tools()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tools/run', methods=['POST'])
def api_tool_run():
    """Run a supervised tool. Mutating/terminal tools require auth."""
    try:
        data = request.get_json() or {}
        name = data.get('name')
        args = data.get('args') or {}
        if not name:
            return jsonify({"error": "name required"}), 400
        tool = get_tool_registry().tools.get(name)
        if not tool:
            return jsonify({"error": "Unknown tool"}), 404
        if tool.requires_approval:
            auth_token = request.headers.get('Authorization')
            if not verify_auth_token(auth_token):
                return jsonify({"error": "Unauthorized"}), 401
        result = tool.run(**args)
        return jsonify(result.__dict__)
    except Exception as e:
        logger.exception("Tool run failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/tools/registry')
def api_tools_registry():
    try:
        tools = list_tools()
        return jsonify({"tools": tools, "status": "ok", "data": tools, "error": None})
    except Exception as e:
        return jsonify({"tools": [], "status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/tools/find', methods=['POST'])
def api_tools_find():
    try:
        data = request.get_json() or {}
        task = data.get("task")
        if not task:
            return jsonify({"error": "task required"}), 400
        return jsonify({"tool": find_tool_for_task(task)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/workers/status')
def api_workers_status():
    """GET /api/workers/status — worker_manager pool + orchestrator logical workers."""
    try:
        import orchestrator as _orch_brain
        data = _orch_brain.get_orchestrator().worker_manager.get_worker_status()
        if not isinstance(data, dict):
            data = {"workers": data}
        with _live_lock:
            data["live"] = {k: dict(v) for k, v in live_workers.items()}
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_workers_status failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/approvals/pending')
def api_approvals_pending():
    """GET /api/approvals/pending — pending OpenClaw approval gates."""
    try:
        from openclaw.openclaw import get_openclaw
        data = get_openclaw().get_pending_approvals()
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_approvals_pending failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/approvals/resolve', methods=['POST'])
def api_approvals_resolve():
    """POST /api/approvals/resolve — resolve a pending approval gate.

    Body: { "approval_id": "...", "approved": true/false, "reason": "..." }
    """
    try:
        data = request.get_json() or {}
        approval_id = data.get("approval_id")
        if not approval_id:
            return jsonify({"status": "error", "data": None, "error": "approval_id required"}), 400

        approved = bool(data.get("approved", False))
        reason = str(data.get("reason", ""))

        from openclaw.openclaw import get_openclaw, ApprovalNotFoundError
        try:
            ok = get_openclaw().resolve_approval(
                approval_id=approval_id,
                approved=approved,
                reason=reason,
                resolved_by=data.get("resolved_by", "user"),
            )
        except ApprovalNotFoundError as anf:
            return jsonify({"status": "error", "data": None, "error": str(anf)}), 404

        resume_result = None
        if ok and approved:
            try:
                approval = get_openclaw().get_approval(approval_id)
                payload = (approval or {}).get("payload") or {}
                task_id = payload.get("task_id")
                desc = payload.get("task_description") or (approval or {}).get("description") or "your request"
                if task_id:
                    import orchestrator as _orch_brain
                    def _resume():
                        # Forge RUNNING — make the HUD show it, not idle (Issue 1/6).
                        set_worker("forge", "running", current_task=desc,
                                   activity=f"Forge started: {desc}")
                        emit_event("orb_state", {"state": "thinking"})
                        db.log_event("forge_started", f"Forge building: {desc[:160]}")
                        try:
                            res = _orch_brain.get_orchestrator().resume_approved_task(task_id)
                        except Exception as exc:
                            logger.exception("approved task resume failed: %s", exc)
                            res = {"status": "failed", "error": str(exc)}
                        status = (res or {}).get("status")
                        if status == "completed":
                            summary = _forge_summary(res)
                            set_worker("forge", "idle", current_task=None,
                                       activity=f"Forge completed: {summary}")
                            emit_event("task_update", {"task_id": task_id, "worker": "forge",
                                                       "status": "completed", "message": summary})
                            db.log_event("forge_completed", f"Forge done: {summary[:160]}")
                        else:
                            err = (res or {}).get("error") or "unknown error"
                            set_worker("forge", "error", current_task=None,
                                       activity=f"Forge failed: {err}")
                            emit_event("task_update", {"task_id": task_id, "worker": "forge",
                                                       "status": "failed", "message": err})
                            db.log_event("forge_failed", f"Forge failed: {str(err)[:160]}")
                        emit_event("orb_state", {"state": "idle"})
                    threading.Thread(target=_resume, daemon=True).start()
                    resume_result = {"status": "started", "task_id": task_id}
            except Exception as resume_exc:
                resume_result = {"status": "error", "error": str(resume_exc)}

        return jsonify({
            "status": "ok",
            "data": {"resolved": ok, "approval_id": approval_id, "resume_result": resume_result},
            "error": None,
        })
    except Exception as e:
        logger.exception("api_approvals_resolve failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/revenue/status')
def api_revenue_status():
    """GET /api/revenue/status — pipeline summary from DB."""
    try:
        earnings = db.get_earnings_summary()
        counts = db.count_opportunities_by_status()
        recent = db.list_opportunities(limit=10)
        data = {
            "earnings": earnings,
            "opportunity_counts": counts,
            "recent_opportunities": recent,
        }
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_revenue_status failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/tasks/submit', methods=['POST'])
def api_tasks_submit():
    """POST /api/tasks/submit — submit a task to the orchestrator.

    Body: { "description": "...", "source": "desktop"|"phone"|"api" }
    """
    try:
        data = request.get_json() or {}
        description = (data.get("description") or "").strip()
        if not description:
            return jsonify({"status": "error", "data": None, "error": "description required"}), 400

        source = data.get("source", "desktop")
        context = dict(data.get("context") or {})
        # Default: don't block the HTTP request while waiting for Forge approval.
        context.setdefault("wait_for_approval", False)

        task_id = data.get("task_id") or f"task-{__import__('uuid').uuid4().hex[:12]}"

        import orchestrator as _orch_brain
        result = _orch_brain.process_task(
            task_id=task_id,
            task_description=description,
            source=source,
            context=context,
        )

        # Safety check: if forge was selected but input has no technical content, override to ollama_general
        from workers.orchestration.task_decomposer import is_conversational_input
        if (result or {}).get("needs_forge") and is_conversational_input(description):
            logger.warning(
                "Safety override: non-technical input blocked from Forge — routing to ollama_general: %r",
                description,
            )
            result = {
                "status": "completed",
                "worker": "ollama_general",
                "intent": {"intent": "general"},
                "note": "Conversational input was rerouted from forge to general AI",
            }

        # Reflect routing in the live worker state so the dock/panels react (Issue 2/6).
        try:
            status = (result or {}).get("status")
            worker = (result or {}).get("worker")
            intent = (result or {}).get("intent") or {}
            itype = intent.get("intent") if isinstance(intent, dict) else None
            if status == "awaiting_approval" or (result or {}).get("needs_forge"):
                set_worker("forge", "running", current_task=description,
                           activity=f"Awaiting approval: {description}")
            else:
                wmap = {"repair": "repair", "search": "web", "monitor": "earn"}
                wkey = wmap.get(itype, worker if worker in live_workers else None)
                if wkey:
                    set_worker(wkey, "idle", current_task=None,
                               activity=f"Handled: {description[:80]}")
        except Exception:
            pass

        return jsonify({"status": "ok", "data": result, "error": None}), 201
    except Exception as e:
        logger.exception("api_tasks_submit failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/tasks/queue')
def api_tasks_queue():
    """GET /api/tasks/queue — orchestrator task queue status."""
    try:
        import orchestrator as _orch_brain
        data = _orch_brain.get_orchestrator().get_queue_status()
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_tasks_queue failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


# ─── Wrap existing /api/tools/registry & /api/tools/find in the new envelope ──
# (the old routes already exist above and return {tools:…} / {tool:…} —
#  we keep them as-is for backwards compat and add envelope wrappers at the new paths)

@app.route('/api/tools/list')
def api_tools_list():
    """GET /api/tools/list — capability registry (new {status,data,error} envelope)."""
    try:
        return jsonify({"status": "ok", "data": list_tools(), "error": None})
    except Exception as e:
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/models/status')
def api_models_status():
    try:
        from models import model_manager, model_registry
        model_registry.init_registry()
        data = {
            "loaded": model_manager.get_loaded_models(),
            "models": model_registry.get_all_models(),
        }
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_models_status failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/models/hardware')
def api_models_hardware():
    try:
        from models import hardware_detector
        return jsonify({"status": "ok", "data": hardware_detector.detect_hardware(), "error": None})
    except Exception as e:
        logger.exception("api_models_hardware failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/models/load', methods=['POST'])
def api_models_load():
    try:
        from models import model_manager
        data = request.get_json() or {}
        tag = data.get("tag") or data.get("ollama_tag")
        if not tag:
            return jsonify({"status": "error", "data": None, "error": "tag required"}), 400
        ok = model_manager.ensure_model_loaded(tag)
        return jsonify({"status": "ok" if ok else "error", "data": {"loaded": ok, "tag": tag}, "error": None if ok else "model unavailable"})
    except Exception as e:
        logger.exception("api_models_load failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/models/unload', methods=['POST'])
def api_models_unload():
    try:
        from models import model_manager
        data = request.get_json() or {}
        tag = data.get("tag") or data.get("ollama_tag")
        if not tag:
            return jsonify({"status": "error", "data": None, "error": "tag required"}), 400
        ok = model_manager.unload_model(tag)
        return jsonify({"status": "ok" if ok else "error", "data": {"unloaded": ok, "tag": tag}, "error": None if ok else "model unavailable"})
    except Exception as e:
        logger.exception("api_models_unload failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/setup/status')
def api_setup_status():
    try:
        from models import hardware_detector, model_registry, setup_wizard
        model_registry.init_registry()
        data = {
            "complete": not setup_wizard.is_first_run(),
            "hardware": hardware_detector.detect_hardware(),
            "models": model_registry.get_all_models(),
        }
        return jsonify({"status": "ok", "data": data, "error": None})
    except Exception as e:
        logger.exception("api_setup_status failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/reflection/workflows/<int:workflow_id>', methods=['POST'])
def api_reflect_workflow(workflow_id):
    """Run a reflection pass on a workflow. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        workflow = orch.get_orchestrator().get_workflow(workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        return jsonify(ReflectionEngine().reflect(workflow))
    except Exception as e:
        logger.exception("Reflection failed")
        return jsonify({"error": str(e)}), 500


# ─── Voice (Task 5) ───────────────────────────────────────────────────────────

@app.route('/api/voice/capabilities')
def api_voice_caps():
    try:
        import voice_io
        return jsonify({"status": "ok", "data": voice_io.capabilities(), "error": None})
    except Exception as e:
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/voice/input', methods=['POST'])
def api_voice_input():
    """Receive an audio blob, transcribe it, route the text to OpenClaw.

    Returns {transcribed, response, orb_state}. Falls back gracefully to a
    text-only message if no STT backend is available.
    """
    import tempfile
    import voice_io
    try:
        emit_event("orb_state", {"state": "thinking"})
        audio = request.files.get("audio")
        if not audio:
            return jsonify({"status": "error", "data": None, "error": "no audio file"}), 400

        suffix = os.path.splitext(audio.filename or "voice.webm")[1] or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio.save(tmp.name)
            tmp_path = tmp.name

        stt = voice_io.transcribe(tmp_path)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if not stt.get("ok") or not stt.get("text"):
            emit_event("orb_state", {"state": "idle"})
            return jsonify({"status": "ok", "data": {
                "transcribed": "", "response": None, "orb_state": "idle",
                "note": "STT unavailable — type your command instead",
                "stt_backend": stt.get("backend"), "stt_error": stt.get("error"),
            }, "error": None})

        text = stt["text"]
        from openclaw.openclaw import get_openclaw
        oc_result = get_openclaw().receive_message("desktop", text, {"wait_for_approval": False})
        data = oc_result.get("data") if isinstance(oc_result, dict) else {}
        response_text = (data or {}).get("response") or _summarize_task_result(data)
        emit_event("orb_state", {"state": "speaking"})
        return jsonify({"status": "ok", "data": {
            "transcribed": text, "response": response_text, "orb_state": "speaking",
            "stt_backend": stt.get("backend"),
        }, "error": None})
    except Exception as e:
        logger.exception("api_voice_input failed")
        emit_event("orb_state", {"state": "idle"})
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


def _summarize_task_result(data) -> str:
    if not isinstance(data, dict):
        return "Acknowledged."
    if data.get("status") == "awaiting_approval":
        return "That action needs your approval."
    if data.get("response"):
        return data["response"]
    intent = data.get("intent")
    if intent:
        itype = intent.get("type") if isinstance(intent, dict) else intent
        return f"Routed as {itype} to {data.get('worker', 'orchestrator')}."
    return f"Task {data.get('status', 'received')}."


@app.route('/api/voice/speak', methods=['POST'])
def api_voice_speak():
    """Generate TTS for text. Plays on the host if possible; the HUD also has a
    browser SpeechSynthesis fallback so the user always hears a response."""
    import voice_io
    try:
        data = request.get_json() or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"status": "error", "data": None, "error": "text required"}), 400

        emit_event("orb_state", {"state": "speaking"})
        result = voice_io.synthesize(text)
        # Best-effort local playback (non-blocking) when a wav was produced.
        if result.get("ok") and result.get("path"):
            def _play(path):
                try:
                    if sys.platform.startswith("win"):
                        import winsound
                        winsound.PlaySound(path, winsound.SND_FILENAME)
                    elif sys.platform == "darwin":
                        subprocess.run(["afplay", path], check=False)
                    else:
                        subprocess.run(["aplay", path], check=False)
                except Exception:
                    pass
                finally:
                    emit_event("orb_state", {"state": "idle"})
            threading.Thread(target=_play, args=(result["path"],), daemon=True).start()
        else:
            emit_event("orb_state", {"state": "idle"})
        return jsonify({"status": "ok", "data": {
            "backend": result.get("backend"), "spoken": result.get("ok"),
            "error": result.get("error"),
        }, "error": None})
    except Exception as e:
        logger.exception("api_voice_speak failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


# ─── EARN dashboard endpoints (Task 6) ─────────────────────────────────────────

@app.route('/api/revenue/bounties/live')
def api_revenue_bounties_live():
    """Live bounty feed for the EARN scanner. Returns fresh GitHub results.

    Network-dependent — returns an empty list with a note when offline or
    rate-limited rather than failing.
    """
    from revenue import bounty_pipeline

    # find_bounty_issues makes many blocking GitHub calls; cap it at ~10s and
    # fall back to sample data so the EARN scanner never spins forever (Issue 3).
    box = {"issues": None, "error": None}

    def _scan():
        try:
            box["issues"] = bounty_pipeline.find_bounty_issues(max=8)
        except Exception as exc:
            box["error"] = str(exc)

    worker = threading.Thread(target=_scan, daemon=True)
    worker.start()
    worker.join(timeout=10)

    def _fmt(issues):
        return [{
            "repo": i.get("repo"),
            "title": i.get("title"),
            "labels": i.get("labels", []),
            "score": i.get("score"),
            "estimate": "$" + str(int((i.get("score") or 0) * 500)),
            "url": i.get("url"),
        } for i in issues]

    if box["issues"]:
        return jsonify({"status": "ok", "data": {
            "bounties": _fmt(box["issues"]), "source": "live"}, "error": None})

    # Timed out, errored (rate limit), or empty → sample feed + helpful note.
    has_token = bool(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"))
    note = ("Scanner timed out — showing sample bounties."
            if box["error"] is None and not has_token
            else "GitHub rate-limited (set GITHUB_TOKEN for live results) — showing sample bounties.")
    sample = [
        {"repo": "octocat/Hello-World", "title": "Fix typo in README", "labels": ["good-first-issue", "docs"], "score": 0.75, "estimate": "$375", "url": "https://github.com/octocat/Hello-World/issues/1"},
        {"repo": "psf/requests", "title": "Improve error message on timeout", "labels": ["bounty", "good-first-issue"], "score": 0.62, "estimate": "$310", "url": "https://github.com/psf/requests/issues/2"},
        {"repo": "pallets/flask", "title": "Add example for blueprints", "labels": ["docs", "help-wanted"], "score": 0.5, "estimate": "$250", "url": "https://github.com/pallets/flask/issues/3"},
        {"repo": "expressjs/express", "title": "Handle edge case in router", "labels": ["bug", "bounty"], "score": 0.45, "estimate": "$225", "url": "https://github.com/expressjs/express/issues/4"},
    ]
    return jsonify({"status": "ok", "data": {
        "bounties": sample, "source": "sample", "note": note}, "error": None})


@app.route('/api/revenue/active')
def api_revenue_active():
    """Currently-active repairs from the task queue."""
    try:
        tasks = qm.list_tasks(limit=200)
        active = []
        for t in tasks:
            if t.get("task_type") == "repair_execute" and t.get("status") in ("pending", "running"):
                td = t.get("task_data") or {}
                issue = td.get("issue") or {}
                active.append({
                    "repo": issue.get("repo") or f"opp-{t.get('opportunity_id')}",
                    "issue": issue.get("title") or t.get("opportunity_id"),
                    "step": t.get("status"),
                    "status": t.get("status"),
                })
        return jsonify({"status": "ok", "data": {"active": active}, "error": None})
    except Exception as e:
        logger.exception("api_revenue_active failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/revenue/history')
def api_revenue_history():
    """Completed repairs / submissions for the EARN history table."""
    try:
        subs = db.list_submissions()
        history = [{
            "repo": s.get("repo_url") or s.get("repo") or "",
            "issue": s.get("issue_url") or s.get("title") or "",
            "pr_url": s.get("pr_url"),
            "status": s.get("status"),
            "amount": s.get("amount") or s.get("bounty_amount") or 0,
        } for s in subs]
        return jsonify({"status": "ok", "data": {"history": history}, "error": None})
    except Exception as e:
        logger.exception("api_revenue_history failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/personality', methods=['GET', 'POST'])
def api_personality():
    """GET active voice personality; POST to set it (Task 5)."""
    try:
        from models import setup_wizard
        if request.method == 'POST':
            data = request.get_json() or {}
            result = setup_wizard.personality_setup(
                data.get("choice", "sentinel"), data.get("custom_prompt", ""))
            return jsonify({"status": "ok", "data": result, "error": None})
        return jsonify({"status": "ok", "data": setup_wizard.get_personality(), "error": None})
    except Exception as e:
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


def _forge_summary(res) -> str:
    """Human summary of a forge result dict."""
    try:
        r = (res or {}).get("result") or {}
        fr = r.get("forge_result") or {}
        files = fr.get("files_changed") or fr.get("files")
        if files:
            shown = ", ".join(str(f) for f in files[:4])
            via = f" (via {fr.get('fallback')} fallback)" if fr.get("fallback") else ""
            return f"built {shown}{via}"
        summary = fr.get("summary") or fr.get("output_path") or r.get("output_path")
        if summary:
            return str(summary)[:200]
        return "tool built and registered"
    except Exception:
        return "tool built"


# ─── Guardian (Issue 2) ────────────────────────────────────────────────────────

# Skip heavy / non-source dirs when sweeping the project tree.
_GUARDIAN_SKIP = {".git", "node_modules", "__pycache__", ".pytest_cache", "jarvis-orb",
                  "venv", ".venv", "built", "data", "launch_logs", "electron_logs"}


def _iter_project_files(root, exts, limit=4000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _GUARDIAN_SKIP]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                yield os.path.join(dirpath, fn)
                count += 1
                if count >= limit:
                    return


@app.route('/api/guardian/scan', methods=['POST'])
def api_guardian_scan():
    """Scan the SentinelAI directory for threat signatures."""
    from workers import guardian_worker
    try:
        set_worker("guardian", "scanning", current_task="scanning project tree")
        root = str(Path(__file__).parent)
        findings = []
        scanned = 0
        for fp in _iter_project_files(root, {".py", ".js", ".cjs", ".sh", ".ps1", ".bat", ".txt", ".md"}):
            scanned += 1
            try:
                res = guardian_worker.scan_file(fp)
            except Exception:
                continue
            if not res.get("clean"):
                for threat, detail in zip(res.get("threats", []), res.get("details", []) + [""] * len(res.get("threats", []))):
                    findings.append({"file": os.path.relpath(fp, root), "threat": threat,
                                     "severity": "high" if "Executable" in threat or "Script" in threat else "medium",
                                     "detail": detail})
        last_scan = datetime.now().isoformat()
        status = "threat" if findings else "idle"
        set_worker("guardian", status, current_task=None,
                   activity=(f"Scan complete — {len(findings)} finding(s) in {scanned} files"),
                   extra={"last_scan": last_scan, "findings": findings})
        db.log_event("guardian_scan_complete", f"scanned={scanned} findings={len(findings)}")
        return jsonify({"status": "ok", "data": {
            "clean": not findings, "findings": findings, "scanned": scanned, "last_scan": last_scan,
        }, "error": None})
    except Exception as e:
        logger.exception("api_guardian_scan failed")
        set_worker("guardian", "error", current_task=None, activity=f"scan error: {e}")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/guardian/check-keys', methods=['POST'])
def api_guardian_check_keys():
    """Scan .py/.js/.env files for exposed API keys."""
    from workers import guardian_worker
    try:
        set_worker("guardian", "scanning", current_task="checking for exposed keys")
        root = str(Path(__file__).parent)
        exposures = []
        scanned = 0
        for fp in _iter_project_files(root, {".py", ".js", ".cjs", ".env", ".json", ".yaml", ".yml"}):
            scanned += 1
            try:
                text = Path(fp).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for det in guardian_worker.check_api_key_exposure(text):
                m = det.get("match", "")
                exposures.append({
                    "file": os.path.relpath(fp, root),
                    "type": det.get("type"),
                    "severity": "critical",
                    "match_preview": (m[:6] + "…" + m[-4:]) if len(m) > 12 else "***",
                })
        status = "threat" if exposures else "idle"
        set_worker("guardian", status, current_task=None,
                   activity=f"Key check — {len(exposures)} exposure(s) in {scanned} files")
        db.log_event("guardian_keycheck_complete", f"scanned={scanned} exposures={len(exposures)}")
        return jsonify({"status": "ok", "data": {"exposures": exposures, "scanned": scanned}, "error": None})
    except Exception as e:
        logger.exception("api_guardian_check_keys failed")
        set_worker("guardian", "error", current_task=None)
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


# ─── System Monitor (Issue 7) ──────────────────────────────────────────────────

@app.route('/api/system/stats')
def api_system_stats():
    """CPU / RAM / DISK (+ GPU when nvidia-smi is present) for the HUD monitor."""
    data = {"cpu": {"percent": 0}, "ram": {"percent": 0}, "disk": {"percent": 0}, "gpu": None}
    try:
        import psutil
        data["cpu"] = {"percent": round(psutil.cpu_percent(interval=0.0), 1)}
        vm = psutil.virtual_memory()
        data["ram"] = {"percent": round(vm.percent, 1),
                       "used_gb": round(vm.used / 1e9, 1), "total_gb": round(vm.total / 1e9, 1)}
        du = psutil.disk_usage(os.path.expanduser("~"))
        data["disk"] = {"percent": round(du.percent, 1),
                        "used_gb": round(du.used / 1e9, 1), "total_gb": round(du.total / 1e9, 1)}
    except Exception as e:
        logger.debug("psutil stats failed: %s", e)
    # GPU via nvidia-smi (optional).
    try:
        from shutil import which
        if which("nvidia-smi"):
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.total,memory.used,name",
                 "--format=csv,noheader,nounits"],
                text=True, capture_output=True, timeout=4, check=False)
            line = (out.stdout or "").strip().splitlines()[0] if out.stdout.strip() else ""
            if line:
                parts = [p.strip() for p in line.split(",")]
                util, mtot, mused = float(parts[0]), float(parts[1]), float(parts[2])
                data["gpu"] = {"percent": round(util, 1), "name": parts[3] if len(parts) > 3 else "GPU",
                               "vram_gb": round(mtot / 1024, 1),
                               "vram_used_gb": round(mused / 1024, 1)}
    except Exception as e:
        logger.debug("nvidia-smi failed: %s", e)
    return jsonify({"status": "ok", "data": data, "error": None})


# ─── Pipeline management (Issue 3) ──────────────────────────────────────────────

@app.route('/api/revenue/pipeline')
def api_revenue_pipeline():
    """Queued repair tasks, in priority order."""
    try:
        tasks = qm.list_tasks(limit=200)
        pipeline = []
        for t in tasks:
            if t.get("task_type") == "repair_execute" and t.get("status") == "pending":
                td = t.get("task_data") or {}
                issue = td.get("issue") or {}
                opp = None
                try:
                    opp = db.get_opportunity(t.get("opportunity_id")) if t.get("opportunity_id") else None
                except Exception:
                    opp = None
                pipeline.append({
                    "task_id": t.get("id"),
                    "opportunity_id": t.get("opportunity_id"),
                    "repo": issue.get("repo") or (opp or {}).get("repo_url") or "",
                    "issue": issue.get("title") or (opp or {}).get("title") or f"opp-{t.get('opportunity_id')}",
                    "score": issue.get("score"),
                })
        return jsonify({"status": "ok", "data": {"pipeline": pipeline}, "error": None})
    except Exception as e:
        logger.exception("api_revenue_pipeline failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/revenue/pipeline/remove', methods=['POST'])
def api_revenue_pipeline_remove():
    try:
        data = request.get_json() or {}
        task_id = data.get("task_id")
        if task_id is None:
            return jsonify({"status": "error", "data": None, "error": "task_id required"}), 400
        qm.cancel_task(int(task_id))
        return jsonify({"status": "ok", "data": {"removed": task_id}, "error": None})
    except Exception as e:
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/revenue/pipeline/clear', methods=['POST'])
def api_revenue_pipeline_clear():
    try:
        tasks = qm.list_tasks(limit=500)
        cleared = 0
        for t in tasks:
            if t.get("task_type") == "repair_execute" and t.get("status") == "pending":
                try:
                    qm.cancel_task(int(t.get("id")))
                    cleared += 1
                except Exception:
                    pass
        return jsonify({"status": "ok", "data": {"cleared": cleared}, "error": None})
    except Exception as e:
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


# ─── Memory Endpoints ──────────────────────────────────────────────────────────

@app.route('/api/memory/recent')
def api_memory_recent():
    """Get recent memory entries from a subdirectory"""
    try:
        subdir = request.args.get('subdir', 'sessions')
        n = int(request.args.get('n', 10))

        mm = get_memory_manager()
        entries = mm.read_recent(subdir, n)

        return jsonify({"status": "ok", "data": entries, "error": None})
    except Exception as e:
        logger.exception("Memory recent fetch failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/memory/vault/search')
def api_memory_vault_search():
    """Search the memory vault (file-system corpus)."""
    try:
        query = request.args.get('q', '')
        if not query:
            return jsonify({"status": "error", "data": None, "error": "Query parameter 'q' required"}), 400

        max_results = int(request.args.get('max_results', 20))

        mm = get_memory_manager()
        results = mm.search_vault(query, max_results)

        return jsonify({"status": "ok", "data": results, "error": None})
    except Exception as e:
        logger.exception("Memory vault search failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


@app.route('/api/memory/session', methods=['POST'])
def api_memory_session():
    """Write a session summary to memory"""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id', datetime.now().strftime("%Y%m%d_%H%M%S"))
        summary_dict = data.get('summary', {})

        mm = get_memory_manager()
        filepath = mm.write_session(session_id, summary_dict)

        return jsonify({"status": "ok", "data": {"filepath": str(filepath)}, "error": None})
    except Exception as e:
        logger.exception("Memory session write failed")
        return jsonify({"status": "error", "data": None, "error": str(e)}), 500


# ─── Voice Endpoints (Track 8) ────────────────────────────────────────────────

@app.route('/voice/wake', methods=['POST'])
def api_voice_wake():
    """Wake word detected"""
    try:
        data = request.get_json() or {}
        logger.info(f"Wake word detected: {data}")

        # Broadcast to orb window via IPC if socketio available
        emit_event("wake_word_detected", data)

        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/voice/mute', methods=['POST'])
def api_voice_mute():
    """Mute wake word detection"""
    try:
        from workers.voice.wake_word import mute_detector
        mute_detector()
        return jsonify({"status": "ok", "message": "Wake word muted"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/voice/unmute', methods=['POST'])
def api_voice_unmute():
    """Unmute wake word detection"""
    try:
        from workers.voice.wake_word import unmute_detector
        unmute_detector()
        return jsonify({"status": "ok", "message": "Wake word unmuted"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/voice/status')
def api_voice_status():
    """Get wake word detector status"""
    try:
        from workers.voice.wake_word import get_status
        status = get_status()
        return jsonify({"status": "ok", "data": status})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── OpenClaw Endpoints (Track 5) ─────────────────────────────────────────────

@app.route('/openclaw/calendar/create', methods=['POST'])
def api_openclaw_calendar_create():
    """Create calendar event"""
    try:
        from workers.openclaw.openclaw_worker import handle_intent
        data = request.get_json() or {}
        result = handle_intent("calendar.create", data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/openclaw/calendar/upcoming')
def api_openclaw_calendar_upcoming():
    """Get upcoming calendar events"""
    try:
        from workers.openclaw.openclaw_worker import handle_intent
        days = int(request.args.get('days', 7))
        result = handle_intent("calendar.list", {"days": days})
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/openclaw/web/search', methods=['POST'])
def api_openclaw_web_search():
    """Web search via Brave"""
    try:
        # Check web search limit for free tier
        limit_check = license_manager.check_limit("web_searches")
        if not limit_check["allowed"]:
            return jsonify({"status": "error", "message": limit_check["message"], "code": "limit_reached"}), 403

        from workers.openclaw.openclaw_worker import handle_intent
        data = request.get_json() or {}
        result = handle_intent("web.search", data)

        license_manager.increment_usage("web_searches")  # Track usage

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/openclaw/notes/create', methods=['POST'])
def api_openclaw_notes_create():
    """Create a note"""
    try:
        from workers.openclaw.openclaw_worker import handle_intent
        data = request.get_json() or {}
        result = handle_intent("notes.create", data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/openclaw/reminders/due')
def api_openclaw_reminders_due():
    """Get due reminders"""
    try:
        from workers.openclaw.openclaw_worker import handle_intent
        result = handle_intent("reminders.due", {})
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/openclaw/health')
def api_openclaw_health():
    """OpenClaw health check"""
    return jsonify({"status": "ok", "worker": "openclaw"})


# ─── Messaging Endpoints (Track 9) ────────────────────────────────────────────

@app.route('/messaging/send/telegram', methods=['POST'])
def api_messaging_send_telegram():
    """Send message via Telegram"""
    # TODO: Implement direct send (currently handled by bridge)
    return jsonify({"status": "error", "message": "Use Telegram bridge for bidirectional communication"})


@app.route('/messaging/status')
def api_messaging_status():
    """Get messaging bridge status"""
    return jsonify({
        "status": "ok",
        "telegram": bool(os.getenv('TELEGRAM_BOT_TOKEN')),
        "whatsapp": False  # Experimental/disabled
    })


# ─── Home Assistant Endpoints (Track 10) ──────────────────────────────────────

@app.route('/home/status')
def api_home_status():
    """Home Assistant status"""
    try:
        feature_check = license_manager.check_feature("home_assistant")
        if not feature_check["allowed"]:
            return jsonify({
                "status": "ok",
                "connected": False,
                "url": None,
                "note": feature_check.get("message", "Home Assistant requires Pro tier"),
                "code": "pro_required"
            })

        from workers.home.home_assistant import get_ha_bridge
        ha = get_ha_bridge()
        return jsonify({
            "status": "ok",
            "connected": ha.connected,
            "url": ha.ha_url
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/cameras')
def api_home_cameras():
    """List cameras"""
    try:
        feature_check = license_manager.check_feature("cameras")
        if not feature_check["allowed"]:
            return jsonify({"status": "error", "error": feature_check["message"], "code": "pro_required"}), 403

        from workers.home.camera_worker import list_cameras
        cameras = list_cameras()
        return jsonify({"status": "ok", "data": cameras})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/camera/look', methods=['POST'])
def api_home_camera_look():
    """Look at specific camera"""
    try:
        feature_check = license_manager.check_feature("cameras")
        if not feature_check["allowed"]:
            return jsonify({"status": "error", "error": feature_check["message"], "code": "pro_required"}), 403

        from workers.home.camera_worker import look_at
        data = request.get_json() or {}
        camera_name = data.get('camera_name', '')
        result = look_at(camera_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/camera/look_all', methods=['POST'])
def api_home_camera_look_all():
    """Look at all cameras"""
    try:
        feature_check = license_manager.check_feature("cameras")
        if not feature_check["allowed"]:
            return jsonify({"status": "error", "error": feature_check["message"], "code": "pro_required"}), 403

        from workers.home.camera_worker import look_at_all
        result = look_at_all()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/lights')
def api_home_lights():
    """Get all lights"""
    try:
        from workers.home.home_assistant import get_ha_bridge
        ha = get_ha_bridge()
        lights = ha.get_lights()
        return jsonify({"status": "ok", "data": lights})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/lights/on', methods=['POST'])
def api_home_lights_on():
    """Turn lights on"""
    try:
        from workers.home.home_assistant import get_ha_bridge
        data = request.get_json() or {}
        entity_id = data.get('entity_id')

        ha = get_ha_bridge()
        success = ha.turn_on(entity_id)

        return jsonify({"status": "ok" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/lights/off', methods=['POST'])
def api_home_lights_off():
    """Turn lights off"""
    try:
        from workers.home.home_assistant import get_ha_bridge
        data = request.get_json() or {}
        entity_id = data.get('entity_id')

        ha = get_ha_bridge()
        success = ha.turn_off(entity_id)

        return jsonify({"status": "ok" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/home/command', methods=['POST'])
def api_home_command():
    """Natural language home command"""
    try:
        from workers.home.home_assistant import get_ha_bridge
        data = request.get_json() or {}
        command = data.get('command', '')

        ha = get_ha_bridge()
        result = ha.natural_language_command(command)

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── Proactive Endpoints (Track 11) ───────────────────────────────────────────

@app.route('/proactive/status')
def api_proactive_status():
    """Get scheduler status"""
    try:
        from workers.proactive.scheduler import get_scheduler
        scheduler = get_scheduler()

        if scheduler:
            return jsonify({"status": "ok", "data": scheduler.get_status()})
        else:
            return jsonify({"status": "ok", "data": {"running": False}})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/proactive/trigger/morning', methods=['POST'])
def api_proactive_trigger_morning():
    """Manually trigger morning briefing"""
    try:
        from workers.proactive.scheduler import get_scheduler
        scheduler = get_scheduler()

        if scheduler:
            scheduler._morning_briefing()
            return jsonify({"status": "ok", "message": "Morning briefing triggered"})
        else:
            return jsonify({"status": "error", "message": "Scheduler not running"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── Health Endpoints (Track 12) ──────────────────────────────────────────────

@app.route('/health/summary')
def api_health_summary():
    """Get health summary"""
    try:
        from workers.health.wearables import get_health_summary
        result = get_health_summary()
        return jsonify({"status": "ok" if not result.get('error') else "error", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/health/sleep')
def api_health_sleep():
    """Get sleep data"""
    try:
        from workers.health.wearables import get_sleep_data
        days = int(request.args.get('days', 7))
        result = get_sleep_data(days)
        return jsonify({"status": "ok" if not result.get('error') else "error", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── Finance Endpoints (Track 13) ─────────────────────────────────────────────

@app.route('/finance/summary')
def api_finance_summary():
    """Get finance summary"""
    try:
        from workers.finance.firefly import get_firefly
        firefly = get_firefly()
        summary = firefly.finance_summary()
        return jsonify({"status": "ok", "data": {"summary": summary}})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/finance/accounts')
def api_finance_accounts():
    """Get all accounts"""
    try:
        from workers.finance.firefly import get_firefly
        firefly = get_firefly()
        result = firefly.get_account_summary()
        return jsonify({"status": "ok" if not result.get('error') else "error", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── Entertainment Endpoints (Track 14) ───────────────────────────────────────

@app.route('/entertainment/spotify/play', methods=['POST'])
def api_spotify_play():
    """Play track on Spotify"""
    try:
        from workers.entertainment.spotify import get_spotify
        data = request.get_json() or {}
        query = data.get('query', '')

        spotify = get_spotify()
        result = spotify.play(query)

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/entertainment/spotify/pause', methods=['POST'])
def api_spotify_pause():
    """Pause Spotify"""
    try:
        from workers.entertainment.spotify import get_spotify
        spotify = get_spotify()
        result = spotify.pause()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/entertainment/spotify/current')
def api_spotify_current():
    """Get current track"""
    try:
        from workers.entertainment.spotify import get_spotify
        spotify = get_spotify()
        result = spotify.current_track()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Logistics Endpoints (Track 15) ───────────────────────────────────────────

@app.route('/logistics/packages')
def api_logistics_packages():
    """Get all tracked packages"""
    try:
        from workers.logistics.package_tracker import get_all_packages
        packages = get_all_packages()
        return jsonify({"status": "ok", "data": packages})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/logistics/packages/add', methods=['POST'])
def api_logistics_packages_add():
    """Add a package to track"""
    try:
        from workers.logistics.package_tracker import add_package
        data = request.get_json() or {}

        result = add_package(
            data.get('tracking_number', ''),
            data.get('carrier', ''),
            data.get('description', '')
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/logistics/packages/check')
def api_logistics_packages_check():
    """Check all packages for updates"""
    try:
        from workers.logistics.package_tracker import check_deliveries
        result = check_deliveries()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── News Endpoints (Track 16) ────────────────────────────────────────────────

@app.route('/news/headlines')
def api_news_headlines():
    """Get news headlines"""
    try:
        from workers.news.miniflux_reader import get_news_reader
        reader = get_news_reader()
        limit = int(request.args.get('limit', 5))
        headlines = reader.get_headlines(limit)
        return jsonify({"status": "ok", "data": headlines})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/news/unread')
def api_news_unread():
    """Get unread news articles"""
    try:
        from workers.news.miniflux_reader import get_news_reader
        reader = get_news_reader()
        limit = int(request.args.get('limit', 10))
        result = reader.get_unread(limit)
        return jsonify({"status": "ok" if not result.get('error') else "error", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── Orchestration Pipeline API ───────────────────────────────────────────────

_BUILD_KEYWORDS = [
    'build', 'create', 'make', 'write', 'develop', 'code',
    'script', 'app', 'program', 'tool', 'website', 'dashboard',
]


def _is_build_request(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _BUILD_KEYWORDS)


@app.route('/orchestration/chat', methods=['POST'])
def api_orchestration_chat():
    """Process user request through orchestration pipeline."""
    try:
        data = request.get_json()
        user_request = data.get('message', '')

        if not user_request:
            return jsonify({"error": "No message provided"}), 400

        log(f'Chat: {user_request[:100]}', 'info', 'system')

        # Route build requests directly to Aider
        if _is_build_request(user_request):
            description = user_request
            import re as _re
            # Detect explicit file/path target in message
            path_match = _re.search(
                r'(?:save|write|put)\s+(?:it\s+)?(?:to|at|in)\s+(C:\\[^\s,\.]+|/[^\s,\.]+)',
                user_request, _re.IGNORECASE
            )
            if path_match:
                explicit_path = path_match.group(1).strip().rstrip('.')
                # If it looks like a file (has extension), use its parent as output_path
                from pathlib import Path as _Path
                ep = _Path(explicit_path)
                output_path = str(ep.parent) if ep.suffix else explicit_path
            else:
                name_match = _re.search(
                    r'(?:called?|named?|for)\s+([a-zA-Z0-9_\-]+)', user_request, _re.IGNORECASE
                )
                proj_name = name_match.group(1) if name_match else "sentinel_project"
                output_path = rf"C:\Users\pgg12\Desktop\{proj_name}"

            def build():
                try:
                    from workers.aider_engine import AiderEngine
                    engine = AiderEngine(socketio)
                    result = engine.build_app(description, output_path)
                    log(
                        'Build complete' if result.success else f'Build failed: {result.error}',
                        'success' if result.success else 'error',
                        'forge',
                    )
                    emit_event('forge_complete', {
                        'success': result.success,
                        'output': result.output[:2000],
                        'files_modified': result.files_modified,
                        'entry_point': result.entry_point,
                        'output_dir': result.output_dir,
                        'error': result.error,
                    })
                except Exception as exc:
                    log(f'Build error: {exc}', 'error', 'forge')
                    emit_event('forge_complete', {'success': False, 'output': str(exc), 'files_modified': [], 'entry_point': None, 'output_dir': None, 'error': str(exc)})

            t = threading.Thread(target=build, daemon=True)
            t.start()

            response_text = (
                f"On it. Building {description[:80]} now. "
                f"Watch the Log tab for live progress."
            )
            log(f'Response: {response_text[:100]}', 'info', 'system')
            return jsonify({"response": response_text, "worker": "aider"})

        lower = user_request.lower()

        # ── Real-time data — runs before pipeline ─────────────────────────────
        if any(w in lower for w in ['weather', 'temperature', 'forecast', 'raining', 'sunny']):
            import re as _re_wx
            _city_match = _re_wx.search(r'(?:weather|forecast|temperature)\s+(?:in|for|at)\s+([A-Za-z\s]+?)(?:\?|$|,)', lower)
            _lat, _lon, _city = 37.3382, -121.8863, "San Jose"
            if _city_match:
                _qcity = _city_match.group(1).strip()
                _glat, _glon, _gname = geocode_city(_qcity)
                if _glat:
                    _lat, _lon, _city = _glat, _glon, _gname
            wx = get_weather_data(_lat, _lon, _city)
            if 'error' not in wx:
                resp = (f"Current weather in {_city}: {wx['temp']}°F (feels like {wx['feels_like']}°F), "
                        f"{wx['condition']}. Wind {wx['wind']} mph, humidity {wx['humidity']}%. "
                        f"Today: high {wx['today_high']}°F / low {wx['today_low']}°F, {wx['rain_chance']}% chance of rain.")
            else:
                resp = "Could not fetch weather data right now."
            log(f'Weather response: {resp[:80]}', 'info', 'system')
            return jsonify({"response": resp, "worker": "general"})

        if any(w in lower for w in ['what time', 'current time', "what's the time"]):
            try:
                import pytz as _pytz
                from datetime import datetime as _dt2
                tz = _pytz.timezone('America/Los_Angeles')
                now = _dt2.now(tz)
                resp = f"It's {now.strftime('%I:%M %p')} Pacific Time, {now.strftime('%A, %B %d, %Y')}."
            except Exception:
                from datetime import datetime as _dt2
                resp = f"It's {_dt2.now().strftime('%I:%M %p')} local time."
            return jsonify({"response": resp, "worker": "general"})

        if any(w in lower for w in ['bitcoin price', 'btc price', 'what is bitcoin']):
            btc = get_crypto_price("bitcoin")
            if 'error' not in btc:
                direction = "▲" if btc['change_24h'] > 0 else "▼"
                resp = f"Bitcoin: ${btc['price']:,.2f} {direction} {abs(btc['change_24h'])}% in the last 24h."
            else:
                resp = "Could not fetch Bitcoin price."
            return jsonify({"response": resp, "worker": "general"})

        from workers.orchestration.pipeline import get_pipeline
        from workers.orchestration.task_decomposer import is_conversational_input
        pipeline = get_pipeline()
        result = pipeline.process(user_request)

        # Safety check: if forge was routed for non-technical input, override to ollama_general
        if is_conversational_input(user_request):
            plan = result.get("plan") or {}
            for subtask in plan.get("subtasks", []):
                if subtask.get("worker") == "forge":
                    logger.warning(
                        "Safety override: non-technical input routed to forge — overriding to ollama_general: %r",
                        user_request,
                    )
                    subtask["worker"] = "ollama_general"
                    subtask["type"] = "GENERAL"

        resp_str = result.get("response", "")
        log(f'Response: {str(resp_str)[:100]}', 'info', 'system')
        return jsonify(result)
    except Exception as e:
        logger.error("Orchestration chat failed: %s", e)
        log(str(e), 'error', 'system')
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/plan/<plan_id>/approve', methods=['POST'])
def api_orchestration_plan_approve(plan_id):
    """Approve and execute a pending plan"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        result = pipeline.approve_plan(plan_id)

        emit_event("plan_executed", {"plan_id": plan_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/plan/<plan_id>/deny', methods=['POST'])
def api_orchestration_plan_deny(plan_id):
    """Deny and cancel a pending plan"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        result = pipeline.deny_plan(plan_id)

        emit_event("plan_cancelled", {"plan_id": plan_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/plan/<plan_id>', methods=['GET'])
def api_orchestration_plan(plan_id):
    """Get plan details"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        plan = pipeline.get_plan(plan_id)

        if not plan:
            return jsonify({"error": "Plan not found"}), 404

        return jsonify(plan)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/plans/pending', methods=['GET'])
def api_orchestration_pending():
    """Get all pending plans"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        plans = pipeline.get_pending_plans()

        return jsonify({"plans": plans})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/status', methods=['GET'])
def api_orchestration_pipeline_status():
    """Get orchestration pipeline status"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        status = pipeline.get_status()

        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/orchestration/test', methods=['POST'])
def api_orchestration_test():
    """Test the orchestration pipeline"""
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        result = pipeline.test()

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Licensing & Tier API ────────────────────────────────────────────────────

@app.route('/license/status', methods=['GET'])
def api_license_status():
    """Get current license status"""
    try:
        status = license_manager.get_status()
        return jsonify(status)
    except Exception as e:
        logger.error(f"License status check failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/license/activate', methods=['POST'])
def api_license_activate():
    """Activate a pro license"""
    try:
        data = request.get_json()
        key = data.get('key', '').strip()

        if not key:
            return jsonify({"success": False, "message": "License key required"}), 400

        result = license_manager.activate(key)
        status_code = 200 if result['success'] else 400

        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"License activation failed: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/license/deactivate', methods=['POST'])
def api_license_deactivate():
    """Deactivate pro license"""
    try:
        result = license_manager.deactivate()
        return jsonify(result)
    except Exception as e:
        logger.error(f"License deactivation failed: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/license/check/<feature_name>', methods=['GET'])
def api_license_check(feature_name):
    """Check if a feature is allowed"""
    try:
        result = license_manager.check_feature(feature_name)
        return jsonify(result)
    except Exception as e:
        logger.error(f"License check failed: {e}")
        return jsonify({"allowed": False, "error": str(e)}), 500


# ─── Earn Jobs API ───────────────────────────────────────────────────────────

@app.route('/earn/jobs')
def api_earn_jobs():
    """Multi-source earn jobs: bounty programs + remote jobs."""
    import threading

    results = {"bounty": [], "remoteok": [], "error": None}

    def _fetch_bounty():
        try:
            from workers.earn.sources.bounty_targets import scan
            results["bounty"] = scan(limit=15)
        except Exception as exc:
            logger.debug("bounty_targets scan failed: %s", exc)

    def _fetch_remoteok():
        try:
            from workers.earn.sources.remoteok_scanner import scan
            results["remoteok"] = scan(limit=15)
        except Exception as exc:
            logger.debug("remoteok scan failed: %s", exc)

    t1 = threading.Thread(target=_fetch_bounty, daemon=True)
    t2 = threading.Thread(target=_fetch_remoteok, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=12); t2.join(timeout=12)

    # Scanners already return normalized dicts — combine directly
    jobs = results["bounty"] + results["remoteok"]

    return jsonify({"status": "ok", "jobs": jobs,
                    "counts": {"bounty": len(results["bounty"]), "remoteok": len(results["remoteok"])},
                    "error": None})


# ─── Market Summary API ───────────────────────────────────────────────────────

@app.route('/market/summary')
def api_market_summary():
    """Market summary — real crypto + equity prices."""
    try:
        btc = get_crypto_price("bitcoin")
        eth = get_crypto_price("ethereum")
        spy = get_stock_price("SPY")
        qqq = get_stock_price("QQQ")
        return jsonify({
            "status": "ok",
            "dry_run": False,
            "quotes": {
                "BTC": {"price": btc.get("price"), "change_24h": btc.get("change_24h"), "symbol": "BTC"},
                "ETH": {"price": eth.get("price"), "change_24h": eth.get("change_24h"), "symbol": "ETH"},
                "SPY": {"price": spy.get("price"), "change_pct": spy.get("change_pct"), "symbol": "SPY"},
                "QQQ": {"price": qqq.get("price"), "change_pct": qqq.get("change_pct"), "symbol": "QQQ"},
            },
        })
    except Exception as e:
        logger.error("market/summary error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/market/news/<ticker>')
def api_market_news(ticker):
    """News headlines for a ticker (uses NPR RSS — no API key needed)."""
    try:
        headlines = get_news_headlines(5)
        return jsonify({"status": "ok", "news": headlines, "ticker": ticker})
    except Exception as e:
        return jsonify({"status": "ok", "news": [], "ticker": ticker, "error": str(e)})


# ─── Capability List API ──────────────────────────────────────────────────────

@app.route('/capability/list')
def api_capability_list():
    """List all registered capabilities / tools."""
    try:
        from tools.registry import list_tools
        tools = list_tools()
        return jsonify({"status": "ok", "capabilities": tools, "count": len(tools)})
    except Exception as e:
        return jsonify({"status": "ok", "capabilities": [], "count": 0, "error": str(e)})


# ─── Chat Routing API ─────────────────────────────────────────────────────────

def _chat_quick_response(message: str) -> str:
    """Generate a quick response via Ollama, falling back to Claude API, then canned text."""
    try:
        import httpx
        ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        ollama_model = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                f"{ollama_host}/api/generate",
                json={"model": ollama_model, "prompt": message, "system": SENTINEL_SYSTEM_PROMPT, "stream": False},
            )
            if resp.status_code == 200:
                text = resp.json().get('response', '').strip()
                if text:
                    return text
    except Exception:
        pass

    try:
        import httpx
        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if api_key:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 256,
                          "messages": [{"role": "user", "content": message}]},
                )
                if resp.status_code == 200:
                    content = resp.json().get('content', [])
                    if content:
                        text = content[0].get('text', '').strip()
                        if text:
                            return text
    except Exception:
        pass

    return ""


_WORKER_RESPONSES = {
    "forge": "I'll help you with that code task. Opening the Forge...",
    "earn": "Searching for bounties and opportunities for you...",
    "market": "Fetching current market and price data for you...",
    "home": "Sending command to your home automation system...",
    "finance": "Loading your financial summary...",
    "general": "I'm here to help! How can I assist you today?",
}

_CONVERSATIONAL_CANNED = [
    ("hi", "Hi there! How can I help you today?"),
    ("hello", "Hello! What can I do for you?"),
    ("hey", "Hey! What's on your mind?"),
    ("how are you", "I'm running great and ready to help! What do you need?"),
    ("what can you do", "I can help you write code, find bug bounties, check market prices, control smart home devices, and much more. Just ask!"),
    ("what time", "I don't have direct clock access, but your system clock is right. Can I help with something else?"),
    ("thank", "You're welcome! Let me know if you need anything else."),
    ("bye", "Goodbye! Come back anytime you need help."),
    ("2 plus 2", "2 + 2 = 4"),
    ("2+2", "2 + 2 = 4"),
]


def _canned_response(message: str) -> str:
    lower = message.lower()
    for kw, reply in _CONVERSATIONAL_CANNED:
        if kw in lower:
            return reply
    return "I'm here and ready to help! What would you like to do?"


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """Route a chat message to the correct worker and return a response string.

    Accepts: { "message": "..." }
    Returns: { "worker": "...", "response": "...", "intent": {...} }
    """
    try:
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message required"}), 400

        # Enrich message with relevant memory context
        if memory_v2 is not None:
            try:
                mem_context = memory_v2.get_context_for_prompt(message, max_tokens=1500)
                if mem_context:
                    # Store it for downstream use; also save this user msg to memory
                    memory_v2.remember(message, source="user", topic=message[:80])
            except Exception as _mem_err:
                logger.debug("Memory context lookup failed: %s", _mem_err)

        from workers.orchestration.task_decomposer import get_decomposer, is_conversational_input

        lower = message.lower()

        # ── Purchase intent — find product, stage approval ───────────────────────
        _buy_kw = ['buy ', 'purchase ', 'order me ', 'i want to buy', 'i want to order',
                   'add to cart', 'get me a ', 'pick up a ', 'grab me a ']
        if any(kw in lower for kw in _buy_kw):
            try:
                import asyncio as _asyncio
                from workers.payments.purchase_executor import PurchaseExecutor
                staged = _asyncio.run(PurchaseExecutor().find_and_stage(message))
                if staged.get("requires_approval"):
                    return jsonify({"status": "ok", "worker": "sentinel_web",
                                    "response": staged["message"], "purchase_approval": staged, "routed": True})
            except Exception as _buy_err:
                logger.debug("Purchase staging failed: %s", _buy_err)

        # ── Web/commerce queries — route to SentinelWeb ─────────────────────────
        _web_kw = ['price of', 'how much is', 'how much does', 'compare prices', 'best deal',
                   'cheapest', 'in stock', 'available at', 'check stock', 'find me ',
                   'search for', 'look up', 'is there a deal', 'on amazon', 'on walmart',
                   'on best buy', 'on target', 'on ebay', 'book a flight', 'book a hotel',
                   'reserve a ', 'book me a']
        if any(kw in lower for kw in _web_kw):
            try:
                import asyncio as _asyncio
                from workers.web.sentinel_web_client import query_web, is_available
                if _asyncio.run(is_available()):
                    web_result = _asyncio.run(query_web(message))
                    web_ans = web_result.get("answer") or web_result.get("result")
                    if web_ans and not web_result.get("error"):
                        src = web_result.get("source_url", "")
                        response = web_ans + (f"\n\nSource: {src}" if src else "")
                        return jsonify({"status": "ok", "worker": "sentinel_web",
                                        "response": response, "routed": True,
                                        "source_url": src, "confidence": web_result.get("confidence")})
                else:
                    return jsonify({"status": "ok", "worker": "general",
                                    "response": "SentinelWeb is offline. Start it with: "
                                                "cd C:\\Users\\pgg12\\Desktop\\SentinelWeb && venv\\Scripts\\python main.py",
                                    "routed": True})
            except Exception as _web_err:
                logger.debug("SentinelWeb routing failed: %s", _web_err)

        # ── Identity questions — hardcoded, never goes to Ollama ────────────────
        _identity_kw = [
            'what is your name', "what's your name", 'who are you',
            'your name', 'what are you', 'who made you',
            'who created you', 'what model', 'are you gpt', 'are you claude',
            'are you qwen', 'are you llama', 'are you ollama'
        ]
        if any(kw in lower for kw in _identity_kw):
            if any(w in lower for w in ['made', 'created', 'built', 'who']):
                _id_resp = "I was created by Sentinel Prime Inc. — a privacy-first AI company building the future of personal AI."
            elif any(w in lower for w in ['model', 'gpt', 'claude', 'qwen', 'llama', 'ollama']):
                _id_resp = "I'm Sentinel. I don't disclose the underlying models I use."
            elif any(w in lower for w in ['name', 'who are you', 'what are you']):
                _id_resp = "I'm Sentinel, your personal AI assistant created by Sentinel Prime Inc."
            else:
                _id_resp = "I'm Sentinel, an advanced AI assistant by Sentinel Prime Inc. I can help you with coding, finding work, managing your home, trading, and much more."
            return jsonify({"status": "ok", "worker": "general", "response": _id_resp, "routed": True})

        # ── Memory save/recall — "remember that X" / "what is my X" ─────────────
        import re as _re_mem
        _remember_match = _re_mem.search(r'(?:remember|note|save|keep in mind|store)\s+that\s+(.+)', lower)
        if _remember_match:
            fact = message[_remember_match.start(1):]
            try:
                get_memory().remember("user_facts", fact, {"source": "chat"})
            except Exception:
                pass
            return jsonify({"status": "ok", "worker": "memory",
                            "response": f"Got it! I've saved: \"{fact.strip()}\"",
                            "routed": True})

        _recall_kw = ['what is my ', 'what are my ', 'tell me my ', 'remind me of my ',
                      "what's my ", 'do you remember ', 'what did i tell you']
        if any(kw in lower for kw in _recall_kw):
            try:
                facts = get_memory().recall("user_facts", lower, limit=5)
                if facts:
                    snippets = "\n".join(f"• {f.get('content', f)}" for f in facts[:5])
                    return jsonify({"status": "ok", "worker": "memory",
                                    "response": f"From your memory:\n{snippets}", "routed": True})
            except Exception:
                pass

        # ── Real-time data routing — runs before Ollama ───────────────────────
        if any(w in lower for w in ['weather', 'temperature', 'forecast', 'raining', 'sunny', 'cold outside', 'hot outside', 'how cold', 'how hot']):
            # Extract city name from "weather in <city>" pattern
            import re as _re
            _city_match = _re.search(r'(?:weather|forecast|temperature)\s+(?:in|for|at)\s+([A-Za-z\s]+?)(?:\?|$|,)', lower)
            _lat, _lon, _city = 37.3382, -121.8863, "San Jose"
            if _city_match:
                _queried_city = _city_match.group(1).strip()
                _glat, _glon, _gname = geocode_city(_queried_city)
                if _glat:
                    _lat, _lon, _city = _glat, _glon, _gname
            wx = get_weather_data(_lat, _lon, _city)
            if 'error' not in wx:
                response = (f"Current weather in {_city}: {wx['temp']}°F (feels like {wx['feels_like']}°F), "
                            f"{wx['condition']}. Wind {wx['wind']} mph, humidity {wx['humidity']}%. "
                            f"Today: high {wx['today_high']}°F / low {wx['today_low']}°F, {wx['rain_chance']}% chance of rain. "
                            f"Tomorrow: {wx['tomorrow_high']}°F / {wx['tomorrow_low']}°F.")
            else:
                response = "Could not fetch weather data right now."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['bitcoin', 'btc price', 'bitcoin price']):
            btc = get_crypto_price("bitcoin")
            if 'error' not in btc:
                direction = "▲" if btc['change_24h'] > 0 else "▼"
                response = f"Bitcoin: ${btc['price']:,.2f} {direction} {abs(btc['change_24h'])}% in the last 24h."
            else:
                response = "Could not fetch Bitcoin price right now."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['ethereum', 'eth price', 'ethereum price']):
            eth = get_crypto_price("ethereum")
            if 'error' not in eth:
                direction = "▲" if eth['change_24h'] > 0 else "▼"
                response = f"Ethereum: ${eth['price']:,.2f} {direction} {abs(eth['change_24h'])}% in the last 24h."
            else:
                response = "Could not fetch Ethereum price right now."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['stock price', 'spy', 'qqq', 'nasdaq', 's&p', 'market today']):
            spy_q = get_stock_price("SPY")
            qqq_q = get_stock_price("QQQ")
            if 'error' not in spy_q:
                response = (f"Markets: SPY ${spy_q['price']} ({'+' if spy_q['change_pct'] > 0 else ''}{spy_q['change_pct']}%), "
                            f"QQQ ${qqq_q['price']} ({'+' if qqq_q['change_pct'] > 0 else ''}{qqq_q['change_pct']}%)")
            else:
                response = "Could not fetch market data right now."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['news', 'headlines', "what's happening", 'latest news']):
            headlines = get_news_headlines(5)
            if headlines:
                response = "Latest headlines:\n" + "\n".join([f"• {h['title']}" for h in headlines])
            else:
                response = "Could not fetch news right now."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['what time', 'current time', "what's the time"]):
            try:
                import pytz
                from datetime import datetime as _dt
                tz = pytz.timezone('America/Los_Angeles')
                now = _dt.now(tz)
                response = f"It's {now.strftime('%I:%M %p')} Pacific Time, {now.strftime('%A, %B %d, %Y')}."
            except Exception:
                from datetime import datetime as _dt
                now = _dt.now()
                response = f"It's {now.strftime('%I:%M %p')} local time."
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        # ── Project planner — complex multi-file builds ───────────────────────────
        # "build me X", "create a full X", "make me a X", "develop a X",
        # "i want a X" — only when the request implies multiple components.
        _project_kw = ['build me ', 'create a full ', 'make me a ', 'develop a ',
                       'i want a ', 'create a complete ']
        _is_complex_build = (
            any(kw in lower for kw in _project_kw)
            and len(message.split()) > 6  # at least 6 words (not "build me a script")
        )
        if _is_complex_build:
            try:
                from workers.consultation.project_planner import get_project_planner
                planner = get_project_planner()
                plan = planner.plan_project(message)
                plan_dict = {
                    "id": plan.id,
                    "intent": plan.intent,
                    "stack": plan.stack,
                    "files": plan.files,
                    "tasks": [{"id": t.id, "description": t.description,
                                "depends_on": t.depends_on, "status": t.status}
                               for t in plan.tasks],
                    "pitfalls": plan.pitfalls,
                }
                resp_text = (
                    f"📋 Project Plan\n\nStack: {', '.join(plan.stack)}\n"
                    f"Files: {', '.join(plan.files[:5])}\n"
                    f"Tasks ({len(plan.tasks)}):\n"
                    + "\n".join(f"  {t.id}. {t.description}" for t in plan.tasks[:5])
                    + (f"\n  ...and {len(plan.tasks)-5} more" if len(plan.tasks) > 5 else "")
                    + "\n\nReply APPROVE to start building, or DENY to cancel."
                )
                return jsonify({
                    "status": "ok", "worker": "consultation",
                    "response": resp_text,
                    "plan": plan_dict, "plan_id": plan.id,
                    "awaiting_approval": True,
                    "routed": True,
                })
            except Exception as _plan_err:
                logger.debug("Project planner failed (%s) — falling through", _plan_err)

        # ── Architecture/guidance consultation ───────────────────────────────────
        _guidance_kw = ['what architecture', 'which architecture', 'how should i build',
                        'what stack', 'which framework', 'best approach for',
                        'design a system', 'design the', 'how to architect']
        if any(kw in lower for kw in _guidance_kw):
            try:
                from workers.consultation.consultant import get_consultant
                consultant = get_consultant()
                result = consultant.consult_for_guidance(message)
                src_label = {"chatgpt": "ChatGPT", "claude": "Claude",
                             "ollama_fallback": "Ollama"}.get(result.source, result.source)
                return jsonify({
                    "status": "ok", "worker": "consultation",
                    "response": f"[Source: {src_label}]\n\n{result.answer}",
                    "consultation_source": result.source,
                    "routed": True,
                })
            except Exception as _cons_err:
                logger.debug("Consultation guidance failed (%s) — falling through", _cons_err)

        # Keyword-based pre-routing runs FIRST — overrides conversational classifier
        # for specific high-confidence patterns. Order: forge > earn > market > home.
        _pre_worker = None

        _forge_kw = ('write a', 'write me', 'build a', 'build me', 'create a', 'create me',
                     'implement', 'debug', 'fix the', 'fix my', 'refactor',
                     'python function', 'python script', 'javascript', 'bash script',
                     'new function', 'new class', 'new module', 'new worker', 'def ',
                     'import ', 'code to', 'script to', 'program to', 'snippet')
        if any(kw in lower for kw in _forge_kw):
            _pre_worker = "forge"

        _earn_kw = ('bounty', 'bug bounty', 'bounties', 'freelance', 'remote job',
                    'find jobs', 'find work', 'hackerone', 'bugcrowd', 'upwork',
                    'earn money', 'earn online', 'paid task')
        if any(kw in lower for kw in _earn_kw):
            _pre_worker = "earn"

        _market_kw = ('bitcoin price', 'eth price', 'crypto price', 'stock price',
                      'btc price', 'bitcoin', 'ethereum price', 'market cap',
                      'market data', 'trading view', 'chart for')
        if any(kw in lower for kw in _market_kw) and _pre_worker != "forge":
            _pre_worker = "market"

        _home_kw = ('turn on', 'turn off', 'switch on', 'switch off',
                    'lights', 'thermostat', 'home automation', 'smart home',
                    'home assistant', 'lock the', 'unlock the', 'dim the',
                    'fan on', 'fan off', 'air conditioning', 'temperature to')
        if any(kw in lower for kw in _home_kw) and _pre_worker is None:
            _pre_worker = "home"

        if _pre_worker:
            response_text = _WORKER_RESPONSES.get(_pre_worker, f"Routing to {_pre_worker} worker...")
            return jsonify({
                "status": "ok",
                "worker": _pre_worker,
                "response": response_text,
                "intent": {"intent": _pre_worker},
                "routed": True,
            })

        # Conversational inputs (no keyword match) → general worker with AI response
        if is_conversational_input(message):
            response_text = _chat_quick_response(message) or _canned_response(message)
            return jsonify({
                "status": "ok",
                "worker": "general",
                "response": response_text,
                "intent": {"intent": "general"},
                "routed": True,
            })

        decomposer = get_decomposer()
        plan = decomposer.generate_plan(message)
        subtasks = plan.get("subtasks", [])
        first = subtasks[0] if subtasks else {}
        worker_raw = first.get("worker", "ollama_general")

        _worker_map = {
            "forge": "forge",
            "earn": "earn",
            "market": "market",
            "ollama_general": "general",
            "openclaw.web": "general",
            "memory": "general",
            "home_assistant": "home",
            "openclaw.calendar": "general",
            "entertainment.spotify": "general",
            "finance.firefly": "finance",
            "home.camera_worker": "home",
        }
        worker = _worker_map.get(worker_raw, "general")

        if worker == "forge" and is_conversational_input(message):
            worker = "general"

        response_text = _chat_quick_response(message) or _WORKER_RESPONSES.get(worker, f"Routing to {worker} worker...")
        return jsonify({
            "status": "ok",
            "worker": worker,
            "response": response_text,
            "intent": {"intent": first.get("type", "GENERAL").lower()},
            "plan": plan,
            "routed": True,
        })
    except Exception as e:
        logger.exception("api_chat failed")
        return jsonify({"status": "error", "worker": "general", "response": "An error occurred. Please try again.", "error": str(e)}), 500


# ─── Real-Time Data API Routes ────────────────────────────────────────────────

@app.route('/api/realtime/weather')
def api_realtime_weather():
    data = get_weather_data()
    return jsonify({"status": "ok", "data": data, "error": data.get("error")})


@app.route('/api/realtime/crypto/<symbol>')
def api_realtime_crypto(symbol):
    data = get_crypto_price(symbol.lower())
    return jsonify({"status": "ok", "data": data, "error": data.get("error")})


@app.route('/api/realtime/news')
def api_realtime_news():
    limit = int(request.args.get('limit', 5))
    headlines = get_news_headlines(limit)
    return jsonify({"status": "ok", "data": headlines, "error": None})


# ─── Earn Accept API ──────────────────────────────────────────────────────────

@app.route('/earn/accept', methods=['POST'])
def api_earn_accept():
    """Accept an earn job and start Aider bounty analysis in background."""
    try:
        import json as _json
        job_data = request.get_json() or {}
        job_title = job_data.get('title', 'Unknown')
        job_url = job_data.get('url', '')
        job_source = job_data.get('source', '')
        job_scope = job_data.get('scope', [])
        job_reward = job_data.get('reward', '')

        # Save to memory vault
        try:
            accepted_dir = Path(__file__).parent / "memory" / "vault" / "earn_jobs" / "accepted"
            accepted_dir.mkdir(parents=True, exist_ok=True)
            safe_title = "".join(c for c in job_title if c.isalnum() or c in ' -_')[:50]
            filepath = accepted_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}.json"
            filepath.write_text(_json.dumps({**job_data, "accepted_at": datetime.now().isoformat()}, indent=2), encoding='utf-8')
        except Exception as _save_err:
            logger.warning("earn/accept: could not save job file: %s", _save_err)

        # Start Aider analysis in background
        log(f'Earn job accepted: {job_title}', 'info', 'earn')

        def analyze():
            try:
                from workers.aider_engine import AiderEngine
                engine = AiderEngine(socketio)
                engine.analyze_bounty(job_title, job_url, job_scope)
            except Exception as exc:
                log(f'Bounty analysis failed: {exc}', 'error', 'earn')

        t = threading.Thread(target=analyze, daemon=True)
        t.start()

        task_id = f"earn_{int(datetime.now().timestamp())}"
        emit_event("orb_state", {"state": "thinking"})

        return jsonify({
            "status": "accepted",
            "message": f"Accepted {job_title}. Sentinel is analyzing the target. Watch the Log tab.",
            "job_id": task_id,
        })
    except Exception as e:
        logger.exception("earn_accept failed")
        log(str(e), 'error', 'earn')
        return jsonify({"status": "error", "error": str(e)}), 200


# ─── SentinelWeb Proxy API ───────────────────────────────────────────────────

@app.route('/web/status', methods=['GET'])
def api_web_status():
    try:
        import asyncio as _aio
        from workers.web.sentinel_web_client import get_health
        return jsonify({"status": "ok", **_aio.run(get_health())})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/web/query', methods=['POST'])
def api_web_query():
    """Proxy a natural language query to SentinelWeb."""
    try:
        import asyncio as _aio
        from workers.web.sentinel_web_client import query_web
        data = request.get_json() or {}
        query = data.get('query', '').strip()
        if not query:
            return jsonify({"status": "error", "error": "query required"}), 200
        result = _aio.run(query_web(query, url=data.get('url'), site_name=data.get('site_name')))
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/web/compare', methods=['POST'])
def api_web_compare():
    """Proxy a price comparison to SentinelWeb."""
    try:
        import asyncio as _aio
        from workers.web.sentinel_web_client import compare_prices
        data = request.get_json() or {}
        result = _aio.run(compare_prices(data.get('query', ''), data.get('sites')))
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/web/credentials/save', methods=['POST'])
def api_web_creds_save():
    try:
        import asyncio as _aio
        from workers.web.sentinel_web_client import save_site_credentials
        data = request.get_json() or {}
        result = _aio.run(save_site_credentials(data.get('site', ''), data.get('username', ''), data.get('password', '')))
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/web/credentials/list', methods=['GET'])
def api_web_creds_list():
    try:
        import asyncio as _aio
        from workers.web.sentinel_web_client import list_saved_sites
        sites = _aio.run(list_saved_sites())
        return jsonify({"status": "ok", "sites": sites})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/web/buy/find', methods=['POST'])
def api_web_buy_find():
    """Find a product's best price and stage an approval for purchase."""
    try:
        import asyncio as _aio
        from workers.payments.purchase_executor import PurchaseExecutor
        data = request.get_json() or {}
        query = data.get('query', '').strip()
        if not query:
            return jsonify({"status": "error", "error": "query required"}), 200
        staged = _aio.run(PurchaseExecutor().find_and_stage(query))
        return jsonify({"status": "ok", **staged})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


# ─── Payment Vault API ────────────────────────────────────────────────────────

_payment_mgr = None


def get_payment_mgr():
    global _payment_mgr
    if _payment_mgr is None:
        from workers.payments.payment_manager import PaymentManager
        _payment_mgr = PaymentManager()
    return _payment_mgr


@app.route('/payments/methods', methods=['GET'])
def api_payment_methods():
    try:
        return jsonify({"status": "ok", "methods": get_payment_mgr().get_payment_methods()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/methods/add', methods=['POST'])
def api_payment_add():
    try:
        data = request.get_json() or {}
        result = get_payment_mgr().add_payment_method(
            data.get('type', ''), data.get('nickname', ''), data.get('details', {}))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/methods/<method_id>', methods=['DELETE'])
def api_payment_delete(method_id):
    try:
        return jsonify(get_payment_mgr().remove_payment_method(method_id))
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/methods/<method_id>/default', methods=['POST'])
def api_payment_set_default(method_id):
    try:
        return jsonify(get_payment_mgr().set_default_method(method_id))
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/limits', methods=['GET', 'POST'])
def api_payment_limits():
    try:
        if request.method == 'GET':
            return jsonify({"status": "ok", "limits": get_payment_mgr().get_limits()})
        data = request.get_json() or {}
        result = get_payment_mgr().set_spending_limit(
            data.get('period', 'per_transaction'),
            float(data.get('amount', 500)),
            data.get('category', 'all'))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/execute', methods=['POST'])
def api_payment_execute():
    """Execute an approved purchase via SentinelWeb."""
    try:
        import asyncio as _aio
        from workers.payments.purchase_executor import PurchaseExecutor
        data = request.get_json() or {}
        result = _aio.run(PurchaseExecutor().execute_purchase(data))
        return jsonify(result)
    except Exception as e:
        logger.error("Payment execution error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/history', methods=['GET'])
def api_payment_history():
    try:
        limit = int(request.args.get('limit', 50))
        return jsonify({"status": "ok", "transactions": get_payment_mgr().get_transaction_history(limit)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/payments/schemas', methods=['GET'])
def api_payment_schemas():
    try:
        from workers.payments.payment_manager import PAYMENT_METHOD_SCHEMAS
        return jsonify({"status": "ok", "schemas": PAYMENT_METHOD_SCHEMAS})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


# ─── Guardian Security Console API ───────────────────────────────────────────

_guardian_brain = None


def get_guardian_brain():
    global _guardian_brain
    if _guardian_brain is None:
        from workers.guardian.guardian_brain import GuardianBrain
        _guardian_brain = GuardianBrain(socketio=socketio)
    return _guardian_brain


@app.route('/guardian/status', methods=['GET'])
def api_guardian_status():
    try:
        return jsonify({"status": "ok", **get_guardian_brain().get_status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/chat', methods=['POST'])
def api_guardian_chat():
    try:
        data = request.get_json() or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({"status": "error", "error": "No message provided"}), 200
        log(f'Guardian query: {message[:100]}', 'info', 'guardian')
        result = get_guardian_brain().chat(message)
        log(f'Guardian response: {str(result.get("response",""))[:100]}', 'info', 'guardian')
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error("Guardian chat error: %s", e, exc_info=True)
        log(str(e), 'error', 'guardian')
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/authorize', methods=['POST'])
def api_guardian_authorize():
    try:
        data = request.get_json() or {}
        target = data.get('target', '').strip()
        if not target:
            return jsonify({"status": "error", "error": "target required"}), 200
        result = get_guardian_brain().confirm_authorization(target)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/mode', methods=['POST'])
def api_guardian_mode():
    try:
        data = request.get_json() or {}
        result = get_guardian_brain().set_mode(data.get('mode', 'defend'))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/clear', methods=['POST'])
def api_guardian_clear():
    try:
        return jsonify(get_guardian_brain().clear_history())
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/tool/run', methods=['POST'])
def api_guardian_tool_run():
    try:
        data = request.get_json() or {}
        tool = data.get('tool', '').strip()
        args = data.get('args', '').strip()
        target = data.get('target', '').strip()
        if not tool:
            return jsonify({"status": "error", "error": "tool required"}), 200
        result = get_guardian_brain().run_tool(tool, args, target)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/audit/code', methods=['POST'])
def api_guardian_audit_code():
    try:
        data = request.get_json() or {}
        content = data.get('code') or data.get('path', '')
        if not content:
            return jsonify({"status": "error", "error": "Provide code text or file path"}), 200
        result = get_guardian_brain().audit_code(content)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/audit/repo', methods=['POST'])
def api_guardian_audit_repo():
    try:
        data = request.get_json() or {}
        repo_path = data.get('path', '').strip()
        if not repo_path or not os.path.isdir(repo_path):
            return jsonify({"status": "error", "error": "Invalid or missing repository path"}), 200
        result = get_guardian_brain().audit_repository(repo_path)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/cves', methods=['GET'])
def api_guardian_cves():
    try:
        product = request.args.get('product')
        severity = request.args.get('severity', 'CRITICAL')
        limit = int(request.args.get('limit', 10))
        cves = get_guardian_brain().get_cves(product=product, severity=severity, limit=limit)
        return jsonify({"status": "ok", "cves": cves, "count": len(cves)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/guardian/cves/<cve_id>', methods=['GET'])
def api_guardian_cve_detail(cve_id):
    try:
        result = get_guardian_brain().analyze_cve(cve_id)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


# ─── Consultation Routes ──────────────────────────────────────────────────────

@app.route('/consultation/project', methods=['POST'])
def consultation_project():
    """Create a project plan via Claude + ChatGPT + Ollama merge."""
    try:
        from workers.consultation.project_planner import get_project_planner
        data = request.get_json() or {}
        intent = data.get("intent", "").strip()
        if not intent:
            return jsonify({"status": "error", "error": "intent required"}), 400
        planner = get_project_planner()
        plan = planner.plan_project(intent)
        plan_dict = {
            "id": plan.id,
            "intent": plan.intent,
            "stack": plan.stack,
            "files": plan.files,
            "tasks": [{"id": t.id, "description": t.description,
                        "depends_on": t.depends_on, "status": t.status}
                       for t in plan.tasks],
            "pitfalls": plan.pitfalls,
            "created_at": plan.created_at,
        }
        return jsonify({"plan": plan_dict, "plan_id": plan.id,
                         "status": "awaiting_approval"})
    except Exception as exc:
        logger.exception("consultation_project error")
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route('/consultation/project/<plan_id>/approve', methods=['POST'])
def consultation_approve(plan_id: str):
    """Start executing the plan in a background thread."""
    try:
        from workers.consultation.project_planner import get_plan, get_project_planner, _plan_status
        plan = get_plan(plan_id)
        if not plan:
            return jsonify({"status": "error", "error": "plan not found"}), 404
        _plan_status[plan_id]["status"] = "executing"

        def _run():
            try:
                get_project_planner().execute_plan(plan)
            except Exception as exc:
                logger.exception("Plan execution error")
                _plan_status[plan_id]["status"] = "failed"

        import threading
        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"status": "executing", "plan_id": plan_id})
    except Exception as exc:
        logger.exception("consultation_approve error")
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route('/consultation/project/<plan_id>/status', methods=['GET'])
def consultation_status(plan_id: str):
    """Return current execution status of a plan."""
    try:
        from workers.consultation.project_planner import _plan_status
        st = _plan_status.get(plan_id, {"status": "unknown"})
        return jsonify(st)
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route('/consultation/project/<plan_id>/deny', methods=['POST'])
def consultation_deny(plan_id: str):
    """Cancel a plan."""
    try:
        from workers.consultation.project_planner import _plans, _plan_status
        _plans.pop(plan_id, None)
        _plan_status.pop(plan_id, None)
        return jsonify({"status": "denied", "plan_id": plan_id})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route('/consultation/ask', methods=['POST'])
def consultation_ask():
    """One-shot consultation question."""
    try:
        from workers.consultation.consultant import get_consultant
        data = request.get_json() or {}
        question = data.get("question", "").strip()
        q_type = data.get("type", "guidance")
        if not question:
            return jsonify({"status": "error", "error": "question required"}), 400
        consultant = get_consultant()
        if q_type == "code":
            result = consultant.consult_for_code(
                problem=question,
                code=data.get("code", ""),
                error=data.get("error", ""),
            )
        else:
            result = consultant.consult_for_guidance(question)
        return jsonify({
            "answer": result.answer,
            "source": result.source,
            "success": result.success,
        })
    except Exception as exc:
        logger.exception("consultation_ask error")
        return jsonify({"status": "error", "error": str(exc)}), 500


# ─── Backend Launcher ─────────────────────────────────────────────────────────

def run_flask_app():
    """Run Flask app in background thread."""
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5001"))
    if host not in ("127.0.0.1", "localhost"):
        logger.warning(f"Flask binding to {host} — ensure firewall is configured!")
    if SOCKETIO_AVAILABLE and socketio is not None:
        # allow_unsafe_werkzeug: we run the dev server in a daemon thread on localhost.
        try:
            socketio.run(app, host=host, port=port, debug=False,
                         use_reloader=False, allow_unsafe_werkzeug=True)
            return
        except TypeError:
            # older flask-socketio without allow_unsafe_werkzeug kwarg
            socketio.run(app, host=host, port=port, debug=False, use_reloader=False)
            return
        except Exception as exc:
            logger.warning("socketio.run failed (%s) — falling back to app.run", exc)
    app.run(host=host, port=port, debug=False, use_reloader=False)


def start_backend():
    """Start the SentinelAI backend."""
    logger.info("Starting SentinelAI backend...")

    # Register Scalp routes (deferred to avoid circular import at module level)
    if _register_scalp_routes_pending:
        try:
            from workers.scalp.scalp_worker import register_routes as _reg
            _reg(app)
            logger.info("Scalp worker routes registered")
        except Exception as e:
            logger.warning("Scalp route registration failed: %s", e)

    # Initialize database
    db.init_db()

    # Register built-in capability tools
    try:
        register_builtin_tools()
        logger.info("Built-in capability tools registered")
    except Exception as e:
        logger.warning(f"Capability registry initialization failed: {e}")
    
    # Initialize learning memory system
    try:
        lm.initialize_learning_system()
        logger.info("Learning memory system initialized")
    except Exception as e:
        logger.warning(f"Learning memory initialization failed: {e}")
    
    # Initialize queue system
    try:
        qm.initialize_queue()
        logger.info("Task queue initialized")
    except Exception as e:
        logger.warning(f"Queue initialization failed: {e}")

    # Initialize orchestration runtime
    try:
        orchestrator = orch.initialize_orchestration()
        recovered = orchestrator.recover_workflows()
        logger.info(f"Orchestration runtime initialized (recovered={recovered})")
    except Exception as e:
        logger.warning(f"Orchestration initialization failed: {e}")
    
    # Perform crash recovery
    try:
        wd.recover_from_crash()
        logger.info("Crash recovery completed")
    except Exception as e:
        logger.warning(f"Crash recovery failed: {e}")
    
    # Initialize worker manager
    try:
        max_workers = int(os.getenv("MAX_WORKERS", "3"))
        manager = wm.initialize_workers(max_workers)
        manager.register_handler("orchestration_workflow", orch.get_orchestrator().handle_queue_task)
        manager.register_handler("repair_execute", handle_repair_execute)
        manager.register_handler("forge_build", handle_forge_build)
        manager.create_worker("repair_worker_1", ["repair_execute"])
        manager.create_worker("repair_worker_2", ["repair_execute"])
        manager.create_worker("forge_worker_1", ["forge_build"])
        manager.start_all()
        logger.info(f"Worker manager initialized (max_workers={max_workers})")
    except Exception as e:
        logger.warning(f"Worker manager initialization failed: {e}")
    
    # Initialize watchdog
    try:
        watchdog_interval = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "30"))
        watchdog = wd.initialize_watchdog(watchdog_interval)
        watchdog.start()
        logger.info(f"Watchdog started (interval={watchdog_interval}s)")
    except Exception as e:
        logger.warning(f"Watchdog initialization failed: {e}")
    
    # Initialize health monitor
    try:
        health_interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))
        monitor = hm.initialize_health_monitor(health_interval)
        monitor.start()
        logger.info(f"Health monitor started (interval={health_interval}s)")
    except Exception as e:
        logger.warning(f"Health monitor initialization failed: {e}")

    # Initialize orchestration pipeline (Tracks 17-25)
    try:
        from workers.orchestration.pipeline import get_pipeline
        pipeline = get_pipeline()
        logger.info("Orchestration pipeline initialized (RAG indexing in background)")
    except Exception as e:
        logger.warning(f"Orchestration pipeline initialization failed: {e}")

    # ─── Start New Background Workers (Tracks 8-16) ─────────────────────────────

    # Wake word detector (Track 8)
    try:
        from workers.voice.wake_word import start_detector

        def wake_word_callback(data):
            logger.info(f"Wake word detected: {data}")
            emit_event("wake_word_detected", data)

            # If transcription available, send to chat
            if data.get('transcription'):
                # TODO: Wire to chat endpoint
                pass

        if os.getenv('WAKE_WORD_ENABLED', 'false').lower() == 'true':
            start_detector(callback=wake_word_callback)
            logger.info("Wake word detector started")
        else:
            logger.info("Wake word detector disabled (set WAKE_WORD_ENABLED=true to enable)")
    except Exception as e:
        logger.warning(f"Wake word detector failed to start: {e}")

    # OpenClaw reminders background checker (Track 5)
    try:
        from workers.openclaw.reminders import get_reminders_manager
        get_reminders_manager()  # Auto-starts on first call
        logger.info("OpenClaw reminders background checker started")
    except Exception as e:
        logger.warning(f"Reminders background checker failed to start: {e}")

    # Telegram bridge (Track 9)
    try:
        from workers.messaging.telegram_bridge import start_bridge
        if os.getenv('TELEGRAM_BOT_TOKEN'):
            start_bridge()
            logger.info("Telegram bridge started")
        else:
            logger.info("Telegram bridge disabled (TELEGRAM_BOT_TOKEN not set)")
    except Exception as e:
        logger.warning(f"Telegram bridge failed to start: {e}")

    # Proactive scheduler (Track 11)
    try:
        from workers.proactive.scheduler import start_scheduler
        start_scheduler()
        logger.info("Proactive scheduler started")
    except Exception as e:
        logger.warning(f"Proactive scheduler failed to start: {e}")

    # ─────────────────────────────────────────────────────────────────────────────

    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # Small delay to allow Flask to bind before marking ready
    import time
    time.sleep(0.8)

    backend_state["running"] = True
    backend_state["startup_complete"] = True
    logger.info("Backend started on http://127.0.0.1:5001")

    # Initialize Memory V2 (3-layer hot/warm/cold)
    global memory_v2
    try:
        memory_v2 = get_memory_manager_v2(socketio=socketio)
        logger.info("Memory Manager V2 initialized")
    except Exception as e:
        logger.warning("Memory V2 init failed: %s", e)

    try:
        enqueue_new_repair_opportunities()
        scan_thread = threading.Thread(target=background_scan_loop, daemon=True)
        scan_thread.start()
        logger.info("Background scan loop started")
    except Exception as e:
        logger.warning(f"Background scan loop failed to start: {e}")

    # Real-time approval watcher — emits approval_needed + orb alert when a new
    # pending approval appears (Task 4). Cheap diff loop; no-op without Socket.IO.
    try:
        approval_thread = threading.Thread(target=approval_watch_loop, daemon=True)
        approval_thread.start()
        logger.info("Approval watcher started")
    except Exception as e:
        logger.warning(f"Approval watcher failed to start: {e}")

    # Conversation sync — runs every 60 minutes after initial 5-minute delay
    def _conversation_sync_loop():
        import time as _time
        _time.sleep(300)  # 5 minute startup delay
        while backend_state.get("running", True):
            try:
                from workers.sync.conversation_sync import get_conversation_sync
                sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
                sync.sync_all()
            except Exception as e:
                log(f"Scheduled sync error: {e}", 'warning', 'sync')
            _time.sleep(3600)  # every 60 minutes

    threading.Thread(target=_conversation_sync_loop, daemon=True).start()

    # Browser sessions — auto-login to Claude + ChatGPT in background
    def _start_browser_sessions():
        import time as _time
        _time.sleep(5)  # Let Flask settle first
        try:
            from workers.identity.browser_sessions import BrowserSessions
            global browser_sessions
            browser_sessions = BrowserSessions(identity_manager, socketio)
            browser_sessions.startup_login()
            log(
                f"Claude.ai: {'connected' if browser_sessions.claude_logged_in else 'skipped/failed'}",
                'info' if browser_sessions.claude_logged_in else 'info',
                'identity'
            )
            log(
                f"ChatGPT: {'connected' if browser_sessions.chatgpt_logged_in else 'skipped/failed'}",
                'info' if browser_sessions.chatgpt_logged_in else 'info',
                'identity'
            )
        except ImportError:
            logger.warning("playwright not installed — browser sessions disabled")
        except Exception as e:
            log(f"Browser session startup failed: {e}", 'warning', 'identity')

    threading.Thread(target=_start_browser_sessions, daemon=True).start()


def approval_watch_loop():
    import time
    seen = set()
    while backend_state.get("running"):
        try:
            from openclaw.openclaw import get_openclaw
            pending = get_openclaw().get_pending_approvals()
            ids = {a.get("id") for a in pending}
            for a in pending:
                if a.get("id") not in seen:
                    emit_event("approval_needed", {
                        "approval_id": a.get("id"),
                        "description": a.get("description"),
                        "action_type": a.get("action_type"),
                    })
                    emit_event("orb_state", {"state": "alert"})
            seen = ids
        except Exception:
            pass
        time.sleep(2)


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def main():
    """Main entry point for desktop app."""
    logger.info("=" * 80)
    logger.info("SENTINELAI DESKTOP APPLICATION")
    logger.info("=" * 80)
    
    # Start backend
    start_backend()
    
    # Open dashboard in browser only when NOT spawned by the Electron shell.
    # Electron sets SENTINEL_NO_BROWSER=1 so the orb window is the only UI.
    if not os.getenv('SENTINEL_NO_BROWSER'):
        webbrowser.open('http://localhost:5001')
    
    # When spawned by Electron (SENTINEL_NO_BROWSER=1) there is no interactive
    # desktop session context for pystray, so skip the tray and just keep alive.
    if os.getenv('SENTINEL_NO_BROWSER'):
        logger.info("Running under Electron — tray icon skipped. Backend serving on :5001")
        import time
        while backend_state.get("running", True):
            time.sleep(5)
        return

    # Create and run system tray (standalone / terminal mode)
    logger.info("Creating system tray icon...")
    try:
        icon = create_system_tray()
        logger.info("SentinelAI is now running. Check system tray for controls.")
        icon.run()
    except Exception as e:
        logger.warning("System tray failed (%s) — keeping backend alive without tray", e)
        import time
        while backend_state.get("running", True):
            time.sleep(5)


if __name__ == "__main__":
    main()
