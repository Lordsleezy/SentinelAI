"""
desktop_app.py — SentinelAI Desktop Application
Lightweight desktop shell using Flask + system tray
Launches backend, provides UI, system tray controls
"""
import functools
import hmac
import os
import sys

from core.app_paths import bootstrap_packaged_env

bootstrap_packaged_env()

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

from core.app_paths import (
    ensure_user_data_dirs,
    load_sentinel_env,
    resolve_config_dir,
    resolve_env_path,
)

ensure_user_data_dirs()
load_sentinel_env()

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
from workers.sentinel.model_router import get_model_router
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

# OWNER_MODE: env var takes precedence; falls back to build_info.py baked constant.
try:
    import build_info as _bi
    _baked_owner = getattr(_bi, 'OWNER_MODE', False)
except ImportError:
    _baked_owner = False
OWNER_MODE = os.getenv('SENTINEL_OWNER_MODE', 'false').lower() == 'true' or _baked_owner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress ChromaDB telemetry and fake_useragent noise before any imports trigger them
logging.getLogger('chromadb.telemetry').setLevel(logging.CRITICAL)
logging.getLogger('chromadb').setLevel(logging.WARNING)
logging.getLogger('fake_useragent').setLevel(logging.ERROR)


# ─── Background thread registry (audit H7) ───────────────────────────────────
#
# Every Thread.start() is intercepted so we can (a) keep a list of all
# background threads for /api/debug/threads, and (b) wrap the target with a
# try/except that logs uncaught exceptions instead of letting them die silent.
# This covers all 37+ fire-and-forget daemon threads without editing each site.

_threads: list[threading.Thread] = []
_threads_lock = threading.Lock()


def _guarded_thread_target(target):
    if target is None:
        return None

    @functools.wraps(target)
    def _wrapped(*args, **kwargs):
        try:
            return target(*args, **kwargs)
        except Exception:
            logger.exception(
                "Background thread '%s' raised an uncaught exception",
                threading.current_thread().name,
            )

    return _wrapped


_orig_thread_start = threading.Thread.start


def _patched_thread_start(self):
    # Wrap target once. _sentinel_guarded prevents double-wrapping if a caller
    # restarts a Thread instance (rare, but possible).
    target = getattr(self, "_target", None)
    if target is not None and not getattr(self, "_sentinel_guarded", False):
        try:
            self._target = _guarded_thread_target(target)
            self._sentinel_guarded = True
        except Exception:
            pass  # never block thread start because of registration bookkeeping
    with _threads_lock:
        # Drop dead threads from the registry so it stays bounded.
        _threads[:] = [t for t in _threads if t.is_alive()]
        _threads.append(self)
    return _orig_thread_start(self)


threading.Thread.start = _patched_thread_start


# ─── Shared async event loop (audit H8) ──────────────────────────────────────
#
# `asyncio.run(...)` creates a fresh event loop on every call, blocks the
# caller for its lifetime, and prevents connection pooling. Several Flask
# handlers and background threads in this file used it. They now submit
# coroutines to one persistent loop running in its own thread, via
# `run_async(coro, timeout)`.

_async_loop: "asyncio.AbstractEventLoop | None" = None
_async_loop_lock = threading.Lock()


def _ensure_async_loop() -> "asyncio.AbstractEventLoop":
    global _async_loop
    with _async_loop_lock:
        if _async_loop is not None and _async_loop.is_running():
            return _async_loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_forever()
            finally:
                loop.close()

        threading.Thread(target=_run, name="sentinel-async-loop", daemon=True).start()
        _async_loop = loop
        return loop


def run_async(coro, timeout: float = 60.0):
    """Run an awaitable on the shared loop and block for its result.

    Use this anywhere we are in a sync context but need to call into an
    `async def` function. Replaces ad-hoc `asyncio.run(...)` calls.
    """
    loop = _ensure_async_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)

# Flask app
app = Flask(__name__)
# Lock CORS to Electron renderer (file:// → null origin) and the local server.
ALLOWED_ORIGINS = [
    "http://localhost:5001",
    "http://127.0.0.1:5001",
    "null",
    "file://",
]
CORS(app, origins=ALLOWED_ORIGINS)

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
    socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="threading",
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


_SUPPRESS_PATTERNS = [
    'chromadb.telemetry',
    'ClientStartEvent',
    'ClientCreateCollectionEvent',
    'CollectionAddEvent',
    'fake_useragent',
    'anonymized_telemetry',
    'capture() takes',
]


def log(message: str, level: str = 'info', source: str = 'system') -> None:
    """Emit a log_event to the Log tab via Socket.IO."""
    if any(p in message for p in _SUPPRESS_PATTERNS):
        return
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

SENTINEL_SYSTEM_PROMPT = """You are Sentinel, a polished personal AI assistant created by Sentinel Prime Inc.
- Your name is always Sentinel. Never say you are qwen, llama, mistral, or any other model.
- If asked who made you, say Sentinel Prime Inc.
- Keep replies natural, warm, and concise unless the user asks for detail.
- For greetings, respond with a brief friendly greeting only — no feature lists unless asked.
- Never mention internal diagnostics, workers, routers, logs, memory systems, or setup steps."""


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
            inserted = run_async(run_scan(dry_run=False), timeout=600.0)
            backend_state["last_scan"] = datetime.now().isoformat()
            logger.info(f"Background scan inserted {inserted} new opportunities")
            enqueue_new_repair_opportunities()
        except Exception as e:
            logger.exception(f"Background scan failed: {e}")

        time.sleep(SCAN_INTERVAL_SECONDS)

# ─── Authentication ──────────────────────────────────────────────────────────
#
# SENTINELAI_AUTH_TOKEN must be set in the environment by the Electron main
# process (or the user) before Flask starts. The Electron renderer reads the
# same value and attaches it as `Authorization: Bearer <token>` on every API
# call. There is no fallback default — refusing to start is safer than booting
# with a guessable token.

AUTH_TOKEN = os.getenv("SENTINELAI_AUTH_TOKEN", "")
if not AUTH_TOKEN:
    logger.error(
        "SENTINELAI_AUTH_TOKEN is not set. "
        "Set this env var before starting Sentinel AI. "
        "The Electron main process is expected to generate a token at launch and inject it into the backend."
    )
    raise SystemExit(
        "SENTINELAI_AUTH_TOKEN is not set. "
        "Set this env var before starting Sentinel AI."
    )


def _extract_bearer(raw: str) -> str:
    if not raw:
        return ""
    if raw.startswith("Bearer "):
        return raw[7:]
    return raw


def verify_auth_token(token: str) -> bool:
    """Verify authentication token using constant-time comparison."""
    if not token:
        return False
    candidate = _extract_bearer(token)
    if not candidate:
        return False
    return hmac.compare_digest(candidate, AUTH_TOKEN)


# Routes that are intentionally reachable without a bearer token:
# - HTML shells (the renderer requests them via Electron loadURL, which can't
#   add an Authorization header; the JS inside then calls authed APIs).
# - /api/ping liveness probe used by Electron readiness polling.
# - /socket.io/* upgrade traffic (the socket connection itself authenticates
#   via the auth payload supplied in the client connect call — see frontend).
# - /static/* assets.
PUBLIC_PATHS = {
    "/",
    "/mobile",
    "/api/ping",
}
PUBLIC_PREFIXES = (
    "/static/",
    "/socket.io/",
    "/api/setup/",
    "/api/onboarding/",
    "/api/models/readiness",
    "/api/telemetry/",
    "/api/ai/",
)


@app.before_request
def _global_auth_gate():
    # CORS preflight must succeed before the browser sends the Authorization header.
    if request.method == "OPTIONS":
        return None
    path = request.path or "/"
    if path in PUBLIC_PATHS:
        return None
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return None
    if not verify_auth_token(request.headers.get("Authorization", "")):
        return jsonify({"error": "Unauthorized"}), 401
    return None


def require_auth(fn):
    """Decorator kept for backwards compatibility.

    The global before_request gate already requires a valid token on every
    non-public route, so this is now a no-op wrapper that preserves existing
    call sites and lets individual routes opt in for clarity.
    """
    return fn


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
@require_auth
def api_credentials_save():
    """Save a credential to .env and env immediately, then signal retry.

    Only keys declared by a worker's REQUIREMENTS (plus a small set of
    service-routing knobs) are accepted. Security-sensitive keys are denied.
    """
    from workers.lazy_init import get_lazy_init
    data = request.get_json() or {}
    key = data.get("key", "").strip()
    value = data.get("value", "").strip()
    if not key or not value:
        return jsonify({"status": "error", "error": "key and value required"}), 400
    li = get_lazy_init()
    if not li.is_allowed_key(key):
        logger.warning("Rejected credential save for disallowed key: %s", key)
        return jsonify({"status": "error", "error": f"Key not allowed: {key}"}), 400
    ok = li.save(key, value)
    if ok:
        return jsonify({"status": "saved", "key": key})
    return jsonify({"status": "error", "error": "Failed to write .env"}), 500


@app.route('/api/ping')
def api_ping():
    """Instant liveness probe — used by Electron readiness poll."""
    return jsonify({"ok": True, "running": backend_state.get("running", False)})


@app.route('/api/debug/threads')
@require_auth
def api_debug_threads():
    """Snapshot of every Thread spawned through the patched start hook.

    Audit H7 — used to verify that fire-and-forget daemon threads are
    actually completing instead of dying silently. Auth is enforced by the
    global before_request gate; the decorator is here for clarity.
    """
    with _threads_lock:
        # Drop dead entries opportunistically so the snapshot stays useful.
        _threads[:] = [t for t in _threads if t.is_alive()]
        snapshot = [
            {
                "name": t.name,
                "ident": t.ident,
                "alive": t.is_alive(),
                "daemon": t.daemon,
            }
            for t in _threads
        ]
    return jsonify({"status": "ok", "count": len(snapshot), "threads": snapshot})


# ── Login / Identity Routes ───────────────────────────────────────────────────

@app.route('/api/login/status')
def api_login_status():
    """Return whether credentials are configured and connection status."""
    configured = identity_manager.has_credentials()
    user_name = identity_manager.get_user_name() if configured else None
    creds = identity_manager.load_credentials() or {}

    # Check stealth availability
    stealth_active = False
    try:
        from workers.identity.stealth_browser import StealthBrowser
        stealth_active = StealthBrowser().verify_stealth()
    except Exception:
        pass

    # Check Gmail configuration
    gmail_configured = False
    try:
        from workers.identity.gmail_handler import GmailHandler
        gmail_configured = GmailHandler().is_configured()
    except Exception:
        pass

    # Check ADB availability
    adb_available = False
    try:
        from workers.identity.adb_handler import ADBHandler
        adb_available = ADBHandler().is_available()
    except Exception:
        pass

    # Connected = credentials exist AND session has been validated by browser automation.
    # Do NOT infer Connected from credentials alone — that would be a false positive.
    _claude_session_active  = bool(browser_sessions and getattr(browser_sessions, 'claude_logged_in',  False))
    _chatgpt_session_active = bool(browser_sessions and getattr(browser_sessions, 'chatgpt_logged_in', False))
    _claude_creds_saved     = bool(creds.get("claude_email"))
    _chatgpt_creds_saved    = bool(creds.get("chatgpt_email"))

    return jsonify({
        "configured":        configured,
        "user_name":         user_name,
        # True only when a live, validated browser session exists
        "claude_connected":  _claude_session_active,
        "chatgpt_connected": _chatgpt_session_active,
        # Separate flags so the UI can show "credentials saved, not yet connected"
        "claude_creds_saved":    _claude_creds_saved,
        "chatgpt_creds_saved":   _chatgpt_creds_saved,
        "claude_2fa_method":     creds.get("claude_2fa_method", "none"),
        "chatgpt_2fa_method":    creds.get("chatgpt_2fa_method", "none"),
        "gmail_configured":      gmail_configured,
        "adb_available":         adb_available,
        "stealth_active":        stealth_active,
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
    """Re-test saved credentials."""
    creds = identity_manager.load_credentials() or {}

    gmail_configured = False
    try:
        from workers.identity.gmail_handler import GmailHandler
        gmail_configured = GmailHandler().is_configured()
    except Exception:
        pass

    adb_available = False
    try:
        from workers.identity.adb_handler import ADBHandler
        adb_available = ADBHandler().is_available()
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "user_name": creds.get("user_name", ""),
        "claude_configured": bool(creds.get("claude_email")),
        "chatgpt_configured": bool(creds.get("chatgpt_email")),
        "claude_2fa_method": creds.get("claude_2fa_method", "none"),
        "chatgpt_2fa_method": creds.get("chatgpt_2fa_method", "none"),
        "gmail_configured": gmail_configured,
        "adb_available": adb_available,
    })


@app.route('/api/login/clear', methods=['POST'])
def api_login_clear():
    """Clear all saved credentials."""
    identity_manager.clear_credentials()
    log("Credentials cleared", 'info', 'identity')
    return jsonify({"status": "cleared"})


@app.route('/api/login/connect/claude', methods=['POST'])
def api_login_connect_claude():
    """Trigger Claude.ai browser login."""
    try:
        if not identity_manager.has_credentials():
            return jsonify({
                'status': 'needs_credentials',
                'message': 'No credentials saved. Complete the login setup first.'
            })

        def do_login():
            try:
                sessions = app.config.get('BROWSER_SESSIONS') or browser_sessions
                if sessions and hasattr(sessions, 'login_claude'):
                    result = sessions.login_claude()
                    app.config['CLAUDE_CONNECTED'] = result
                    log(f"Claude login {'successful' if result else 'failed'}", 'success' if result else 'error', 'identity')
                else:
                    log("Claude login: no browser session available", 'warning', 'identity')
            except Exception as e:
                log(f"Claude login error: {e}", 'error', 'identity')

        threading.Thread(target=do_login, daemon=True).start()
        return jsonify({'status': 'connecting', 'message': 'Login attempt started. Check the Log for progress.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/login/connect/chatgpt', methods=['POST'])
def api_login_connect_chatgpt():
    """Trigger ChatGPT browser login."""
    try:
        if not identity_manager.has_credentials():
            return jsonify({
                'status': 'needs_credentials',
                'message': 'No credentials saved. Complete the login setup first.'
            })

        def do_login():
            try:
                sessions = app.config.get('BROWSER_SESSIONS') or browser_sessions
                if sessions and hasattr(sessions, 'login_chatgpt'):
                    result = sessions.login_chatgpt()
                    app.config['CHATGPT_CONNECTED'] = result
                    log(f"ChatGPT login {'successful' if result else 'failed'}", 'success' if result else 'error', 'identity')
                else:
                    log("ChatGPT login: no browser session available", 'warning', 'identity')
            except Exception as e:
                log(f"ChatGPT login error: {e}", 'error', 'identity')

        threading.Thread(target=do_login, daemon=True).start()
        return jsonify({'status': 'connecting', 'message': 'Login attempt started. Check the Log for progress.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Sync Routes ───────────────────────────────────────────────────────────────

@app.route('/sync/status')
def sync_status():
    try:
        from workers.sync.conversation_sync import get_conversation_sync
        sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
        return jsonify(sync.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/memory/sync/diagnostics', methods=['GET'])
def api_memory_sync_diagnostics():
    """Provider sync state: OFFLINE → SYNCED with import counts."""
    try:
        from workers.memory.provider_sync_status import get_provider_sync_status
        creds = identity_manager.load_credentials() or {}
        login = {
            "claude_connected": bool(browser_sessions and getattr(browser_sessions, "claude_logged_in", False)),
            "chatgpt_connected": bool(browser_sessions and getattr(browser_sessions, "chatgpt_logged_in", False)),
            "claude_creds_saved": bool(creds.get("claude_email")),
            "chatgpt_creds_saved": bool(creds.get("chatgpt_email")),
        }
        from workers.sync.conversation_sync import get_conversation_sync
        sync = get_conversation_sync(sessions=browser_sessions, socketio=socketio)
        diag = get_provider_sync_status(login, sync.get_status())
        return jsonify({"status": "ok", **diag})
    except Exception as e:
        logger.exception("memory sync diagnostics failed")
        return jsonify({"status": "error", "error": str(e)}), 200


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


@app.route('/memory/purge/source/<source>', methods=['DELETE'])
def memory_purge_source(source: str):
    """Delete all memories from a specific source. Use 'all' to wipe everything."""
    if memory_v2 is None:
        return jsonify({"error": "Memory V2 not initialized"}), 503
    try:
        if source == 'all':
            count = memory_v2.purge_all()
        else:
            count = memory_v2.purge_by_source(source)
        log(f"Purged {count} memories from source: {source}", 'warning', 'memory')
        return jsonify({"purged": count, "source": source})
    except Exception as e:
        log(f"Purge error: {e}", 'error', 'memory')
        return jsonify({"error": str(e)}), 500


# Only files under a Sentinel-managed directory may be launched via /api/launch.
# This prevents the endpoint from being used to execute arbitrary files on disk.
_LAUNCH_ROOTS = [
    Path(__file__).parent / "workspace",
    Path(__file__).parent / "tools" / "built",
    Path(__file__).parent / "data",
]
_LAUNCH_ALLOWED_EXTS = {".py", ".exe", ".bat", ".cmd", ".html"}


def _is_path_under_root(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


@app.route('/api/launch', methods=['POST'])
@require_auth
def api_launch():
    """Launch a built file (Python script, exe, bat, html) by absolute path.

    The path must resolve to a file under a Sentinel-managed root
    (workspace/, tools/built/, data/) and have an allowed extension.
    """
    try:
        data = request.json or {}
        file_path = (data.get('file', '') or '').strip()

        if not file_path:
            return jsonify({"error": "file required"}), 400

        target = Path(file_path)
        if not target.exists() or not target.is_file():
            return jsonify({"error": f"File not found: {file_path}"}), 404

        ext = target.suffix.lower()
        if ext not in _LAUNCH_ALLOWED_EXTS:
            return jsonify({"error": f"Extension not allowed: {ext}"}), 403

        if not any(_is_path_under_root(target, root) for root in _LAUNCH_ROOTS):
            logger.warning("Rejected launch outside managed roots: %s", file_path)
            return jsonify({"error": "Path not under a Sentinel-managed root"}), 403

        if getattr(sys, "frozen", False):
            python_exe = sys.executable
        else:
            python_exe = str(Path(__file__).parent / "venv" / "Scripts" / "python.exe")
            if not os.path.exists(python_exe):
                python_exe = sys.executable if os.path.exists(sys.executable) else "python"

        if ext == '.py':
            subprocess.Popen(
                [python_exe, str(target)],
                shell=False,
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
            )
        elif ext in ('.exe', '.bat', '.cmd'):
            # shell=False with a list argv prevents shell metacharacter expansion.
            subprocess.Popen([str(target)], shell=False)
        elif ext == '.html':
            webbrowser.open(target.as_uri())
        else:
            if os.name == 'nt':
                os.startfile(str(target))  # noqa: S606 — restricted by allowlist above
            else:
                subprocess.Popen(['xdg-open', str(target)], shell=False)

        log(f"Launched: {target.name}", 'success', 'forge')
        return jsonify({"status": "launched", "file": target.name})
    except Exception as e:
        log(f"Launch error: {e}", 'error', 'forge')
        return jsonify({"error": str(e)}), 500


@app.route('/api/artifact/latest', methods=['GET'])
def api_artifact_latest():
    """Return the most recently registered build artifact."""
    try:
        from workers.artifacts.artifact_registry import get_latest_artifact
        artifact = get_latest_artifact()
        if artifact:
            return jsonify({"status": "ok", "artifact": artifact})
        return jsonify({"status": "none", "artifact": None})
    except Exception as e:
        log(f"[ARTIFACT] Latest error: {e}", 'error', 'forge')
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/artifact/launch', methods=['POST'])
def api_artifact_launch():
    """Launch the most recently registered artifact."""
    try:
        from workers.artifacts.artifact_registry import (
            get_artifact_by_task, get_latest_artifact, launch_artifact
        )
        data = request.get_json() or {}
        task_hint = data.get('task', '').strip()

        artifact = (get_artifact_by_task(task_hint) if task_hint else None) or get_latest_artifact()

        if not artifact:
            log("[ARTIFACT] No artifacts registered — nothing to launch", 'warning', 'forge')
            return jsonify({"status": "error", "message": "No builds found. Build something first."})

        result = launch_artifact(artifact)
        if not result.get('ok') and result.get('dependency') == 'godot':
            global _pending_godot_install
            _pending_godot_install = True
        msg = result.get('message', result.get('error', ''))
        log(f"[ARTIFACT] {msg}", 'success' if result.get('ok') else 'error', 'forge')
        return jsonify(result)
    except Exception as e:
        log(f"[ARTIFACT] Launch error: {e}", 'error', 'forge')
        return jsonify({"status": "error", "message": str(e)}), 200


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel Task Manager — REST API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/sentinel/tasks', methods=['GET'])
def api_sentinel_tasks():
    """List Sentinel tracked tasks with optional filters."""
    try:
        from workers.task_manager import list_tasks, recent_tasks
        status_filter  = request.args.get('status')
        source_filter  = request.args.get('source')
        project_filter = request.args.get('project_id')
        limit          = int(request.args.get('limit', 50))
        tasks = list_tasks(status=status_filter, source=source_filter,
                           project_id=project_filter, limit=limit)
        return jsonify({"status": "ok", "tasks": tasks, "count": len(tasks)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/tasks', methods=['POST'])
def api_sentinel_task_create():
    """Manually create a Sentinel task (for testing / custom workflows)."""
    try:
        from workers.task_manager import create_task
        data = request.get_json() or {}
        task = create_task(
            title      = data.get('title', 'Unnamed Task'),
            source     = data.get('source', 'system'),
            project_id = data.get('project_id'),
            metadata   = data.get('metadata', {}),
        )
        return jsonify({"status": "ok", "task": task})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/tasks/<task_id>', methods=['GET'])
def api_sentinel_task_get(task_id):
    """Get a single Sentinel task by ID."""
    try:
        from workers.task_manager import get_task
        task = get_task(task_id)
        if not task:
            return jsonify({"status": "not_found"}), 404
        return jsonify({"status": "ok", "task": task})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/tasks/<task_id>', methods=['PATCH'])
def api_sentinel_task_update(task_id):
    """Update a Sentinel task (status, progress, error, result_summary)."""
    try:
        from workers.task_manager import update_task
        data = request.get_json() or {}
        task = update_task(
            task_id,
            status         = data.get('status'),
            progress       = data.get('progress'),
            error          = data.get('error'),
            result_summary = data.get('result_summary'),
            metadata_update= data.get('metadata'),
        )
        if not task:
            return jsonify({"status": "not_found"}), 404
        return jsonify({"status": "ok", "task": task})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/tasks/<task_id>/cancel', methods=['POST'])
def api_sentinel_task_cancel(task_id):
    """Cancel a Sentinel task."""
    try:
        from workers.task_manager import cancel_task
        task = cancel_task(task_id)
        return jsonify({"status": "ok", "task": task})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel Project Manager — REST API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/sentinel/projects', methods=['GET'])
def api_sentinel_projects():
    """List all Sentinel projects."""
    try:
        from workers.projects.project_manager import list_projects
        return jsonify({"status": "ok", "projects": list_projects()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/projects', methods=['POST'])
def api_sentinel_project_create():
    """Create a new Sentinel project."""
    try:
        from workers.projects.project_manager import create_project
        data    = request.get_json() or {}
        name    = data.get('name', '').strip()
        color   = data.get('color')
        if not name:
            return jsonify({"status": "error", "error": "name required"}), 400
        project = create_project(name, color=color)
        return jsonify({"status": "ok", "project": project})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/projects/<project_id>', methods=['GET'])
def api_sentinel_project_get(project_id):
    from workers.projects.project_manager import get_project
    p = get_project(project_id)
    if not p:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "ok", "project": p})


@app.route('/api/sentinel/projects/<project_id>', methods=['PATCH'])
def api_sentinel_project_update(project_id):
    from workers.projects.project_manager import update_project
    data = request.get_json() or {}
    p = update_project(project_id, name=data.get('name'), color=data.get('color'))
    if not p:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": "ok", "project": p})


@app.route('/api/sentinel/projects/<project_id>', methods=['DELETE'])
def api_sentinel_project_delete(project_id):
    from workers.projects.project_manager import delete_project
    ok = delete_project(project_id)
    return jsonify({"status": "ok" if ok else "not_found"})


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel Artifact Registry — REST API (new canonical endpoints)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/sentinel/artifacts', methods=['GET'])
def api_sentinel_artifacts():
    """List Sentinel artifacts (most recent first)."""
    try:
        from workers.artifacts.artifact_registry import list_artifacts
        limit      = int(request.args.get('limit', 20))
        project_id = request.args.get('project_id')
        task_id    = request.args.get('task_id')
        arts = list_artifacts(limit=limit, project_id=project_id, task_id=task_id)
        return jsonify({"status": "ok", "artifacts": arts, "count": len(arts)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/artifacts/latest', methods=['GET'])
def api_sentinel_artifact_latest():
    try:
        from workers.artifacts.artifact_registry import get_latest_artifact
        art = get_latest_artifact()
        return jsonify({"status": "ok" if art else "none", "artifact": art})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/artifacts/launch', methods=['POST'])
def api_sentinel_artifact_launch():
    """Launch an artifact by task hint or the latest one."""
    try:
        from workers.artifacts.artifact_registry import (
            get_artifact_by_task, get_latest_artifact, launch_artifact
        )
        data       = request.get_json() or {}
        task_hint  = data.get('task', '').strip()
        artifact   = (get_artifact_by_task(task_hint) if task_hint else None) or get_latest_artifact()
        if not artifact:
            return jsonify({"status": "error", "message": "No artifacts found. Build something first."})
        result = launch_artifact(artifact)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/artifacts/<artifact_id>/assign', methods=['POST'])
def api_sentinel_artifact_assign(artifact_id):
    """Assign an artifact to a project."""
    try:
        from workers.artifacts import artifact_registry as _ar
        data = request.get_json() or {}
        art  = _ar.get_artifact(artifact_id)
        if not art:
            return jsonify({"status": "not_found"}), 404
        art['project_id'] = data.get('project_id')
        with _ar._LOCK:
            _ar._registry[artifact_id] = art
            _ar._persist()
        return jsonify({"status": "ok", "artifact": art})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


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
        "owner_mode":   OWNER_MODE,
        "build_type":   getattr(_bi, 'BUILD_TYPE',   'dev') if '_bi' in dir() else 'dev',
        "include_earn": getattr(_bi, 'INCLUDE_EARN', OWNER_MODE) if '_bi' in dir() else OWNER_MODE,
    }
    return jsonify({**data, "status": "ok", "data": data, "error": None})


@app.route('/api/config')
def api_config():
    """Return current model config and detected hardware."""
    try:
        cfg_path = Path(__file__).parent / "config" / "model_config.json"
        cfg = {}
        if cfg_path.exists():
            with open(cfg_path) as f:
                import json as _j; cfg = _j.load(f)
        vram = 0
        try:
            import subprocess as _sp
            r = _sp.run(['nvidia-smi','--query-gpu=memory.total','--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                vram = round(int(r.stdout.strip().split('\n')[0]) / 1024, 1)
        except Exception: pass
        return jsonify({"status": "ok", "active_model": cfg.get("model", os.getenv("AIDER_MODEL","ollama/qwen2.5-coder:14b")),
                        "vram_gb": vram, "config": cfg})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200

@app.route('/api/settings/keys', methods=['GET'])
def api_settings_keys_get():
    """Return masked API keys."""
    keys = {}
    for k, env in [('openai','OPENAI_API_KEY'),('claude','ANTHROPIC_API_KEY')]:
        v = os.getenv(env, '')
        keys[k] = ('*' * (len(v)-4) + v[-4:]) if len(v) > 4 else (v if v else '')
    return jsonify({"status": "ok", **keys})

@app.route('/api/settings/keys', methods=['POST'])
def api_settings_keys_post():
    """Save an API key to the .env file."""
    try:
        data = request.get_json() or {}
        provider = data.get('provider', '')
        key = data.get('key', '').strip()
        env_map = {'openai': 'OPENAI_API_KEY', 'claude': 'ANTHROPIC_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}
        env_name = env_map.get(provider)
        if not env_name:
            return jsonify({"status": "error", "error": "Unknown provider"}), 200
        env_path = resolve_env_path()
        lines = env_path.read_text(encoding='utf-8').splitlines() if env_path.exists() else []
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(env_name + '='):
                lines[i] = f'{env_name}={key}'; updated = True; break
        if not updated:
            lines.append(f'{env_name}={key}')
        env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.environ[env_name] = key
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200

@app.route('/api/settings/model', methods=['POST'])
def api_settings_model_post():
    """Switch the active local model."""
    try:
        data = request.get_json() or {}
        model_id = data.get('model', '').strip()
        if not model_id:
            return jsonify({"status": "error", "error": "model required"}), 200
        cfg_path = resolve_config_dir() / "model_config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _j
        cfg = _j.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        cfg['model'] = model_id
        cfg_path.write_text(_j.dumps(cfg, indent=2))
        os.environ['AIDER_MODEL'] = f'ollama/{model_id}'
        return jsonify({"status": "ok", "model": model_id})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200

# Track pull progress in memory
_pull_status: dict = {}

@app.route('/api/settings/model/pull', methods=['POST'])
def api_settings_model_pull():
    """Start pulling a model from Ollama in the background."""
    import threading, json as _j, requests as _req
    data = request.get_json() or {}
    model_id = data.get('model', '').strip()
    if not model_id:
        return jsonify({"status": "error", "error": "model required"}), 200
    _pull_status[model_id] = {'done': False, 'progress': 0}

    def _pull():
        try:
            log(f'Pulling Ollama model: {model_id}', 'info', 'settings')
            resp = _req.post('http://localhost:11434/api/pull',
                             json={'name': model_id, 'stream': True}, stream=True, timeout=1800)
            for line in resp.iter_lines():
                if line:
                    try:
                        d = _j.loads(line)
                        total = d.get('total', 0); comp = d.get('completed', 0)
                        pct = int(comp * 100 / total) if total else 0
                        _pull_status[model_id] = {'done': False, 'progress': pct, 'status': d.get('status','')}
                        emit_event('log_event', {'type':'settings','level':'info','message': f'Pulling {model_id}: {pct}%',
                                                  'timestamp': datetime.now().isoformat()})
                    except Exception: pass
            _pull_status[model_id] = {'done': True, 'progress': 100}
            log(f'Model {model_id} pulled successfully', 'success', 'settings')
        except Exception as exc:
            _pull_status[model_id] = {'done': True, 'progress': 0, 'error': str(exc)}
            log(f'Model pull failed: {exc}', 'error', 'settings')

    threading.Thread(target=_pull, daemon=True).start()
    return jsonify({"status": "ok", "message": f"Pulling {model_id} in background"})

@app.route('/api/settings/model/pull/status')
def api_settings_model_pull_status():
    model_id = request.args.get('model', '')
    return jsonify(_pull_status.get(model_id, {'done': False, 'progress': 0}))

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
            inserted = run_async(run_scan(dry_run=False), timeout=600.0)
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
                from workers.task_manager import TaskContext
                with TaskContext(f"Build {task[:60]}", source="forge") as ctx:
                    forge_result, _art = _run_forge_build(task, output_dir, sentinel_task_id=ctx.task_id)
                result_ok = forge_result.success
                log(
                    'Task complete' if result_ok else f'Task failed: {forge_result.error}',
                    'success' if result_ok else 'error',
                    'forge',
                )
                fail_msg = None
                if not result_ok and forge_result.error:
                    partial = f"Partial files: {', '.join(forge_result.files)}" if forge_result.files else "No files created."
                    fail_msg = f"Build stopped: {forge_result.error}. {partial} Check the Log tab for details."
                # Save build result to long-term memory with HIGH importance
                if memory_v2 is not None:
                    try:
                        mem_content = (
                            f"Sentinel built: {task}. "
                            f"Builder: {forge_result.builder}. "
                            f"Entry point: {forge_result.entry_point}. "
                            f"All files: {', '.join(forge_result.files)}. "
                            f"Output dir: {forge_result.output_dir}. "
                            f"Built at: {datetime.now().isoformat()}. "
                            f"Success: {forge_result.success}."
                        )
                        memory_v2.remember(mem_content, source='sentinel',
                                           topic='build_completion', importance=9)
                    except Exception:
                        pass
            except Exception as exc:
                log(f'Forge engine error: {exc}', 'error', 'forge')
                emit_event('forge_complete', {'success': False, 'output': str(exc), 'files_modified': [], 'entry_point': None, 'output_dir': None, 'error': str(exc), 'message': f'Forge engine error: {exc}'})

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return jsonify({"status": "started", "message": "Forge builder is working on your task"})

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


# In-memory log buffer for /api/log/recent (ring buffer, max 500 entries)
_log_buffer = []
_log_buffer_lock = threading.Lock()
_LOG_BUFFER_MAX = 500

def _log_buffer_append(message: str, level: str, source: str):
    """Append to the in-memory log buffer for self-diagnosis."""
    entry = {
        'time': datetime.now().strftime('%H:%M:%S'),
        'type': source,
        'level': level,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }
    with _log_buffer_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > _LOG_BUFFER_MAX:
            del _log_buffer[:-_LOG_BUFFER_MAX]

# Monkey-patch log() to also feed the buffer
_orig_log = log
def log(message: str, level: str = 'info', source: str = 'system') -> None:
    _orig_log(message, level, source)
    _log_buffer_append(message, level, source)


@app.route('/api/log/recent')
def api_log_recent():
    """Return recent in-memory log entries for self-diagnosis."""
    try:
        limit = int(request.args.get('limit', 100))
        level_filter = request.args.get('level', '').lower()
        with _log_buffer_lock:
            entries = list(_log_buffer[-limit:])
        if level_filter:
            entries = [e for e in entries if e.get('level', '').lower() == level_filter]
        return jsonify({'entries': entries, 'count': len(entries)})
    except Exception as e:
        return jsonify({'entries': [], 'error': str(e)}), 500


# In-memory chat session messages (survives the Flask process lifetime)
_chat_session = []
_chat_session_lock = threading.Lock()

# ── Pending task store (approval flow) ────────────────────────────────────────
import uuid as _uuid_mod
_pending_tasks: dict = {}
_pending_latest_id: str = ''
_pending_godot_install: bool = False

def _store_pending_task(task_data: dict) -> str:
    global _pending_latest_id
    task_id = task_data.get('task_id') or str(_uuid_mod.uuid4())
    task_data['task_id'] = task_id
    _pending_tasks[task_id] = task_data
    _pending_latest_id = task_id
    return task_id

def _get_pending_task() -> dict:
    if _pending_latest_id and _pending_latest_id in _pending_tasks:
        return _pending_tasks[_pending_latest_id]
    return {}

def _clear_pending_task():
    global _pending_latest_id
    tid = _pending_latest_id
    _pending_latest_id = ''
    _pending_tasks.pop(tid, None)

_APPROVE_WORDS = ['approve', 'yes', 'go ahead', 'do it', 'start', 'build it',
                  'proceed', 'confirmed', 'ok', 'okay', 'yeah', 'yep', 'sure']
_DENY_WORDS    = ['deny', 'no', 'cancel', 'stop', 'abort',
                  'nevermind', 'nope', "don't", 'dont']

@app.route('/api/memory/session', methods=['POST'])
def api_memory_session_write():
    """Store a single chat exchange message to in-memory session."""
    try:
        data = request.get_json() or {}
        role = data.get('role', 'sentinel')
        content = data.get('content', '')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        entry = {'role': role, 'content': content, 'timestamp': timestamp}
        with _chat_session_lock:
            _chat_session.append(entry)
            if len(_chat_session) > 200:
                del _chat_session[:-200]
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/memory/recent')
def api_memory_recent_chat():
    """Return recent chat session messages (current session only)."""
    try:
        limit = int(request.args.get('limit', 50))
        since = request.args.get('since', None)
        with _chat_session_lock:
            msgs = list(_chat_session)
        if since:
            msgs = [m for m in msgs if m.get('timestamp', '') >= since]
        msgs = msgs[-limit:]
        return jsonify({'messages': msgs, 'count': len(msgs)})
    except Exception as e:
        return jsonify({'messages': [], 'error': str(e)}), 500


@app.route('/api/memory/sessions')
def api_memory_sessions():
    """Return list of past chat sessions grouped by date."""
    try:
        if memory_v2 is not None:
            sessions = memory_v2.get_chat_sessions()
        else:
            sessions = []
        return jsonify({'sessions': sessions})
    except Exception as e:
        return jsonify({'sessions': [], 'error': str(e)}), 500


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
@require_auth
def api_openclaw_command():
    """
    OpenClaw command endpoint.
    Allows OpenClaw to control SentinelAI through safe command routing.
    """
    try:
        data = request.get_json() or {}
        command = data.get('command')
        parameters = data.get('parameters', {})
        auth_header = request.headers.get('Authorization', '')

        if not command:
            return jsonify({"error": "command required"}), 400

        # The global before_request gate already verified the token, but we
        # re-check here so the router's requires_auth commands are explicitly
        # tied to a constant-time match rather than presence of any header.
        authorized = verify_auth_token(auth_header)

        router = OpenClawCommandRouter(auth_token=None, authorized=authorized)
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
        selection = get_model_router().route_for_task(
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


@app.route('/api/setup/scan', methods=['POST'])
def api_setup_scan():
    """Fast non-blocking machine scan; background setup starts immediately."""
    try:
        from core.onboarding.pipeline import get_onboarding_pipeline
        from core.model_runtime import get_model_runtime
        from core.onboarding.debug_logger import StepWatchdog

        with StepWatchdog("api_setup_scan"):
            pipe = get_onboarding_pipeline()
            profile = pipe.run_fast_scan()
            pipe.start_background_setup(profile)
            readiness = get_model_runtime().readiness_quick()
            return jsonify({
                **profile,
                "readiness": readiness,
                "progress": pipe.progress(),
                "allow_chat": True,
                "setup_complete": False,
            })
    except Exception as e:
        logger.exception("api_setup_scan failed")
        from core.onboarding.pipeline import get_onboarding_pipeline
        get_onboarding_pipeline().force_complete(allow_degraded=True)
        return jsonify({
            "error": "scan_degraded",
            "allow_chat": True,
            "user_message": "Sentinel will finish setup in the background.",
            "cpu_only_profile": True,
        }), 200


@app.route('/api/setup/status')
def api_setup_status():
    """Cached profile + quick readiness — never runs a blocking full scan."""
    try:
        from workers.setup.machine_scanner import get_machine_scanner
        from core.model_runtime import get_model_runtime
        from core.onboarding.pipeline import get_onboarding_pipeline

        profile = get_machine_scanner().load_cached() or {}
        readiness = get_model_runtime().readiness_quick()
        progress = get_onboarding_pipeline().progress()
        models = readiness.get("models") or []
        model_downloaded = all(m.get("installed") for m in models if m.get("required"))

        return jsonify({
            **profile,
            "model_downloaded": model_downloaded,
            "setup_complete": bool(progress.get("completed")) or bool(readiness.get("ready")),
            "readiness": readiness,
            "progress": progress,
            "recommended_models": readiness.get("required"),
            "allow_chat": True,
        })
    except Exception as e:
        logger.exception("api_setup_status failed")
        return jsonify({"status": "ok", "allow_chat": True, "error": "status_degraded"}), 200


@app.route('/api/setup/install-ollama', methods=['POST'])
def api_setup_install_ollama():
    """Download/install Ollama (Windows) and start the service."""
    try:
        from core.model_runtime import get_model_runtime

        def _run():
            result = get_model_runtime().install_ollama(
                progress_cb=lambda p: emit_event("setup_progress", {"step": "ollama_install", **p}),
            )
            emit_event("setup_progress", {"step": "ollama_install", "complete": True, **result})

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"status": "installing", "user_message": get_model_runtime().user_message()})
    except Exception as e:
        return jsonify({"status": "error", "user_message": "Setup could not continue. Please try again."}), 500


@app.route('/api/setup/pull-model', methods=['POST'])
def api_setup_pull_model():
    """Pull hardware-appropriate Llama + Dolphin models. Progress via Socket.IO."""
    try:
        from core.model_runtime import get_model_runtime

        def pull():
            rt = get_model_runtime()
            log("Pulling recommended models for this machine", "info", "setup")

            def progress(p):
                emit_event("setup_progress", {"step": "model_download", **p})

            result = rt.install_required_models(progress_cb=progress)
            emit_event("setup_progress", {
                "step": "model_download",
                "complete": True,
                "success": result.get("ok"),
                "message": result.get("user_message", ""),
            })
            log(
                f"Model install {'complete' if result.get('ok') else 'incomplete'}",
                "success" if result.get("ok") else "error",
                "setup",
            )

        threading.Thread(target=pull, daemon=True).start()
        req = get_model_runtime().required_models()
        return jsonify({"status": "pulling", "models": req.get("models", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/setup/validate', methods=['POST'])
def api_setup_validate():
    """Run inference test before enabling chat."""
    try:
        from core.model_runtime import get_model_runtime
        result = get_model_runtime().validate_inference()
        return jsonify({"status": "ok" if result.get("ok") else "failed", **result})
    except Exception as e:
        return jsonify({"status": "error", "user_message": "Validation could not complete. Please try again."}), 500


@app.route('/api/setup/complete', methods=['POST'])
def api_setup_complete():
    """Always allow entering chat; mark components needing repair when degraded."""
    try:
        from core.model_runtime import get_model_runtime
        result = get_model_runtime().mark_setup_complete()
        return jsonify({"status": "ok", "allow_chat": True, **result}), 200
    except Exception as e:
        logger.exception("api_setup_complete")
        from core.onboarding.pipeline import get_onboarding_pipeline
        result = get_onboarding_pipeline().force_complete(allow_degraded=True)
        return jsonify({"status": "ok", "allow_chat": True, **result}), 200


@app.route('/api/setup/intent', methods=['POST'])
def api_setup_intent():
    """Save the user's primary intent from the setup wizard."""
    try:
        data = request.json or {}
        intent = data.get('intent', 'all')
        log(f"Setup intent: {intent}", 'info', 'setup')
        return jsonify({"status": "ok", "intent": intent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

def _collect_system_stats() -> dict:
    """Collect CPU / RAM / DISK (+ GPU when nvidia-smi is present).

    Used by both the /api/system/stats endpoint (for initial fetch) and the
    background `system_stats` socket broadcaster (for live updates).
    """
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
    return data


@app.route('/api/system/stats')
def api_system_stats():
    """CPU / RAM / DISK (+ GPU when nvidia-smi is present) for the HUD monitor."""
    return jsonify({"status": "ok", "data": _collect_system_stats(), "error": None})


# ─── Background broadcasters (replace frontend polling with one server-side cadence) ──
_BROADCAST_INTERVAL_SECONDS = 5.0
_broadcasters_started = False
_broadcasters_lock = threading.Lock()


def _start_broadcasters_once():
    """Spin up one background thread that pushes system_stats over Socket.IO.

    Replaces N renderer-side `setInterval` polls with one server cadence;
    every connected dashboard now gets updates by listening to the
    `system_stats` event instead of polling /api/system/stats every 5 s.
    """
    global _broadcasters_started
    with _broadcasters_lock:
        if _broadcasters_started:
            return
        _broadcasters_started = True

    def _system_stats_loop():
        import time as _t
        while True:
            try:
                if SOCKETIO_AVAILABLE and socketio is not None:
                    socketio.emit("system_stats", {"data": _collect_system_stats()})
            except Exception as exc:
                logger.debug("system_stats broadcast failed: %s", exc)
            _t.sleep(_BROADCAST_INTERVAL_SECONDS)

    t = threading.Thread(target=_system_stats_loop, name="system-stats-broadcaster", daemon=True)
    t.start()


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


def _run_forge_build(description: str, output_dir=None, sentinel_task_id: str = ''):
    """
    Execute build via ForgeBuildEngine (builder router + verification + artifact).

    Emits forge_complete only after verification, launch verified, and artifact saved.
    Files alone are not success — the app must be runnable.
    """
    global _pending_godot_install
    from builders.build_tracker import begin_build, finish_build, mark_launch_ready, update_build
    from builders.common.logging_util import log_builder
    from builders.forge_engine import ForgeBuildEngine
    from builders.router import engine_for_route, route_build
    from workers.artifacts.artifact_registry import register_artifact

    build_type = route_build(description, socketio)

    title = description[:60] if description else "Build"
    if sentinel_task_id:
        begin_build(
            sentinel_task_id,
            title,
            description,
            build_type.value,
            engine_for_route(build_type),
        )

    set_worker("forge", "running", current_task=title, activity="Planning")

    def _on_progress(pct: int, msg: str) -> None:
        if not sentinel_task_id:
            return
        try:
            from workers.task_manager import update_task, RUNNING
            b = update_build(current_stage=msg, progress_percent=pct)
            files = (b or {}).get("files_created") or []
            update_task(
                sentinel_task_id,
                status=RUNNING,
                progress=pct,
                result_summary=msg,
                current_stage=msg,
                files_created=files if files else None,
            )
        except Exception:
            pass

    engine = ForgeBuildEngine(socketio)
    try:
        result = engine.build(
            description, output_dir, on_progress=_on_progress, build_type=build_type,
        )
    except Exception as exc:
        finish_build(False, str(exc))
        set_worker("forge", "error", current_task=None, activity=str(exc))
        if socketio:
            socketio.emit('forge_complete', {
                'success': False,
                'files_modified': [],
                'entry_point': None,
                'output_dir': None,
                'error': str(exc),
                'task_id': sentinel_task_id,
            })
        raise

    if not result.success or not result.verified:
        err = result.error or (result.verification.message if result.verification else "Verification failed")
        log_builder(f"Build failed: {err}", "error", socketio)
        finish_build(False, err)
        set_worker("forge", "error", current_task=None, activity=err)
        if socketio:
            socketio.emit('forge_complete', {
                'success': False,
                'files_modified': result.files,
                'entry_point': result.entry_point,
                'output_dir': result.output_dir,
                'error': err,
                'task_id': sentinel_task_id,
                'verification_status': 'failed',
                'build_complete': False,
            })
        return result, {}

    # ── Stage 7–8: Launch + verify runnable ───────────────────────────────────
    log_builder("Stage 7/9 Launch", "info", socketio)
    update_build(current_stage="Launch", progress_percent=85)
    if sentinel_task_id:
        try:
            from workers.task_manager import update_task, RUNNING
            update_task(sentinel_task_id, status=RUNNING, progress=85, current_stage="Launch")
        except Exception:
            pass

    from builders.launch_verifier import verify_launch
    from builders.router import BuildType as _BT

    launch_ok, launch_msg, launch_details = verify_launch(result, build_type, socketio=socketio)

    if not launch_ok and launch_details.get("needs_install") and launch_details.get("dependency") == "godot":
        log_builder("Installing Godot…", "info", socketio)
        _pending_godot_install = True
        try:
            from builders.runtime.godot_runtime import install_godot
            inst = install_godot(log_fn=lambda m, lvl="info": log_builder(m, lvl, socketio))
            if inst.get("ok"):
                from builders.runtime.godot_runtime import find_godot
                gpath = find_godot() or inst.get("path")
                if gpath and result.output_dir:
                    result.launch_command = f'"{gpath}" --path "{result.output_dir}"'
                launch_ok, launch_msg, launch_details = verify_launch(result, build_type, socketio=socketio)
            else:
                launch_msg = inst.get("error", "Godot install failed")
        except Exception as _gi:
            launch_msg = str(_gi)
        _pending_godot_install = False

    if not launch_ok:
        log_builder(f"Launch failed: {launch_msg}", "error", socketio)
        finish_build(False, launch_msg)
        set_worker("forge", "error", current_task=None, activity=launch_msg)
        if socketio:
            socketio.emit('forge_complete', {
                'success': False,
                'files_modified': result.files,
                'entry_point': result.entry_point,
                'output_dir': result.output_dir,
                'error': launch_msg,
                'task_id': sentinel_task_id,
                'verification_status': 'verified',
                'launch_verified': False,
                'build_complete': False,
            })
        if launch_details.get("needs_install"):
            if launch_details.get("dependency") == "godot":
                _pending_godot_install = True
            if socketio:
                socketio.emit("launch_dependency_prompt", launch_details)
        return result, {}

    result.launch_verified = True
    result.launch_message = launch_msg
    result.success = True

    # ── Stage 9/9: Register artifact ───────────────────────────────────────────
    log_builder("Stage 9/9 Registering artifact", "info", socketio)
    update_build(current_stage="Registering artifact", progress_percent=92)
    if sentinel_task_id:
        try:
            from workers.task_manager import update_task, RUNNING
            update_task(sentinel_task_id, status=RUNNING, progress=92,
                         current_stage="Registering artifact")
        except Exception:
            pass

    ver_status = "verified"
    art = register_artifact(
        task=description[:120],
        entry_point=result.entry_point,
        output_dir=result.output_dir,
        files=result.files,
        launch_command=result.launch_command,
        task_id=sentinel_task_id or None,
        artifact_type=result.artifact_type,
        builder_used=result.builder,
        project_type=result.project_type,
        verification_status=ver_status,
        build_logs=result.build_logs,
    )
    mark_launch_ready(art.get("id", ""))
    log_builder(f"Build Complete — {launch_msg}", "success", socketio)
    update_build(current_stage="Build Complete", progress_percent=100)

    log(
        f"[FORGE] {result.builder} ({result.project_type}) — {ver_status} — {result.output_dir}",
        'success',
        'forge',
    )
    finish_build(True)
    set_worker("forge", "idle", current_task=None, activity="Build complete")

    if socketio:
        socketio.emit('forge_complete', {
            'success': True,
            'files_modified': result.files,
            'entry_point': result.entry_point,
            'output_dir': result.output_dir,
            'error': '',
            'task_id': sentinel_task_id,
            'artifact_id': art.get('id'),
            'builder': result.builder,
            'project_type': result.project_type,
            'verification_status': ver_status,
            'launch_command': result.launch_command,
            'launch_verified': True,
            'launch_message': launch_msg,
            'build_complete': True,
        })
    return result, art


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
                    from workers.task_manager import TaskContext
                    with TaskContext(f"Build {description[:60]}", source="forge") as ctx:
                        _run_forge_build(description, output_path, sentinel_task_id=ctx.task_id)
                except Exception as exc:
                    log(f'Build error: {exc}', 'error', 'forge')
                    emit_event('forge_complete', {
                        'success': False, 'output': str(exc),
                        'files_modified': [], 'entry_point': None,
                        'output_dir': None, 'error': str(exc),
                    })

            t = threading.Thread(target=build, daemon=True)
            t.start()

            response_text = (
                f"On it. Building {description[:80]} now. "
                f"Watch the Log tab → BUILDER filter for live stages."
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


# ─── Trial & Access Control ───────────────────────────────────────────────────

from workers.licensing.trial_manager import get_trial_manager as _get_trial_mgr

_trial_manager = _get_trial_mgr()
_trial_manager.start_trial()   # no-op if already started


def check_access() -> dict | None:
    """
    Returns None if the user may proceed.
    Returns a JSON-serializable error dict if access is blocked.
    Owner mode always passes; pro license always passes; active trial passes;
    expired trial blocks.
    """
    if OWNER_MODE:
        return None
    if license_manager.is_restricted_mode():
        return {
            'blocked': True,
            'reason': 'restricted_mode',
            'message': 'Beta period ended. Activate your license to continue using Sentinel.',
            'restricted_mode': True,
        }
    if license_manager.is_pro():
        return None
    trial = _trial_manager.get_status()
    if trial.get('active'):
        return None
    if trial.get('never_started'):
        _trial_manager.start_trial()
        return None
    return {
        'blocked': True,
        'reason': 'trial_expired',
        'message': 'Your 7-day trial has expired. Activate a license key to continue.',
        'trial': trial,
    }


@app.route('/api/trial/status', methods=['GET'])
def api_trial_status():
    """Return trial status + license tier."""
    try:
        if OWNER_MODE:
            return jsonify({
                'active': False,
                'expired': False,
                'owner_mode': True,
                'days_remaining': 999,
                'hours_remaining': 0,
                'is_pro': True,
                'tier': 'owner',
                'message': 'Owner build - no trial',
            })
        trial = _trial_manager.get_status()
        lic = license_manager.get_status()
        return jsonify({**trial, 'is_pro': lic.get('is_pro', False), 'tier': lic.get('tier', 'free')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Anonymous Telemetry API ─────────────────────────────────────────────────

from workers.telemetry.telemetry_manager import get_telemetry_manager as _get_tm

_telemetry = _get_tm()


@app.route('/api/telemetry/status', methods=['GET'])
def api_telemetry_status():
    """Return current telemetry opt-in status."""
    return jsonify({'opted_in': _telemetry.is_opted_in()})


@app.route('/api/telemetry/opt-in', methods=['POST'])
def api_telemetry_opt_in():
    """Opt in to anonymous telemetry."""
    try:
        _telemetry.opt_in()
        _telemetry.start()
        return jsonify({'status': 'ok', 'opted_in': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/telemetry/opt-out', methods=['POST'])
def api_telemetry_opt_out():
    """Opt out of anonymous telemetry."""
    try:
        _telemetry.opt_out()
        return jsonify({'status': 'ok', 'opted_in': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/telemetry/event', methods=['POST'])
def api_telemetry_event():
    """Record a single anonymous event from the frontend."""
    try:
        data = request.get_json(force=True) or {}
        event = data.get('event', 'unknown')
        props = {k: v for k, v in (data.get('props') or {}).items()
                 if k not in ('content', 'message', 'prompt', 'response', 'key')}
        _telemetry.track(event, props)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Kill Switch API ──────────────────────────────────────────────────────────

from workers.licensing.killswitch_checker import get_killswitch_checker as _get_ksc

_killswitch = _get_ksc(
    is_owner=OWNER_MODE,
    is_pro_fn=lambda: license_manager.is_pro(),
)


@app.route('/api/killswitch/check', methods=['GET'])
def api_killswitch_check():
    """Return current kill-switch status for the frontend."""
    try:
        status = _killswitch.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)}), 500


@app.route('/api/killswitch/refresh', methods=['POST'])
def api_killswitch_refresh():
    """Force an immediate kill-switch check (owner use only)."""
    try:
        status = _killswitch.check_now()
        return jsonify(status)
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)}), 500


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
    """Multi-source earn jobs: bounty programs + remote jobs.

    Query params:
      refresh=1  — fetch upstream (respects 24h cache unless force=1)
      force=1    — bypass cache completely
      limit=N    — max bounty programs (default 50)
    """
    import threading

    refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50

    results = {"bounty": [], "remoteok": [], "discovery": None, "error": None}
    discovery_box: dict = {}

    def _fetch_bounty():
        try:
            from workers.earn.program_discovery import discover_programs
            programs, meta = discover_programs(
                limit=limit,
                force_refresh=force,
                refresh=refresh and not force,
                socketio=socketio,
            )
            results["bounty"] = programs
            discovery_box["meta"] = meta.to_dict()
        except Exception as exc:
            logger.exception("earn discovery failed: %s", exc)
            results["error"] = str(exc)

    def _fetch_remoteok():
        try:
            from workers.earn.sources.remoteok_scanner import scan as scan_remote
            results["remoteok"] = scan_remote(limit=15)
        except Exception as exc:
            logger.debug("remoteok scan failed: %s", exc)

    t1 = threading.Thread(target=_fetch_bounty, daemon=True)
    t2 = threading.Thread(target=_fetch_remoteok, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=45)
    t2.join(timeout=12)

    jobs = results["bounty"] + results["remoteok"]
    disc = discovery_box.get("meta") or {}

    return jsonify({
        "status": "ok",
        "jobs": jobs,
        "counts": {
            "bounty": len(results["bounty"]),
            "remoteok": len(results["remoteok"]),
            "discovered_total": disc.get("discovered_total"),
            "bounty_eligible_total": disc.get("bounty_eligible_total"),
        },
        "discovery": disc,
        "error": results["error"],
    })


@app.route('/api/earn/diagnostics', methods=['GET'])
def api_earn_diagnostics():
    """Earn discovery diagnostics for the diagnostics panel."""
    try:
        from workers.earn.program_discovery import get_discovery_diagnostics
        return jsonify({"status": "ok", **get_discovery_diagnostics()})
    except Exception as e:
        logger.exception("earn diagnostics failed")
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/earn/discovery/dashboard', methods=['GET'])
def api_earn_discovery_dashboard():
    """Full Earn Discovery Dashboard payload (500+ programs, overview, metrics)."""
    try:
        refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        force = request.args.get("force", "").lower() in ("1", "true", "yes")
        from workers.earn.dashboard_service import fetch_dashboard_programs, log_dashboard_event

        if force:
            log_dashboard_event("Force refresh — bypassing cache", socketio)
        elif refresh:
            log_dashboard_event("Discovery Started", socketio)

        programs, overview, extra = fetch_dashboard_programs(
            refresh=refresh or force,
            force=force,
            socketio=socketio,
        )

        if refresh or force:
            disc = extra.get("discovery") or {}
            earn_log_msg = (
                f"Source: {(disc.get('source') or 'API').upper()} · "
                f"Programs Discovered: {disc.get('discovered_total') or len(programs)} · "
                f"Duration: {round((disc.get('duration_ms') or 0) / 1000, 1)}s"
            )
            from workers.earn.earn_diagnostics import earn_log
            earn_log(socketio, earn_log_msg)

        log_dashboard_event("Dashboard Loaded", socketio)
        return jsonify({
            "status": "ok",
            "programs": programs,
            "overview": overview,
            "metrics": extra.get("metrics"),
            "discovery": extra.get("discovery"),
        })
    except Exception as e:
        logger.exception("earn dashboard failed")
        return jsonify({"status": "error", "error": str(e), "programs": []}), 200


@app.route('/api/earn/discovery/program/<handle>', methods=['GET'])
def api_earn_discovery_program(handle: str):
    """Program details for dashboard side panel."""
    try:
        from workers.earn.dashboard_service import get_program_detail, log_dashboard_event
        detail = get_program_detail(handle)
        log_dashboard_event(f"Program Selected: {handle}", socketio)
        return jsonify({"status": "ok", "program": detail})
    except Exception as e:
        logger.exception("earn program detail failed")
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/earn/discovery/log', methods=['POST'])
def api_earn_discovery_log():
    """Client-side dashboard interaction logs → [EARN] log stream."""
    try:
        data = request.get_json() or {}
        msg = (data.get("message") or "").strip()
        if not msg:
            return jsonify({"status": "error", "error": "message required"}), 400
        from workers.earn.earn_diagnostics import earn_log
        earn_log(socketio, msg, data.get("level", "info"))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


# ─── Earn Research Mode API ───────────────────────────────────────────────────

@app.route('/api/earn/research/start', methods=['POST'])
def api_earn_research_start():
    """Accept program → analyze scope → launch research pipeline (no auto-submit)."""
    try:
        program_data = request.get_json() or {}
        if not program_data.get("handle") and not program_data.get("program") and not program_data.get("title"):
            return jsonify({"status": "error", "error": "program data required"}), 200
        from workers.earn.research.pipeline import run_research_pipeline
        session = run_research_pipeline(program_data, socketio=socketio, background=True)
        log(f'Earn research started: {session.program_title} ({session.id})', 'info', 'earn')
        return jsonify({
            "status": "ok",
            "session_id": session.id,
            "message": f"Research pipeline started for {session.program_title}",
        })
    except Exception as e:
        logger.exception("earn research start failed")
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/earn/research/sessions', methods=['GET'])
def api_earn_research_sessions():
    try:
        from workers.earn.research.store import list_sessions
        return jsonify({"status": "ok", "sessions": list_sessions()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "sessions": []}), 200


@app.route('/api/earn/research/<session_id>', methods=['GET'])
def api_earn_research_session(session_id):
    try:
        from workers.earn.research.pipeline import get_research_session
        session = get_research_session(session_id)
        if not session:
            return jsonify({"status": "error", "error": "session not found"}), 200
        return jsonify({"status": "ok", "session": session.to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/earn/research/<session_id>/finding/<finding_id>/status', methods=['POST'])
def api_earn_research_finding_status(session_id, finding_id):
    """Update finding workflow status (human review — no submission)."""
    try:
        from workers.earn.research.pipeline import get_research_session
        from workers.earn.research.store import save_session
        data = request.get_json() or {}
        status = data.get("status", "").strip()
        session = get_research_session(session_id)
        if not session:
            return jsonify({"status": "error", "error": "session not found"}), 200
        updated = False
        for f in session.potential_findings:
            if f.get("id") == finding_id:
                f["status"] = status
                if status == "Validated":
                    f["workflow_stage"] = "human_review"
                updated = True
                break
        if not updated:
            return jsonify({"status": "error", "error": "finding not found"}), 200
        save_session(session)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/earn/research/<session_id>/evidence', methods=['POST'])
def api_earn_research_evidence(session_id):
    try:
        from workers.earn.research.pipeline import get_research_session
        from workers.earn.research.store import add_evidence
        data = request.get_json() or {}
        kind = data.get("kind", "note")
        content = data.get("content", "")
        filename = data.get("filename") or f"evidence_{kind}.txt"
        session = get_research_session(session_id)
        if not session:
            return jsonify({"status": "error", "error": "session not found"}), 200
        item = add_evidence(session, kind, content, filename)
        return jsonify({"status": "ok", "evidence": item.to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


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


@app.route('/market/prediction', methods=['GET'])
def api_market_prediction():
    """Fetch top markets from Polymarket and Kalshi — no API key needed."""
    import requests as _req
    results: dict = {'polymarket': [], 'kalshi': []}

    # Polymarket — free REST API
    try:
        resp = _req.get(
            'https://gamma-api.polymarket.com/markets?closed=false&limit=20&order=volume&ascending=false',
            timeout=10,
            headers={'User-Agent': 'SentinelAI/1.0'},
        )
        if resp.status_code == 200:
            import json as _json
            for m in resp.json()[:10]:
                raw_prices = m.get('outcomePrices', [])
                # outcomePrices may arrive as a JSON-encoded string e.g. '["0.95","0.05"]'
                if isinstance(raw_prices, str):
                    try:
                        raw_prices = _json.loads(raw_prices)
                    except Exception:
                        raw_prices = []
                try:
                    yes_p = f"{float(raw_prices[0]):.2f}" if raw_prices else '?'
                    no_p = f"{float(raw_prices[1]):.2f}" if len(raw_prices) > 1 else '?'
                except (ValueError, IndexError):
                    yes_p, no_p = '?', '?'
                results['polymarket'].append({
                    'question': m.get('question', ''),
                    'yes_price': yes_p,
                    'no_price': no_p,
                    'volume': m.get('volume', 0),
                    'url': f"https://polymarket.com/event/{m.get('slug', '')}",
                })
    except Exception as e:
        results['polymarket_error'] = str(e)

    # Kalshi — free public read API
    try:
        resp = _req.get(
            'https://trading-api.kalshi.com/trade-api/v2/markets?limit=10&status=open',
            headers={'accept': 'application/json', 'User-Agent': 'SentinelAI/1.0'},
            timeout=10,
        )
        if resp.status_code == 200:
            for m in resp.json().get('markets', [])[:10]:
                results['kalshi'].append({
                    'title': m.get('title', ''),
                    'yes_price': m.get('yes_bid', '?'),
                    'no_price': m.get('no_bid', '?'),
                    'volume': m.get('volume', 0),
                    'close_time': m.get('close_time', ''),
                })
    except Exception as e:
        results['kalshi_error'] = str(e)

    return jsonify(results)


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

def _save_chat_exchange(user_msg: str, sentinel_response: str) -> None:
    """Save a complete chat exchange to memory and chat session buffer."""
    # Log response to chat source (visible in Log panel CHAT filter)
    log(f"SENTINEL: {sentinel_response[:300]}", 'info', 'chat')
    # Save to chat session (for UI history)
    with _chat_session_lock:
        _chat_session.append({'role': 'sentinel', 'content': sentinel_response, 'timestamp': datetime.now().isoformat()})
        if len(_chat_session) > 200:
            del _chat_session[:-200]
    # Long-term memory — skip short/social turns to avoid polluting greetings with old debug text
    if memory_v2 is not None:
        try:
            from core.chat.context import should_attach_memory
            if should_attach_memory(user_msg):
                memory_v2.remember(
                    content=f"User: {user_msg}\nSentinel: {sentinel_response[:500]}",
                    source="user",
                    topic=user_msg[:80],
                    importance=5,
                )
        except Exception as _e:
            logger.debug("Memory save failed: %s", _e)


def _chat_quick_response(message: str) -> str:
    """Chat via Ollama → Claude → OpenAI → web-assistant; always returns text."""
    from core.chat.context import log_chat_context, try_conversational_reply
    from core.ai_provider import chat_with_fallbacks

    quick = try_conversational_reply(message)
    if quick:
        log_chat_context(
            user_message=message,
            system_prompt=SENTINEL_SYSTEM_PROMPT,
            route="conversational",
            provider="canned",
        )
        return quick
    result = chat_with_fallbacks(message, system=SENTINEL_SYSTEM_PROMPT)
    return result.get("text") or ""


# NOTE: the legacy `_WORKER_RESPONSES`, `_CONVERSATIONAL_CANNED`, and
# `_canned_response()` helpers were removed in the 2026 audit. Every chat
# turn now routes through `workers.sentinel.capability_router.route_message`
# and the LLM — there is no hardcoded chat fallback.


@app.route('/api/chat', methods=['POST'])
@require_auth
def api_chat():
    """Route a chat message to the correct worker and return a response string.

    Accepts: { "message": "..." }
    Returns: { "worker": "...", "response": "...", "intent": {...} }
    """
    global _pending_godot_install
    try:
        blocked = check_access()
        if blocked:
            return jsonify(blocked), 402

        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message required"}), 400

        from core.model_runtime import get_model_runtime
        from core.chat.context import (
            log_chat_context,
            should_attach_memory,
            try_conversational_reply,
        )

        _chat_rt = get_model_runtime()
        if not _chat_rt.is_ready():
            threading.Thread(target=lambda: _chat_rt.heal(max_retries=1), daemon=True).start()

        _conversational = try_conversational_reply(message)
        if _conversational:
            try:
                log_chat_context(
                    user_message=message,
                    system_prompt=SENTINEL_SYSTEM_PROMPT,
                    route="conversational",
                    provider="canned",
                )
            except Exception as _log_err:
                logger.debug("chat context log skipped: %s", _log_err)
            _save_chat_exchange(message, _conversational)
            return jsonify({
                "status": "ok",
                "worker": "general",
                "response": _conversational,
                "routed": True,
                "provider": "canned",
            })

        # ── Godot install confirmation (chat "yes" after launch prompt) ───────────
        _msg_lower = message.lower().strip()
        _godot_confirm = _pending_godot_install and any(
            w in _msg_lower for w in ('yes', 'y', 'install', 'install godot', 'ok', 'okay', 'sure', 'go ahead')
        )
        if _godot_confirm:
            try:
                from builders.runtime.godot_runtime import install_godot
                from workers.artifacts.artifact_registry import launch_latest
                log("Installing Godot (chat confirmation)…", "info", "forge")
                inst = install_godot(log_fn=lambda m, lvl="info": log(m, lvl, "forge"))
                _pending_godot_install = False
                if not inst.get("ok"):
                    _resp = f"✗ Godot install failed: {inst.get('error', 'unknown')}"
                    _save_chat_exchange(message, _resp)
                    return jsonify({"status": "ok", "worker": "forge", "response": _resp, "routed": True})
                launch = launch_latest()
                if launch.get("ok"):
                    _resp = f"✓ Godot installed. {launch.get('message', 'Launch successful')}"
                else:
                    _resp = f"Godot installed but launch failed: {launch.get('error', '?')}"
                _save_chat_exchange(message, _resp)
                return jsonify({"status": "ok", "worker": "forge", "response": _resp, "routed": True})
            except Exception as _godot_chat_err:
                _pending_godot_install = False
                logger.exception("Godot chat install failed: %s", _godot_chat_err)

        # ── APPROVE / DENY pending task — check FIRST before any routing ─────────
        _pending = _get_pending_task()
        if _pending:
            if any(w in _msg_lower for w in _APPROVE_WORDS):
                _clear_pending_task()
                log(f"Task approved: {_pending.get('description', '')[:80]}", 'info', 'system')
                _task_type = _pending.get('type', '')
                if _task_type == 'build':
                    _task_desc = _pending.get('description', 'the task')
                    _output_dir = _pending.get('output_dir')
                    def _run_approved_build(_desc=_task_desc, _odir=_output_dir):
                        from workers.task_manager import TaskContext
                        with TaskContext(f"Build {_desc[:60]}", source="forge") as ctx:
                            try:
                                forge_result, art = _run_forge_build(
                                    _desc, _odir, sentinel_task_id=ctx.task_id,
                                )
                                ctx.complete(
                                    result_summary=(
                                        f"{forge_result.builder} — "
                                        f"{forge_result.project_type} — "
                                        f"{forge_result.verification.message if forge_result.verification else 'done'}"
                                    ),
                                    artifact_id=art.get('id'),
                                )
                                log(f"Build complete: {_desc[:60]} via {forge_result.builder}", 'info', 'forge')
                            except Exception as _be:
                                ctx.fail(str(_be))
                                log(f"Build error: {_be}", 'error', 'forge')
                    threading.Thread(target=_run_approved_build, daemon=True).start()
                    _resp = (
                        f"✓ Approved. Building **{_task_desc}** now. "
                        f"Watch the LOG tab → **BUILDER** filter for live stages."
                    )
                else:
                    _resp = f"✓ Approved. Working on it now."
                _save_chat_exchange(message, _resp)
                return jsonify({"status": "ok", "worker": "aider", "response": _resp, "routed": True})

            if any(w in _msg_lower for w in _DENY_WORDS):
                _task_desc = _pending.get('description', 'the task')
                _clear_pending_task()
                log(f"Task denied: {_task_desc[:80]}", 'info', 'system')
                _resp = f"Cancelled. Let me know if you'd like to try something different."
                _save_chat_exchange(message, _resp)
                return jsonify({"status": "ok", "worker": "system", "response": _resp, "routed": True})
        # ── END APPROVE/DENY ─────────────────────────────────────────────────────

        # ── Active work status (build > guardian > earn) ─────────────────────────
        try:
            from workers.active_work import get_active_work_response, is_status_query
            if is_status_query(message):
                active = get_active_work_response()
                if active:
                    _resp = active
                else:
                    _resp = (
                        "No active build, Guardian scan, or Earn analysis right now. "
                        "Start a build or check the **Tasks** tab for recent work."
                    )
                _save_chat_exchange(message, _resp)
                return jsonify({"status": "ok", "worker": "system", "response": _resp, "routed": True})
        except Exception as _st_err:
            logger.debug("Status query handler failed: %s", _st_err)

        _memory_context = ""
        if memory_v2 is not None:
            try:
                if should_attach_memory(message):
                    _memory_context = memory_v2.get_context_for_prompt(
                        message, max_tokens=800, chat_mode=True,
                    )
                    if _memory_context:
                        log(f"Memory context attached: {_memory_context[:100]}...", 'info', 'memory')
                if should_attach_memory(message):
                    memory_v2.remember(message, source="user", topic=message[:80])
            except Exception as _mem_err:
                logger.debug("Memory context lookup failed: %s", _mem_err)
        # Log user message to chat source (visible in Log panel CHAT filter)
        log(f"USER: {message}", 'info', 'chat')
        # Save to in-memory chat session
        with _chat_session_lock:
            _chat_session.append({'role': 'user', 'content': message, 'timestamp': datetime.now().isoformat()})
            if len(_chat_session) > 200:
                del _chat_session[:-200]

        from workers.orchestration.task_decomposer import get_decomposer, is_conversational_input

        lower = message.lower()

        # ── Launch intent — "launch it", "run it", "open it", "start it" ─────────
        _launch_kw = ('launch it', 'run it', 'open it', 'start it', 'launch the', 'run the',
                      'open the', 'start the', 'execute it', 'launch calculator', 'run calculator',
                      'launch app', 'run app', 'run program', 'launch program')
        if any(kw in lower for kw in _launch_kw):
            try:
                from workers.artifacts.artifact_registry import (
                    get_artifact_by_task, get_latest_artifact, launch_artifact as _launch_art,
                )
                _task_hint = ''
                for _phrase in ('launch ', 'run ', 'open ', 'start ', 'execute '):
                    if _phrase in lower:
                        _candidate = lower.split(_phrase, 1)[-1].strip().rstrip('.')
                        if _candidate and _candidate not in ('it', 'the', 'app', 'program', 'this'):
                            _task_hint = _candidate
                            break
                artifact = (get_artifact_by_task(_task_hint) if _task_hint else None) or get_latest_artifact()
                _launch_result: dict = {}
                if artifact:
                    _launch_result = _launch_art(artifact)
                    _cmd = _launch_result.get('command') or artifact.get('launch_command', '')
                    if _launch_result.get('ok'):
                        _task_name = artifact.get('task', 'application')
                        _resp = (
                            f"✓ Launching {_task_name}\n\n"
                            f"Builder: {artifact.get('builder_used') or 'unknown'}\n"
                            f"Command: `{_cmd}`\n\n"
                            f"{_launch_result.get('message', 'Launch successful')}"
                        )
                        log(f"[ARTIFACT] Launched via chat: {_task_name}", 'success', 'forge')
                    elif _launch_result.get("needs_install"):
                        _resp = _launch_result.get("error", "Godot required. Install now?")
                        log("[ARTIFACT] Launch blocked — Godot install required", 'warning', 'forge')
                    else:
                        _resp = f"✗ Launch failed: {_launch_result.get('error', 'unknown error')}"
                        log(f"[ARTIFACT] Launch failed: {_launch_result.get('error')}", 'error', 'forge')
                else:
                    _resp = "No recent builds found. Build something first, then ask me to launch it."
                    log("[ARTIFACT] No artifacts registered — cannot launch", 'warning', 'forge')
                _save_chat_exchange(message, _resp)
                out = {"status": "ok", "worker": "forge", "response": _resp, "routed": True}
                if artifact and _launch_result.get("needs_install"):
                    out["launch"] = _launch_result
                return jsonify(out)
            except Exception as _launch_err:
                logger.warning("Launch intent handler failed: %s", _launch_err)

        # ── Purchase intent — find product, stage approval ───────────────────────
        _buy_kw = ['buy ', 'purchase ', 'order me ', 'i want to buy', 'i want to order',
                   'add to cart', 'get me a ', 'pick up a ', 'grab me a ']
        if any(kw in lower for kw in _buy_kw):
            try:
                from workers.payments.purchase_executor import PurchaseExecutor
                staged = run_async(PurchaseExecutor().find_and_stage(message), timeout=30.0)
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
                from workers.web.sentinel_web_client import query_web, is_available

                async def _availability_then_query():
                    # One coroutine, one loop trip. Eliminates the race window
                    # between is_available() and query_web() and avoids paying
                    # for two fresh event loops per chat turn.
                    if not await is_available():
                        return None
                    return await query_web(message)

                web_result = run_async(_availability_then_query(), timeout=30.0)
                if web_result is None:
                    return jsonify({"status": "ok", "worker": "general",
                                    "response": "SentinelWeb is offline. Start it with: "
                                                "cd C:\\Users\\pgg12\\Desktop\\SentinelWeb && venv\\Scripts\\python main.py",
                                    "routed": True})
                web_ans = web_result.get("answer") or web_result.get("result")
                if web_ans and not web_result.get("error"):
                    src = web_result.get("source_url", "")
                    log_chat_context(
                        user_message=message,
                        tools_context=f"sentinel_web; source_url={src}",
                        route="sentinel_web",
                    )
                    response = web_ans + (f"\n\nSource: {src}" if src else "")
                    _save_chat_exchange(message, response)
                    return jsonify({"status": "ok", "worker": "sentinel_web",
                                    "response": response, "routed": True,
                                    "source_url": src, "confidence": web_result.get("confidence")})
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
            _save_chat_exchange(message, response)
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['bitcoin', 'btc price', 'bitcoin price']):
            btc = get_crypto_price("bitcoin")
            if 'error' not in btc:
                direction = "▲" if btc['change_24h'] > 0 else "▼"
                response = f"Bitcoin: ${btc['price']:,.2f} {direction} {abs(btc['change_24h'])}% in the last 24h."
            else:
                response = "Could not fetch Bitcoin price right now."
            _save_chat_exchange(message, response)
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['ethereum', 'eth price', 'ethereum price']):
            eth = get_crypto_price("ethereum")
            if 'error' not in eth:
                direction = "▲" if eth['change_24h'] > 0 else "▼"
                response = f"Ethereum: ${eth['price']:,.2f} {direction} {abs(eth['change_24h'])}% in the last 24h."
            else:
                response = "Could not fetch Ethereum price right now."
            _save_chat_exchange(message, response)
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['stock price', 'spy', 'qqq', 'nasdaq', 's&p', 'market today']):
            spy_q = get_stock_price("SPY")
            qqq_q = get_stock_price("QQQ")
            if 'error' not in spy_q:
                response = (f"Markets: SPY ${spy_q['price']} ({'+' if spy_q['change_pct'] > 0 else ''}{spy_q['change_pct']}%), "
                            f"QQQ ${qqq_q['price']} ({'+' if qqq_q['change_pct'] > 0 else ''}{qqq_q['change_pct']}%)")
            else:
                response = "Could not fetch market data right now."
            _save_chat_exchange(message, response)
            return jsonify({"status": "ok", "worker": "general", "response": response, "routed": True})

        if any(w in lower for w in ['news', 'headlines', "what's happening", 'latest news']):
            headlines = get_news_headlines(5)
            if headlines:
                response = "Latest headlines:\n" + "\n".join([f"• {h['title']}" for h in headlines])
            else:
                response = "Could not fetch news right now."
            _save_chat_exchange(message, response)
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
            _save_chat_exchange(message, response)
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
                _task_id = _store_pending_task({
                    'type': 'build',
                    'description': message,
                    'plan': plan_dict,
                    'files': plan.files,
                    'created_at': datetime.now().isoformat(),
                })
                _save_chat_exchange(message, resp_text)
                return jsonify({
                    "status": "ok", "worker": "consultation",
                    "response": resp_text,
                    "plan": plan_dict, "plan_id": plan.id,
                    "pending_task_id": _task_id,
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
                _resp_text = f"[Source: {src_label}]\n\n{result.answer}"
                _save_chat_exchange(message, _resp_text)
                return jsonify({
                    "status": "ok", "worker": "consultation",
                    "response": _resp_text,
                    "consultation_source": result.source,
                    "routed": True,
                })
            except Exception as _cons_err:
                logger.debug("Consultation guidance failed (%s) — falling through", _cons_err)

        # Unified intent router — Sentinel voice, internal engines (extend keyword routing).
        try:
            from workers.sentinel.capability_router import route_message
            _route = route_message(message)
        except Exception as _ur_err:
            logger.debug("unified_router failed: %s", _ur_err)
            _route = None

        if _route and _route.internal_engine == "guardian" and _route.execute:
            def _run_guardian_from_chat(_msg=message, _target=_route.extracted_target):
                from workers.task_manager import TaskContext
                title = f"Guardian: {_target or _msg[:50]}"
                with TaskContext(title, source="guardian") as ctx:
                    try:
                        brain = get_guardian_brain()
                        q = _msg if not _target else f"Perform security assessment on {_target}. {_msg}"
                        result = brain.chat(q)
                        summary = str(result.get("response", ""))[:500]
                        ctx.complete(result_summary=summary)
                    except Exception as exc:
                        ctx.fail(str(exc))
            threading.Thread(target=_run_guardian_from_chat, daemon=True).start()
            _gresp = (
                f"Starting security assessment"
                + (f" on **{_route.extracted_target}**" if _route.extracted_target else "")
                + ". Track progress in **Tasks** and the Guardian panel."
            )
            _save_chat_exchange(message, _gresp)
            return jsonify({
                "status": "ok", "worker": "sentinel", "internal_engine": "guardian",
                "response": _gresp, "routed": True,
            })

        if _route and _route.internal_engine == "earn_research" and _route.execute:
            def _run_earn_research(_prog=_route.extracted_target):
                from workers.earn.research.pipeline import run_research_pipeline
                run_research_pipeline(
                    {"title": _prog, "handle": _prog}, socketio=socketio, background=True,
                )
            threading.Thread(target=_run_earn_research, daemon=True).start()
            _eresp = f"Research pipeline started for **{_route.extracted_target}**. See **Tasks** and the Earn tab."
            _save_chat_exchange(message, _eresp)
            return jsonify({
                "status": "ok", "worker": "sentinel", "internal_engine": "earn_research",
                "response": _eresp, "routed": True,
            })

        if _route and _route.internal_engine == "learning" and _route.execute:
            try:
                from core.learning.learning_engine import get_learning_engine
                lr = get_learning_engine().handle_unknown(message)
                _save_chat_exchange(message, lr.get("response", ""))
                return jsonify({
                    "status": "ok", "worker": "sentinel", "internal_engine": "learning",
                    "response": lr.get("response", ""), "routed": True,
                })
            except Exception as _le:
                logger.debug("learning engine: %s", _le)

        if _route and _route.internal_engine == "memory" and _route.execute:
            if memory_v2 is not None:
                try:
                    hits = memory_v2.recall(message, limit=5)
                    if hits:
                        _mresp = "Here's what I remember:\n\n" + "\n".join(
                            f"- {(getattr(h, 'content', None) or '')[:200]}" for h in hits[:5]
                        )
                    else:
                        _mresp = "No matching memories yet. I'll remember what you tell me in this chat."
                    _save_chat_exchange(message, _mresp)
                    return jsonify({"status": "ok", "worker": "sentinel", "response": _mresp, "routed": True})
                except Exception as _mr:
                    logger.debug("memory recall: %s", _mr)

        # Single source of truth: the capability_router decision already
        # computed at the top of this handler (`_route`) selects the internal
        # engine. No inline keyword block, no canned per-worker strings —
        # if the engine doesn't have a structured handler above, fall through
        # to the LLM.

        engine = (_route.internal_engine if _route else "general")

        # Forge — show the structured Build Plan and stage the approval. The
        # plan text is parameterized (not a canned response): it describes the
        # routing decision the user is about to approve.
        if engine == "forge":
            from builders.router import classify_build, engine_for_route, stack_for_route
            _bt = classify_build(message)
            _stack = ", ".join(stack_for_route(_bt))
            _plan_text = (
                f"📋 Build Plan\n\n"
                f"Task: {message}\n"
                f"Route: **{_bt.value}**\n"
                f"Engine: **{engine_for_route(_bt)}**\n"
                f"Stack: {_stack}\n\n"
                f"Stages: Planning → Dependencies → Generate → Build → Verify → Launch → Complete\n\n"
                f"Reply APPROVE to start building, or DENY to cancel."
            )
            _task_id = _store_pending_task({
                'type': 'build',
                'description': message,
                'created_at': datetime.now().isoformat(),
            })
            _save_chat_exchange(message, _plan_text)
            return jsonify({
                "status": "ok",
                "worker": "forge",
                "response": _plan_text,
                "pending_task_id": _task_id,
                "awaiting_approval": True,
                "routed": True,
            })

        # Everything else (earn, market, home, general) — route through the
        # real LLM. No canned per-worker strings, no canned conversational
        # replies. If the model is unreachable we surface that to the user
        # instead of papering over it with hardcoded chat.
        from core.ai_provider import chat_with_fallbacks

        _tools_context = ""
        if _route:
            _tools_context = (
                f"internal_engine={_route.internal_engine}; "
                f"reason={_route.reason}; confidence={_route.confidence}"
            )
        log_chat_context(
            user_message=message,
            memory_context=_memory_context,
            system_prompt=SENTINEL_SYSTEM_PROMPT,
            tools_context=_tools_context,
            route=engine,
        )
        chat_result = chat_with_fallbacks(
            message,
            system=SENTINEL_SYSTEM_PROMPT,
            memory_context=_memory_context,
            tools_context=_tools_context,
        )
        response_text = chat_result.get("text") or "I'm here. What would you like to do?"
        status_code = 200

        log_chat_context(
            user_message=message,
            memory_context=_memory_context,
            system_prompt=SENTINEL_SYSTEM_PROMPT,
            tools_context=_tools_context,
            route=engine,
            provider=chat_result.get("source", "unknown"),
            extra={"degraded": chat_result.get("degraded")},
        )
        _save_chat_exchange(message, response_text)
        return jsonify({
            "status": "ok",
            "worker": engine,
            "response": response_text,
            "intent": {"intent": engine},
            "routed": True,
            "degraded": bool(chat_result.get("degraded")),
            "provider": chat_result.get("source", "unknown"),
            "model_ready": _chat_rt.is_ready(),
        }), status_code
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
                engine.analyze_bounty(
                    job_title,
                    job_url,
                    job_scope,
                    program_data=job_data,
                )
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


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel Vision — visual understanding + browser/desktop/provider operator
# ══════════════════════════════════════════════════════════════════════════════

def _vision():
    from core.sentinelvision import get_vision_engine
    return get_vision_engine(socketio=socketio)


@app.route('/api/sentinelvision/status', methods=['GET'])
@app.route('/api/sentinelscrub/status', methods=['GET'])
def api_sentinelvision_status():
    try:
        engine = _vision()
        return jsonify({
            "status": "ok",
            "enabled": True,
            "subsystem": "sentinel_vision",
            "browser": engine.operators.browser.available,
            "desktop_platform": engine.operators.desktop.platform,
            "providers": __import__("core.sentinelvision.providers.registry", fromlist=["list_providers"]).list_providers(),
        })
    except Exception as e:
        return jsonify({"status": "error", "enabled": False, "error": str(e)}), 200


@app.route('/api/sentinelvision/goals', methods=['GET', 'POST'])
@app.route('/api/sentinelscrub/goals', methods=['GET', 'POST'])
def api_sentinelvision_goals():
    try:
        engine = _vision()
        if request.method == 'POST':
            data = request.get_json() or {}
            objective = (data.get("objective") or data.get("message") or "").strip()
            if not objective:
                return jsonify({"error": "objective required"}), 400
            goal = engine.submit_goal(objective, provider_id=data.get("provider_id"))
            return jsonify({"status": "ok", "goal": goal.to_dict()})
        goals = [g.to_dict() for g in engine.goals.list_goals()]
        return jsonify({"status": "ok", "goals": goals})
    except Exception as e:
        logger.exception("sentinelvision goals")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/goals/<goal_id>', methods=['GET'])
@app.route('/api/sentinelscrub/goals/<goal_id>', methods=['GET'])
def api_sentinelvision_goal(goal_id):
    try:
        engine = _vision()
        goal = engine.goals.get(goal_id)
        if not goal:
            return jsonify({"error": "not found"}), 404
        pending = [a.to_dict() for a in engine.approval.list_pending(goal_id)]
        return jsonify({
            "status": "ok",
            "goal": goal.to_dict(),
            "feed": engine.goals.get_feed(goal_id),
            "pending_approvals": pending,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/approvals', methods=['GET'])
@app.route('/api/sentinelscrub/approvals', methods=['GET'])
def api_sentinelvision_approvals():
    try:
        engine = _vision()
        pending = [a.to_dict() for a in engine.approval.list_pending()]
        return jsonify({"status": "ok", "approvals": pending})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/approvals/<approval_id>/resolve', methods=['POST'])
@app.route('/api/sentinelscrub/approvals/<approval_id>/resolve', methods=['POST'])
def api_sentinelvision_approval_resolve(approval_id):
    try:
        engine = _vision()
        data = request.get_json() or {}
        approved = bool(data.get("approved", False))
        trust = bool(data.get("trust_provider", False))
        req = engine.approval.resolve(approval_id, approved)
        if not req:
            return jsonify({"error": "approval not found or already resolved"}), 404
        if trust:
            engine.approval.set_trusted_provider(req.provider_id, True)
        if approved:
            engine.resume_after_approval(approval_id)
        return jsonify({"status": "ok", "approval": req.to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/vault/providers', methods=['GET'])
@app.route('/api/sentinelscrub/vault/providers', methods=['GET'])
def api_sentinelvision_vault_list():
    try:
        engine = _vision()
        return jsonify({"status": "ok", "providers": engine.vault.list_providers()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/vault/register', methods=['POST'])
@app.route('/api/sentinelscrub/vault/register', methods=['POST'])
def api_sentinelvision_vault_register():
    """Register credentials — values never returned in response."""
    try:
        engine = _vision()
        data = request.get_json() or {}
        provider_id = (data.get("provider_id") or "").strip()
        fields = data.get("fields") or {}
        if not provider_id or not fields:
            return jsonify({"error": "provider_id and fields required"}), 400
        result = engine.vault.register_provider_account(
            provider_id, fields, label=data.get("label"),
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/audit', methods=['GET'])
@app.route('/api/sentinelscrub/audit', methods=['GET'])
def api_sentinelvision_audit():
    try:
        from core.sentinelvision.audit import list_audit
        goal_id = request.args.get("goal_id")
        limit = int(request.args.get("limit", 100))
        return jsonify({"status": "ok", "entries": list_audit(limit=limit, goal_id=goal_id)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/metrics', methods=['GET'])
@app.route('/api/sentinelscrub/metrics', methods=['GET'])
def api_sentinelvision_metrics():
    try:
        engine = _vision()
        return jsonify({"status": "ok", "metrics": engine.metrics.summary()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/playbooks', methods=['GET'])
@app.route('/api/sentinelscrub/playbooks', methods=['GET'])
def api_sentinelvision_playbooks():
    try:
        from core.sentinelvision.playbooks.recorder import list_playbooks
        return jsonify({"status": "ok", "playbooks": list_playbooks()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/workflows', methods=['GET'])
@app.route('/api/sentinelscrub/workflows', methods=['GET'])
def api_sentinelvision_workflows():
    try:
        from core.sentinelvision.workflows.workflow_library import WorkflowLibrary
        return jsonify({"status": "ok", "workflows": WorkflowLibrary().list_templates()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/onboard', methods=['POST'])
@app.route('/api/sentinelscrub/onboard', methods=['POST'])
def api_sentinelvision_onboard():
    try:
        engine = _vision()
        data = request.get_json() or {}
        provider_id = (data.get("provider_id") or "").strip()
        if not provider_id:
            objective = (data.get("objective") or data.get("message") or "").strip()
            provider_id = engine.onboarding.resolve_onboarding_objective(objective) or ""
        if not provider_id:
            return jsonify({"error": "provider_id or recognizable objective required"}), 400
        result = engine.onboarding.onboard_provider(
            provider_id,
            objective=data.get("objective"),
            credentials=data.get("fields") or data.get("credentials"),
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.exception("sentinelvision onboard")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/repair-memory', methods=['GET'])
@app.route('/api/sentinelscrub/repair-memory', methods=['GET'])
def api_sentinelvision_repair_memory():
    try:
        from core.sentinelvision.self_correction.repair_memory import RepairMemoryStore
        return jsonify({"status": "ok", "patterns": RepairMemoryStore().list_top(30)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/sentinelvision/providers/health', methods=['GET'])
@app.route('/api/sentinelscrub/providers/health', methods=['GET'])
def api_sentinelvision_providers_health():
    try:
        from core.sentinelvision.providers.registry import list_providers
        from core.sentinelvision.providers.workflows import get_workflow_runner
        runner = get_workflow_runner()
        health = [runner.health_check(p["provider_id"]) for p in list_providers()]
        return jsonify({"status": "ok", "providers": health})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# Memory 2.0 / Missions / Guardian monitor / Updates / Release
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/memory2/health', methods=['GET'])
def api_memory2_health():
    try:
        from core.memory2 import get_memory2_engine
        return jsonify({"status": "ok", "health": get_memory2_engine().health()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/memory2/retrieve', methods=['POST'])
def api_memory2_retrieve():
    try:
        from core.memory2 import get_memory2_engine
        data = request.get_json() or {}
        q = (data.get("query") or "").strip()
        if not q:
            return jsonify({"error": "query required"}), 400
        results = get_memory2_engine().retrieve(
            q,
            memory_type=data.get("memory_type"),
            project_id=data.get("project_id"),
            limit=int(data.get("limit", 20)),
        )
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/memory2/summarize', methods=['GET'])
def api_memory2_summarize():
    try:
        from core.memory2 import get_memory2_engine
        mt = request.args.get("memory_type")
        return jsonify({"status": "ok", "summary": get_memory2_engine().summarize(mt)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/memory2/consolidate', methods=['POST'])
def api_memory2_consolidate():
    try:
        from core.memory2 import get_memory2_engine
        data = request.get_json() or {}
        return jsonify({"status": "ok", **get_memory2_engine().consolidate(data.get("memory_type"))})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/memory2/cleanup', methods=['POST'])
def api_memory2_cleanup():
    try:
        from core.memory2 import get_memory2_engine
        data = request.get_json() or {}
        return jsonify({"status": "ok", **get_memory2_engine().cleanup(dry_run=bool(data.get("dry_run")))})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/missions', methods=['GET', 'POST'])
def api_missions():
    try:
        from core.missions import get_mission_engine
        eng = get_mission_engine()
        if request.method == 'POST':
            data = request.get_json() or {}
            title = (data.get("title") or data.get("goal") or "").strip()
            if not title:
                return jsonify({"error": "title required"}), 400
            m = eng.create_mission(title, goal=data.get("goal"), dependencies=data.get("dependencies"))
            return jsonify({"status": "ok", "mission": m})
        status = request.args.get("status")
        return jsonify({"status": "ok", "missions": eng.list_missions(status=status)})
    except Exception as e:
        logger.exception("missions")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/missions/<mission_id>', methods=['GET', 'PATCH'])
def api_mission(mission_id):
    try:
        from core.missions import get_mission_engine
        eng = get_mission_engine()
        if request.method == 'PATCH':
            data = request.get_json() or {}
            m = eng.update_mission(mission_id, **data)
            if not m:
                return jsonify({"error": "not found"}), 404
            return jsonify({"status": "ok", "mission": m})
        m = eng.get_mission(mission_id)
        if not m:
            return jsonify({"error": "not found"}), 404
        return jsonify({"status": "ok", "mission": m})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/guardian/dashboard', methods=['GET'])
def api_guardian_dashboard():
    try:
        from workers.guardian.system_monitor import get_guardian_monitor
        return jsonify({"status": "ok", **get_guardian_monitor().dashboard()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/guardian/alerts', methods=['GET'])
def api_guardian_alerts():
    try:
        from workers.guardian.system_monitor import get_guardian_monitor
        limit = int(request.args.get("limit", 20))
        return jsonify({"status": "ok", "alerts": get_guardian_monitor().get_alerts(limit)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/version', methods=['GET'])
def api_version():
    try:
        from core.release import get_release_manager
        return jsonify({"status": "ok", **get_release_manager().version()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/status', methods=['GET'])
def api_updates_status():
    try:
        from core.updater import get_auto_updater
        return jsonify({"status": "ok", **get_auto_updater().status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/check', methods=['POST'])
def api_updates_check():
    try:
        from core.updater import get_auto_updater
        return jsonify({"status": "ok", **get_auto_updater().check_for_updates()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/channel', methods=['POST'])
def api_updates_channel():
    try:
        from core.updater import get_auto_updater
        data = request.get_json() or {}
        return jsonify(get_auto_updater().set_channel((data.get("channel") or "beta").strip()))
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/download', methods=['POST'])
def api_updates_download():
    try:
        from core.updater import get_auto_updater
        return jsonify(get_auto_updater().download_update(background=True))
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/rollback', methods=['GET'])
def api_updates_rollback():
    try:
        from core.updater import get_auto_updater
        return jsonify({"status": "ok", **get_auto_updater().rollback_info()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/diagnostics', methods=['GET'])
def api_updates_diagnostics():
    try:
        from core.updater import get_auto_updater
        return jsonify({"status": "ok", **get_auto_updater().diagnostics()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/install', methods=['POST'])
def api_updates_install():
    try:
        from core.updater import get_auto_updater
        return jsonify(get_auto_updater().install_pending())
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/rollback/execute', methods=['POST'])
def api_updates_rollback_execute():
    try:
        from core.updater import get_auto_updater
        u = get_auto_updater()
        triggered = u.trigger_rollback()
        if not triggered.get("ok"):
            return jsonify({"status": "error", **triggered}), 400
        result = u.execute_rollback()
        code = 200 if result.get("ok") else 500
        return jsonify({"status": "ok" if result.get("ok") else "error", **result}), code
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/electron-event', methods=['POST'])
def api_updates_electron_event():
    try:
        from core.updater import get_auto_updater
        data = request.get_json() or {}
        get_auto_updater().record_electron_event(
            (data.get("phase") or "unknown").strip(),
            data.get("detail"),
        )
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/updates/manifest', methods=['GET', 'POST'])
def api_updates_manifest():
    try:
        from core.release import get_release_manager
        mgr = get_release_manager()
        if request.method == 'POST':
            data = request.get_json() or {}
            m = mgr.generate_update_manifest(
                channel=data.get("channel", "beta"),
                minimum_supported_version=data.get("minimum_supported_version", "1.0.0"),
                force_update=bool(data.get("force_update")),
                kill_switch=bool(data.get("kill_switch")),
                updates_disabled=bool(data.get("updates_disabled")),
            )
            return jsonify({"status": "ok", "manifest": m})
        m = mgr.load_update_manifest() or mgr.generate_update_manifest()
        return jsonify({"status": "ok", "manifest": m})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/release/manifest', methods=['GET', 'POST'])
def api_release_manifest():
    try:
        from core.release import get_release_manager
        mgr = get_release_manager()
        if request.method == 'POST':
            ch = (request.get_json() or {}).get("channel", "beta")
            return jsonify({"status": "ok", "manifest": mgr.generate_manifest(channel=ch)})
        m = mgr.load_manifest() or mgr.generate_manifest()
        return jsonify({"status": "ok", "manifest": m})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/release/verify', methods=['GET'])
def api_release_verify():
    try:
        from core.release import get_release_manager
        return jsonify({"status": "ok", **get_release_manager().verify_build()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/release/changelog', methods=['GET'])
def api_release_changelog():
    try:
        from core.release import get_release_manager
        return jsonify({"status": "ok", **get_release_manager().changelog()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/dependencies/scan', methods=['POST'])
def api_dependencies_scan():
    try:
        from core.dependency_manager import get_dependency_manager
        return jsonify({"status": "ok", **get_dependency_manager().scan_system()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/dependencies', methods=['GET'])
def api_dependencies_list():
    try:
        from core.dependency_manager import get_dependency_manager
        return jsonify({"status": "ok", "components": get_dependency_manager().list_components()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/dependencies/install', methods=['POST'])
def api_dependencies_install():
    try:
        from core.dependency_manager import get_dependency_manager
        data = request.get_json() or {}
        cid = (data.get("component_id") or "").strip()
        mgr = get_dependency_manager()
        if cid:
            return jsonify({"status": "ok", **mgr.install_component(cid)})
        return jsonify({"status": "ok", **mgr.install_all_required()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/dependencies/repair', methods=['POST'])
def api_dependencies_repair():
    try:
        from core.dependency_manager import get_dependency_manager
        return jsonify({"status": "ok", **get_dependency_manager().repair_failed()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models/recommend', methods=['GET'])
def api_models_recommend():
    try:
        from core.model_manager import get_model_manager
        return jsonify({"status": "ok", **get_model_manager().recommend()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models', methods=['GET'])
def api_models_list():
    try:
        from core.model_manager import get_model_manager
        return jsonify({"status": "ok", "models": get_model_manager().list_models()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models/install-recommended', methods=['POST'])
def api_models_install_recommended():
    try:
        from core.model_manager import get_model_manager
        return jsonify({"status": "ok", **get_model_manager().install_recommended()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models/pull', methods=['POST'])
def api_models_pull():
    try:
        from core.model_manager import get_model_manager
        data = request.get_json() or {}
        name = (data.get("model") or data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "model required"}), 400
        return jsonify({"status": "ok", **get_model_manager().pull_model(name)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models/remove', methods=['POST'])
def api_models_remove():
    try:
        from core.model_manager import get_model_manager
        data = request.get_json() or {}
        name = (data.get("model") or data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "model required"}), 400
        return jsonify({"status": "ok", **get_model_manager().remove_model(name)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/onboarding/status', methods=['GET'])
def api_onboarding_status():
    try:
        from core.onboarding import get_first_launch
        return jsonify({"status": "ok", **get_first_launch().status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/onboarding/step', methods=['POST'])
def api_onboarding_step():
    try:
        from core.onboarding import get_first_launch
        data = request.get_json() or {}
        fl = get_first_launch()
        if data.get("run_all"):
            return jsonify({"status": "ok", **fl.run_all()})
        if data.get("retry") and data.get("step"):
            return jsonify({"status": "ok", **fl.retry_step(data["step"])})
        return jsonify({"status": "ok", **fl.run_step(data.get("step"))})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/models/readiness', methods=['GET'])
def api_models_readiness():
    try:
        from core.model_runtime import get_model_runtime
        return jsonify({"status": "ok", **get_model_runtime().readiness_quick()})
    except Exception as e:
        return jsonify({"status": "ok", "allow_chat": True, "ready": False, "degraded": True}), 200


@app.route('/api/ai/status', methods=['GET'])
def api_ai_status():
    try:
        from core.ai_provider import get_ai_status
        return jsonify({"status": "ok", **get_ai_status()})
    except Exception as e:
        logger.exception("api_ai_status")
        return jsonify({
            "status": "ok",
            "ollama_running": False,
            "model_installed": False,
            "model_loaded": False,
            "provider_ready": False,
            "download_progress": 0,
            "allow_chat": True,
        }), 200


@app.route('/api/onboarding/progress', methods=['GET'])
def api_onboarding_progress():
    try:
        from core.onboarding.pipeline import get_onboarding_pipeline
        from core.model_runtime import get_model_runtime
        return jsonify({
            "status": "ok",
            "progress": get_onboarding_pipeline().progress(),
            "readiness": get_model_runtime().readiness_quick(),
            "allow_chat": True,
        })
    except Exception as e:
        return jsonify({"status": "ok", "allow_chat": True, "progress": {"percent": 0, "message": "Starting…"}}), 200


@app.route('/api/models/heal', methods=['POST'])
def api_models_heal():
    try:
        from core.model_runtime import get_model_runtime
        data = request.get_json() or {}
        retries = int(data.get("max_retries", 2))
        return jsonify({"status": "ok", **get_model_runtime().heal(max_retries=retries)})
    except Exception as e:
        return jsonify({"status": "error", "user_message": "Sentinel is restoring the local AI service. Please wait."}), 500


@app.route('/api/models/pull-status', methods=['GET'])
def api_models_pull_status():
    try:
        from core.model_runtime import get_model_runtime
        rt = get_model_runtime()
        return jsonify({
            "status": "ok",
            "phase": rt._state.get("phase"),
            "pull": rt._state.get("pull") or {},
            "install": rt._state.get("install") or {},
            "readiness": rt.readiness(),
        })
    except Exception as e:
        return jsonify({"status": "error", "user_message": "Download status is temporarily unavailable."}), 500


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
        from workers.guardian.tools.tool_registry import get_tool_diagnostics
        payload = get_guardian_brain().get_status()
        payload["tool_diagnostics"] = get_tool_diagnostics()
        return jsonify({"status": "ok", **payload})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/tools/status', methods=['GET'])
@app.route('/guardian/tools/status', methods=['GET'])
def api_guardian_tools_status():
    """Guardian Tool Status — registry + legacy diagnostics."""
    try:
        from workers.guardian.tools.tool_registry import get_tool_diagnostics
        from workers.guardian.guardian_tool_registry_store import get_registry_list
        tools = get_registry_list()
        if not tools:
            tools = get_tool_diagnostics()
        else:
            for t in tools:
                t.setdefault("installed", t.get("install_status") == "installed")
                t.setdefault("label", (t.get("name") or "").title())
                t.setdefault("status_line", "✓ Installed" if t.get("installed") else "✗ Missing")
        return jsonify({"status": "ok", "tools": tools, "registry": tools})
    except Exception as e:
        logger.error("Guardian tools status error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e), "tools": []}), 200


@app.route('/api/build/status', methods=['GET'])
def api_build_status():
    """Active forge build progress for status commands and HUD."""
    try:
        from builders.build_tracker import get_active_build
        b = get_active_build()
        if b:
            return jsonify({"status": "ok", "active": True, "build": b})
        return jsonify({"status": "ok", "active": False, "build": None})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/sentinel/model/status', methods=['GET'])
def api_sentinel_model_status():
    try:
        from workers.sentinel.model_router import get_runtime_status
        return jsonify({"status": "ok", **get_runtime_status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/learning/capabilities', methods=['GET'])
def api_learning_capabilities():
    """Learned capability profiles (Learning Engine registry)."""
    try:
        from core.learning.learning_engine import get_learning_engine
        return jsonify({"status": "ok", "profiles": get_learning_engine().list_profiles()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "profiles": []}), 200


@app.route('/api/capabilities/status', methods=['GET'])
def api_capabilities_status():
    """Capability registry status for Builder Status Center."""
    try:
        from core.capabilities.capability_manager import get_capability_manager
        panels = get_capability_manager(socketio).builder_status_panels()
        return jsonify({"status": "ok", "panels": panels})
    except Exception as e:
        logger.error("Capabilities status error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e), "panels": []}), 200


@app.route('/api/builder/status', methods=['GET'])
def api_builder_status():
    """Builder runtime status panel (GAME Godot, WEB npm, …)."""
    try:
        from builders.builder_status import get_builder_status
        return jsonify({"status": "ok", "panels": get_builder_status()})
    except Exception as e:
        logger.error("Builder status error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e), "panels": []}), 200


@app.route('/api/builder/runtime/godot/install', methods=['POST'])
def api_builder_godot_install():
    try:
        from builders.runtime.godot_runtime import install_godot
        result = install_godot(log_fn=lambda msg, level="info": log(msg, level, "forge"))
        if result.get("ok") and socketio:
            socketio.emit("builder_runtime_updated", {"tool": "godot", **result})
        return jsonify({"status": "ok" if result.get("ok") else "error", **result})
    except Exception as e:
        logger.exception("Godot install failed")
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/builder/runtime/godot/browse', methods=['POST'])
def api_builder_godot_browse():
    try:
        from builders.runtime.godot_runtime import browse_godot_exe
        result = browse_godot_exe()
        if result.get("ok") and socketio:
            socketio.emit("builder_runtime_updated", {"tool": "godot", **result})
        return jsonify({"status": "ok" if result.get("ok") else "error", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/builder/runtime/godot/register', methods=['POST'])
def api_builder_godot_register():
    try:
        from builders.runtime.godot_runtime import register_godot_path
        data = request.get_json() or {}
        path = (data.get("path") or "").strip()
        if not path:
            return jsonify({"status": "error", "error": "path required"}), 200
        result = register_godot_path(path)
        if result.get("ok") and socketio:
            socketio.emit("builder_runtime_updated", {"tool": "godot", **result})
        return jsonify({"status": "ok" if result.get("ok") else "error", **result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/runtime', methods=['GET'])
@app.route('/guardian/runtime', methods=['GET'])
def api_guardian_runtime():
    try:
        from workers.guardian.runtime_manager import get_brain_status, list_ollama_models
        brain = get_brain_status()
        return jsonify({
            "status": "ok",
            "runtime": brain,
            "brain": brain,
            "models": brain.get("installed_models") or list_ollama_models(),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/runtime/model', methods=['POST'])
def api_guardian_runtime_model():
    try:
        from workers.guardian.runtime_manager import get_brain_status, save_models_config
        data = request.get_json() or {}
        model = (data.get("model") or data.get("selected_model") or "").strip()
        if not model:
            return jsonify({"status": "error", "error": "model required"}), 200
        save_models_config({"selected_model": model})
        return jsonify({"status": "ok", "runtime": get_brain_status(), "brain": get_brain_status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/runtime/install', methods=['POST'])
def api_guardian_runtime_install():
    try:
        from workers.guardian.runtime_manager import pull_model, get_brain_status
        data = request.get_json() or {}
        model = (data.get("model") or "dolphin3:8b").strip()
        result = pull_model(model)
        return jsonify({"status": "ok" if result.get("ok") else "error", **result, "brain": get_brain_status()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/bootstrap/status', methods=['GET'])
def api_guardian_bootstrap_status():
    try:
        from workers.guardian.guardian_tool_registry_store import refresh_registry, get_registry_list
        reg = refresh_registry()
        return jsonify({"status": "ok", "registry": reg, "tools": get_registry_list()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/findings/center', methods=['GET'])
def api_guardian_findings_center():
    try:
        from workers.guardian.findings_center import get_session, list_sessions
        sid = request.args.get("session_id", "").strip()
        if sid:
            return jsonify({"status": "ok", "center": get_session(sid)})
        return jsonify({"status": "ok", "sessions": list_sessions()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/settings/trusted-targets', methods=['GET'])
def api_guardian_trusted_list():
    try:
        from workers.guardian.guardian_trusted_targets import list_trusted, get_settings
        return jsonify({"status": "ok", "targets": list_trusted(), "settings": get_settings()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/settings/trusted-targets', methods=['POST'])
def api_guardian_trusted_approve():
    try:
        from workers.guardian.guardian_trusted_targets import approve, revoke
        data = request.get_json() or {}
        target = (data.get("target") or "").strip()
        if not target:
            return jsonify({"status": "error", "error": "target required"}), 200
        if data.get("revoke"):
            revoke(target)
            return jsonify({"status": "ok", "revoked": target})
        entry = approve(target, ttl_days=data.get("ttl_days"), note=data.get("note", ""))
        return jsonify({"status": "ok", "target": target, "entry": entry})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/findings', methods=['GET'])
def api_guardian_findings():
    try:
        from workers.guardian.guardian_findings_db import GuardianFindingsDB
        db = GuardianFindingsDB()
        target = request.args.get("target")
        severity = request.args.get("severity")
        session_id = request.args.get("session_id")
        rows = db.search(target=target, severity=severity, session_id=session_id)
        return jsonify({"status": "ok", "findings": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "findings": []}), 200


@app.route('/api/guardian/offensive-lab/status', methods=['GET'])
def api_guardian_offensive_lab_status():
    try:
        from workers.guardian.guardian_offensive_lab import load_lab_config, is_lab_authorized
        cfg = load_lab_config()
        target = (request.args.get("target") or "").strip()
        auth = {"ok": False, "reason": "no target"}
        if target:
            ok, reason = is_lab_authorized(target, attack_mode=True)
            auth = {"ok": ok, "reason": reason}
        return jsonify({
            "status": "ok",
            "config": cfg,
            "authorization_probe": auth,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/offensive-lab/acknowledge', methods=['POST'])
def api_guardian_offensive_lab_acknowledge():
    """Operator confirms closed-lab-only ethical use."""
    try:
        from workers.guardian.guardian_offensive_lab import acknowledge_closed_lab, load_lab_config
        cfg = acknowledge_closed_lab()
        return jsonify({"status": "ok", "offensive_lab": cfg, "config": load_lab_config()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/crypto-intel', methods=['GET'])
def api_guardian_crypto_intel():
    try:
        from workers.guardian.guardian_crypto_intel import get_roadmap
        return jsonify({"status": "ok", **get_roadmap().to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/guardian/bootstrap', methods=['POST'])
def api_guardian_bootstrap():
    """Run Guardian Bootstrap Manager (all core + extended tools)."""
    try:
        from workers.guardian.bootstrap_manager import run_bootstrap
        force = bool((request.get_json() or {}).get("force"))
        result = run_bootstrap(
            force=force,
            download=True,
            log_fn=lambda msg, level="info": log(msg, level, "guardian"),
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error("Guardian bootstrap error: %s", e, exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 200


def _sentinel_security_gate(module, permission, message="", tool=None, args=""):
    """AI safety + zero-trust gate (API layer only — no workflow/UI changes)."""
    try:
        from sentinel_security.orchestrator import get_security
        sec = get_security()
        blocked = (
            sec.gate_tool(module, tool or "", args or "", message)
            if tool
            else sec.gate_request(module, permission, message)
        )
        if blocked:
            return jsonify({
                "status": "blocked",
                "error": "Blocked by Sentinel security policy",
                "reasons": blocked.reasons,
                "risk_level": blocked.risk_level,
            }), 403
    except Exception as exc:
        logger.debug("Security gate skipped: %s", exc)
    return None


@app.route('/guardian/chat', methods=['POST'])
def api_guardian_chat():
    try:
        data = request.get_json() or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({"status": "error", "error": "No message provided"}), 200
        gate = _sentinel_security_gate("guardian", "network", message)
        if gate:
            return gate
        log(f'Guardian query: {message[:100]}', 'info', 'guardian')
        result = get_guardian_brain().chat(message)
        resp_text = str(result.get("response", ""))
        log(f'Guardian response: {resp_text[:100]}', 'info', 'guardian')
        tool_calls = result.get('tool_calls', [])
        if tool_calls:
            log(f'Guardian ran {len(tool_calls)} tool(s)', 'info', 'guardian')
        return jsonify({"status": "ok", **result})
    except PermissionError as e:
        log(f'Guardian permission error: {e}', 'error', 'guardian')
        log('UAC/admin required — falling back to guidance mode', 'warning', 'guardian')
        return jsonify({"status": "ok", "response": f"I encountered a permissions error: {e}\n\nI'll provide guidance instead of running the tool directly. What would you like to know?", "tool_calls": []}), 200
    except Exception as e:
        logger.error("Guardian chat error: %s", e, exc_info=True)
        log(str(e), 'error', 'guardian')
        return jsonify({"status": "error", "error": str(e), "response": f"Guardian error: {str(e)}"}), 200


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
        gate = _sentinel_security_gate("guardian", "network", tool=tool, args=f"{args} {target}")
        if gate:
            return gate
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


@app.route('/api/security/health', methods=['GET'])
@app.route('/security/health', methods=['GET'])
def api_security_health():
    """Sentinel Security Health report (internal audit — no UI)."""
    try:
        from sentinel_security.guardian_internal_audit import run_internal_audit
        report = run_internal_audit()
        return jsonify({"status": "ok", "score": report.score, "report": report.to_markdown(), "findings": [
            {"category": f.category, "severity": f.severity, "summary": f.summary}
            for f in report.findings
        ]})
    except Exception as e:
        logger.exception("security health failed")
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/security/audit', methods=['GET'])
def api_security_audit():
    """Full security architecture audit payload."""
    try:
        from sentinel_security.orchestrator import get_security
        return jsonify({"status": "ok", **get_security().full_audit_report()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200


@app.route('/api/security/audit-log', methods=['GET'])
def api_security_audit_log():
    """Searchable immutable audit log."""
    try:
        from sentinel_security.orchestrator import get_security
        event_type = request.args.get("event_type")
        module = request.args.get("module")
        limit = min(int(request.args.get("limit", 200)), 1000)
        entries = get_security().audit.search(
            event_type=event_type, module=module, limit=limit,
        )
        return jsonify({
            "status": "ok",
            "chain_valid": get_security().audit.verify_chain(),
            "entries": entries,
        })
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
    _start_broadcasters_once()
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

    # Sentinel Vision — operator subsystem (safe: failure does not block boot)
    try:
        from core.sentinelvision import get_vision_engine
        get_vision_engine(socketio=socketio)
        logger.info("Sentinel Vision subsystem initialized")
    except Exception as e:
        logger.warning("Sentinel Vision initialization failed (disabled): %s", e)
    
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

    # Model runtime: apply active model + self-healing when Ollama drops
    try:
        from core.model_runtime import get_model_runtime, start_self_healing_monitor
        get_model_runtime().apply_active_model_env()
        start_self_healing_monitor(interval_sec=45)
        logger.info("Model runtime self-healing monitor started")
    except Exception as e:
        logger.warning("Model runtime monitor failed: %s", e)

    try:
        from core.ai_provider import bootstrap_providers
        bootstrap_providers()
        logger.info("AI provider bootstrap started")
    except Exception as e:
        logger.warning("AI provider bootstrap failed: %s", e)

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

    # Weekly license revalidation
    def _weekly_revalidate():
        import time as _t
        _t.sleep(30)   # Initial delay — don't block startup
        while backend_state.get("running", True):
            license_manager.revalidate()
            _t.sleep(7 * 24 * 3600)   # Every 7 days

    threading.Thread(target=_weekly_revalidate, daemon=True, name="license-revalidate").start()
    logger.info("License revalidation thread started")

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

    # Guardian bundled toolchain bootstrap (verify / repair core tools)
    def _guardian_bootstrap_thread():
        import time as _gt
        _gt.sleep(2)
        try:
            from workers.guardian.bootstrap_manager import run_bootstrap, should_run_bootstrap

            def _blog(msg, level="info"):
                log(msg, level, "guardian")

            if should_run_bootstrap():
                run_bootstrap(force=False, download=True, log_fn=_blog)
            else:
                from workers.guardian.guardian_tool_registry_store import refresh_registry
                refresh_registry()
        except Exception as e:
            logger.warning("Guardian bootstrap failed: %s", e)

    threading.Thread(target=_guardian_bootstrap_thread, daemon=True, name="guardian-bootstrap").start()

    def _security_bootstrap_thread():
        import time as _st
        _st.sleep(1)
        try:
            from sentinel_security.orchestrator import get_security
            summary = get_security().bootstrap()
            logger.info(
                "[SECURITY] Stack ready — integrity=%s local_first=%s",
                summary.get("integrity_ok"),
                summary.get("local_first_passed"),
            )
        except Exception as e:
            logger.warning("Security bootstrap failed: %s", e)

    threading.Thread(target=_security_bootstrap_thread, daemon=True, name="security-bootstrap").start()

    def _godot_bootstrap_thread():
        import time as _gt
        _gt.sleep(3)
        try:
            from builders.runtime.godot_runtime import bootstrap_godot_runtime
            bootstrap_godot_runtime(log_fn=lambda msg, level="info": log(msg, level, "forge"))
        except Exception as e:
            logger.warning("Godot runtime bootstrap failed: %s", e)

    threading.Thread(target=_godot_bootstrap_thread, daemon=True, name="godot-bootstrap").start()

    def _capability_bootstrap_thread():
        import time as _ct
        _ct.sleep(5)
        try:
            from core.capabilities.capability_manager import get_capability_manager
            get_capability_manager(socketio).bootstrap_tier2(
                log_fn=lambda msg, lvl="info": log(msg, lvl, "system"),
            )
        except Exception as e:
            logger.warning("Capability tier-2 bootstrap failed: %s", e)

    threading.Thread(target=_capability_bootstrap_thread, daemon=True, name="capability-bootstrap").start()

    # Initialize Memory V2 (3-layer hot/warm/cold)
    global memory_v2
    try:
        memory_v2 = get_memory_manager_v2(socketio=socketio)
        logger.info("Memory Manager V2 initialized")
    except Exception as e:
        logger.warning("Memory V2 init failed: %s", e)

    try:
        from core.memory2 import get_memory2_engine
        get_memory2_engine()
        logger.info("Memory 2.0 engine initialized")
    except Exception as e:
        logger.warning("Memory 2.0 init failed: %s", e)

    try:
        from core.missions import get_mission_engine
        get_mission_engine()
        logger.info("Mission engine initialized")
    except Exception as e:
        logger.warning("Mission engine init failed: %s", e)

    try:
        from workers.guardian.system_monitor import get_guardian_monitor
        get_guardian_monitor()
        logger.info("Guardian system monitor initialized")
    except Exception as e:
        logger.warning("Guardian monitor init failed: %s", e)

    try:
        from core.updater import get_auto_updater
        get_auto_updater().check_for_updates()
        logger.info("Auto-updater check completed")
    except Exception as e:
        logger.warning("Auto-updater init failed: %s", e)

    try:
        license_manager.start_beta_period()
    except Exception as e:
        logger.debug("beta period: %s", e)

    try:
        from core.release import get_release_manager
        rm = get_release_manager()
        rm.generate_manifest(channel="beta")
        rm.generate_update_manifest(channel="beta")
    except Exception as e:
        logger.debug("release manifest: %s", e)

    try:
        from core.dependency_manager import get_dependency_manager
        get_dependency_manager().scan_system()
        logger.info("Dependency manager scan completed")
    except Exception as e:
        logger.warning("Dependency manager scan failed: %s", e)

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

    # Telemetry — start flush loop if user has opted in
    def _start_telemetry():
        try:
            if _telemetry.is_opted_in():
                _telemetry.start()
                logger.info('[Telemetry] Started (opted in)')
        except Exception as exc:
            logger.debug('[Telemetry] Startup error: %s', exc)

    threading.Thread(target=_start_telemetry, daemon=True).start()

    # Kill switch — start background checker
    def _start_killswitch():
        try:
            _killswitch.start()
            logger.info('[Killswitch] Checker started')
        except Exception as exc:
            logger.debug('[Killswitch] Startup error: %s', exc)

    threading.Thread(target=_start_killswitch, daemon=True).start()


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
