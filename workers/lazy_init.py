"""Lazy credential initialization — credentials collected on demand.

Workers declare what they need via REQUIREMENTS.
Before executing, call check(worker_name).  If anything is missing,
returns a dict that the orb renders as an inline setup card.
Once the user fills it in, call save(key, value) to persist to .env
and os.environ immediately.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _env_path() -> Path:
    try:
        from core.app_paths import resolve_env_path
        return resolve_env_path()
    except ImportError:
        return Path(__file__).parent.parent / ".env"


class LazyInit:
    # (env_key, label, hint, is_secret)
    REQUIREMENTS: dict[str, list[tuple[str, str, str, bool]]] = {
        "spotify": [
            ("SPOTIPY_CLIENT_ID", "Spotify Client ID", "from developer.spotify.com", False),
            ("SPOTIPY_CLIENT_SECRET", "Spotify Client Secret", "from developer.spotify.com", True),
        ],
        "telegram": [
            ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token", "from @BotFather", True),
            ("TELEGRAM_ALLOWED_USER_ID", "Your Telegram User ID", "from @userinfobot", False),
        ],
        "home": [
            ("HA_URL", "Home Assistant URL", "e.g. http://homeassistant.local:8123", False),
            ("HA_TOKEN", "Home Assistant Token", "Long-lived access token from HA profile", True),
        ],
        "google": [
            ("GOOGLE_CREDENTIALS_PATH", "Google credentials.json path", "from console.cloud.google.com", False),
        ],
        "brave": [
            ("BRAVE_API_KEY", "Brave Search API Key", "from api.search.brave.com", True),
        ],
        "finance": [
            ("FIREFLY_URL", "Firefly III URL", "your self-hosted instance", False),
            ("FIREFLY_TOKEN", "Firefly III Token", "from Firefly profile", True),
        ],
        "health": [
            ("OPEN_WEARABLES_TOKEN", "Open Wearables Token", "from your wearables app", True),
        ],
        "news": [
            ("MINIFLUX_URL", "Miniflux URL", "your self-hosted instance", False),
            ("MINIFLUX_API_KEY", "Miniflux API Key", "from Miniflux settings", True),
        ],
        "packages": [
            ("USPS_USER_ID", "USPS API User ID", "from registration.shippingapis.com", False),
        ],
        "consultation": [
            ("ANTHROPIC_API_KEY", "Anthropic API Key",
             "from console.anthropic.com — optional, for API escalation only", True),
        ],
        "scalp": [
            ("BINANCE_API_KEY", "Binance API Key",
             "from binance.com/en/my/settings/api-management — read-only is fine for paper trading", True),
            ("BINANCE_API_SECRET", "Binance API Secret",
             "from binance.com API management", True),
        ],
    }

    def get_missing(self, worker_name: str) -> list[dict[str, Any]]:
        """Return list of dicts for missing credentials."""
        reqs = self.REQUIREMENTS.get(worker_name, [])
        missing = []
        for (env_key, label, hint, is_secret) in reqs:
            if not os.environ.get(env_key):
                missing.append({
                    "key": env_key,
                    "label": label,
                    "hint": hint,
                    "is_secret": is_secret,
                })
        return missing

    def is_configured(self, worker_name: str) -> bool:
        """True if every credential for this worker is present."""
        return len(self.get_missing(worker_name)) == 0

    def check(self, worker_name: str) -> dict | None:
        """
        Returns None if all credentials are present.
        Returns a setup-card dict if anything is missing.
        """
        missing = self.get_missing(worker_name)
        if not missing:
            return None
        return {
            "error": "not_configured",
            "worker": worker_name,
            "missing": missing,
            "title": f"Setup Required — {worker_name.capitalize()}",
        }

    # Keys that must never be settable through the API surface. These either
    # control the security posture (AUTH_TOKEN, OWNER_MODE) or affect process
    # bootstrapping in ways that would let a caller pivot off the app.
    DENY_KEYS: set[str] = {
        "SENTINELAI_AUTH_TOKEN",
        "SENTINEL_OWNER_MODE",
        "SENTINEL_DEV_TOOLS",
        "PATH",
        "PYTHONPATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }

    def allowed_keys(self) -> set[str]:
        """All credential keys declared by any worker, used as an allowlist."""
        keys: set[str] = set()
        for reqs in self.REQUIREMENTS.values():
            for env_key, *_ in reqs:
                keys.add(env_key)
        # Common service-routing knobs the user is permitted to override.
        keys.update({
            "OLLAMA_URL",
            "OLLAMA_HOST",
            "OLLAMA_MODEL",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GROQ_API_KEY",
        })
        return keys - self.DENY_KEYS

    def is_allowed_key(self, key: str) -> bool:
        return key in self.allowed_keys()

    def save(self, key: str, value: str) -> bool:
        """Write key=value to .env and os.environ immediately.

        Rejects any key outside the allowlist — this guards the .env file from
        being used as an arbitrary env-var injection sink via the API surface.
        """
        if not self.is_allowed_key(key):
            logger.warning("[LazyInit] Refusing to save disallowed key: %s", key)
            return False
        try:
            env_file = _env_path()
            # Read existing content
            if env_file.exists():
                content = env_file.read_text(encoding="utf-8")
            else:
                content = ""

            # Replace existing key or append
            pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
            new_line = f"{key}={value}"
            if pattern.search(content):
                content = pattern.sub(new_line, content)
            else:
                if content and not content.endswith("\n"):
                    content += "\n"
                content += new_line + "\n"

            env_file.write_text(content, encoding="utf-8")
            os.environ[key] = value
            logger.info("[LazyInit] Saved %s to .env", key)
            return True
        except Exception:
            logger.exception("[LazyInit] Failed to save %s", key)
            return False


# Module-level singleton
_lazy_init = LazyInit()


def get_lazy_init() -> LazyInit:
    return _lazy_init
