"""
Remote kill-switch checker for SentinelAI.

Periodically fetches a status payload from the kill-switch endpoint.
If the switch is active AND the current install is not a paid/owner build,
the app UI is blocked with a full-screen overlay until the condition clears.

Endpoint contract (GET https://sentinelprime.org/api/killswitch):
    {
        "active":   true | false,
        "reason":   "string shown to user",
        "min_version": "1.2.0"   // optional — block outdated builds
    }

The result is cached to ~/.sentinelai/killswitch_cache.json so the app
can honour the switch even when starting offline after a previous check.

Pro / Owner installs are NEVER blocked by the kill-switch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SENTINEL_DIR  = Path.home() / '.sentinelai'
_CACHE_FILE    = _SENTINEL_DIR / 'killswitch_cache.json'
_KILLSWITCH_URL = 'https://sentinelprime.org/api/killswitch'
_CHECK_INTERVAL = 30 * 60    # 30 minutes
_REQUEST_TIMEOUT = 8


class KillswitchChecker:
    """
    Background checker that polls the remote kill-switch endpoint.

    Usage:
        ksc = get_killswitch_checker(is_owner=OWNER_MODE, is_pro=license_manager.is_pro)
        ksc.start()
        ...
        status = ksc.get_status()   # {'active': bool, 'reason': str}
    """

    def __init__(self, is_owner: bool = False, is_pro_fn=None) -> None:
        self._is_owner  = is_owner
        self._is_pro_fn = is_pro_fn    # callable -> bool
        self._status: dict = {'active': False, 'reason': '', 'checked_at': 0}
        self._lock   = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

        # Load cached state on init so blocking works even on first cold start
        self._load_cache()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop, daemon=True, name='killswitch-checker'
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_status(self) -> dict:
        """
        Returns {'active': bool, 'reason': str}.
        Always returns active=False for owner or pro installs.
        """
        if self._is_owner:
            return {'active': False, 'reason': 'owner build'}
        if self._is_pro_fn and self._is_pro_fn():
            return {'active': False, 'reason': 'pro license'}
        with self._lock:
            return dict(self._status)

    def check_now(self) -> dict:
        """Force an immediate check and return the result."""
        self._fetch()
        return self.get_status()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _check_loop(self) -> None:
        # First check after a short delay to let Flask settle
        time.sleep(15)
        while self._running:
            self._fetch()
            time.sleep(_CHECK_INTERVAL)

    def _fetch(self) -> None:
        try:
            import requests
            resp = requests.get(
                _KILLSWITCH_URL,
                timeout=_REQUEST_TIMEOUT,
                headers={'User-Agent': 'SentinelAI/killswitch'},
            )
            if resp.status_code == 200:
                data = resp.json()
                active = bool(data.get('active', False))
                reason = str(data.get('reason', 'Service temporarily unavailable.'))
                min_ver = data.get('min_version')
                if min_ver:
                    from packaging.version import Version
                    import os
                    app_ver = os.getenv('SENTINEL_VERSION', '0.0.0')
                    try:
                        if Version(app_ver) < Version(min_ver):
                            active = True
                            reason = f'Please update SentinelAI to v{min_ver} or later.'
                    except Exception:
                        pass
                with self._lock:
                    self._status = {
                        'active':     active,
                        'reason':     reason,
                        'checked_at': int(time.time()),
                    }
                self._save_cache()
                logger.debug('[Killswitch] active=%s', active)
            else:
                logger.debug('[Killswitch] HTTP %s — keeping cached state', resp.status_code)
        except Exception as exc:
            logger.debug('[Killswitch] Check failed (offline?): %s', exc)

    def _save_cache(self) -> None:
        _SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                data = dict(self._status)
            _CACHE_FILE.write_text(json.dumps(data), encoding='utf-8')
        except Exception as exc:
            logger.debug('[Killswitch] Cache save failed: %s', exc)

    def _load_cache(self) -> None:
        try:
            if _CACHE_FILE.exists():
                data = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
                # Only honour cache if checked within the last 24 hours
                age = time.time() - data.get('checked_at', 0)
                if age < 86400:
                    with self._lock:
                        self._status = data
                    logger.debug('[Killswitch] Loaded cache (age %.0fh)', age / 3600)
        except Exception as exc:
            logger.debug('[Killswitch] Cache load failed: %s', exc)


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: KillswitchChecker | None = None
_instance_lock = threading.Lock()


def get_killswitch_checker(is_owner: bool = False, is_pro_fn=None) -> KillswitchChecker:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = KillswitchChecker(is_owner=is_owner, is_pro_fn=is_pro_fn)
    return _instance
