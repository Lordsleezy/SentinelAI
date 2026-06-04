"""
Anonymous usage telemetry for SentinelAI.

What is collected (NO personal data, NO chat content):
  - A random UUID generated once per install (never tied to identity)
  - Event names: app_start, feature_used, model_used, panel_opened, earn_accepted
  - OS family (windows/linux/mac), Python version, app version
  - Session duration in seconds

What is NEVER collected:
  - Chat messages, prompts, or AI responses
  - File paths, project names, or code content
  - IP address (stripped at the Netlify/Supabase edge)
  - License keys or any credentials

Opt-in: controlled by ~/.sentinelai/telemetry_opt_in (file presence = opted in).
Users choose during setup wizard; they can change this via settings at any time.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_SENTINEL_DIR     = Path.home() / '.sentinelai'
_OPT_IN_FILE      = _SENTINEL_DIR / 'telemetry_opt_in'
_INSTALL_ID_FILE  = None  # resolved lazily via product_analytics / AppData
_TELEMETRY_URL    = 'https://sentinelprime.org/api/telemetry'
_FLUSH_INTERVAL   = 120          # seconds between flushes
_MAX_QUEUE        = 50           # drop oldest events when queue overflows
_APP_VERSION      = os.getenv('SENTINEL_VERSION', '1.0.0')


class TelemetryManager:
    """
    Thread-safe, opt-in anonymous telemetry.

    Usage:
        tm = get_telemetry_manager()
        tm.track('feature_used', {'feature': 'guardian'})
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._queue: list[dict] = []
        self._session_start = time.time()
        self._install_id  = self._load_install_id()
        self._flush_thread: threading.Thread | None = None
        self._running = False

    # ── Opt-in helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def is_opted_in() -> bool:
        return _OPT_IN_FILE.exists()

    @staticmethod
    def opt_in() -> None:
        _SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
        _OPT_IN_FILE.touch(exist_ok=True)
        logger.info('[Telemetry] Opted in')

    @staticmethod
    def opt_out() -> None:
        try:
            _OPT_IN_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        logger.info('[Telemetry] Opted out')

    # ── Install ID ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_install_id() -> str:
        try:
            from workers.telemetry.product_analytics import get_install_id
            return get_install_id()
        except Exception:
            _SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
            legacy = _SENTINEL_DIR / 'install_id'
            if legacy.exists():
                try:
                    return legacy.read_text().strip()
                except Exception:
                    pass
            new_id = str(uuid.uuid4())
            try:
                legacy.write_text(new_id)
            except Exception:
                pass
            return new_id

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background flush thread and emit app_start event."""
        if self._running:
            return
        self._running = True
        self.track('app_start', {
            'os': platform.system().lower(),
            'py': f'{sys.version_info.major}.{sys.version_info.minor}',
            'version': _APP_VERSION,
        })
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name='telemetry-flush'
        )
        self._flush_thread.start()

    def stop(self) -> None:
        """Flush remaining events and stop the background thread."""
        self._running = False
        self._flush()

    def track(self, event: str, props: dict[str, Any] | None = None) -> None:
        """Queue an event for sending. Silently no-ops if not opted in."""
        if not self.is_opted_in():
            return
        payload = {
            'install_id': self._install_id,
            'event':      event,
            'props':      props or {},
            'ts':         int(time.time()),
        }
        with self._lock:
            if len(self._queue) >= _MAX_QUEUE:
                self._queue.pop(0)   # drop oldest
            self._queue.append(payload)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(_FLUSH_INTERVAL)
            self._flush()

    def _flush(self) -> None:
        if not self.is_opted_in():
            with self._lock:
                self._queue.clear()
            return

        with self._lock:
            if not self._queue:
                return
            batch = list(self._queue)
            self._queue.clear()

        try:
            import requests
            requests.post(
                _TELEMETRY_URL,
                json={'events': batch},
                timeout=8,
                headers={'Content-Type': 'application/json'},
            )
            logger.debug('[Telemetry] Flushed %d events', len(batch))
        except Exception as exc:
            logger.debug('[Telemetry] Flush failed (offline?): %s', exc)
            # Re-queue on failure so we don't lose events permanently
            with self._lock:
                self._queue = batch + self._queue
                if len(self._queue) > _MAX_QUEUE:
                    self._queue = self._queue[-_MAX_QUEUE:]


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: TelemetryManager | None = None
_instance_lock = threading.Lock()


def get_telemetry_manager() -> TelemetryManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = TelemetryManager()
    return _instance
