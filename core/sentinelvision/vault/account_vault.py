"""Encrypted account vault — credentials never exposed to chat APIs."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from core.sentinelvision.audit import audit_log

logger = logging.getLogger("sentinel.vision.vault")

_PROVIDER_PREFIX = "vision:vault:"
_LEGACY_PREFIX = "scrub:vault:"
_ALLOWED_ROLES = frozenset({"operator", "admin", "read_metadata"})


def _store():
    from sentinel_security.secrets_store import SecretsStore
    return SecretsStore()


class AccountVault:
    """
    Provider-scoped secrets via Sentinel SecretsStore (DPAPI / AES).
    List endpoints return metadata only — never secret values.
    """

    def register_provider_account(
        self,
        provider_id: str,
        fields: Dict[str, str],
        *,
        label: Optional[str] = None,
        role: str = "operator",
    ) -> Dict[str, Any]:
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"invalid role: {role}")
        pid = _normalize_provider(provider_id)
        store = _store()
        stored_keys = []
        for key, value in fields.items():
            if not value or not str(value).strip():
                continue
            secret_name = f"{_PROVIDER_PREFIX}{pid}:{key}"
            store.set_secret(secret_name, str(value).strip())
            stored_keys.append(key)
            audit_log("vault_field_set", provider_id=pid, action=key)
        meta_name = f"{_PROVIDER_PREFIX}{pid}:__meta__"
        import json
        store.set_secret(meta_name, json.dumps({"label": label or pid, "fields": stored_keys}))
        return {"provider_id": pid, "fields_registered": stored_keys, "label": label or pid}

    def list_providers(self) -> List[Dict[str, Any]]:
        store = _store()
        cache = getattr(store, "_cache", {})
        providers: Dict[str, Dict[str, Any]] = {}
        for name in cache:
            prefix = _prefix_for_name(name)
            if not prefix or name.endswith(":__meta__"):
                continue
            parts = name[len(prefix) :].split(":", 1)
            if len(parts) != 2:
                continue
            pid, field = parts[0], parts[1]
            if pid not in providers:
                meta_raw = _read_meta(cache, pid)
                label = pid
                fields = []
                if meta_raw:
                    try:
                        import json
                        m = json.loads(meta_raw)
                        label = m.get("label", pid)
                        fields = m.get("fields", [])
                    except Exception:
                        pass
                providers[pid] = {
                    "provider_id": pid,
                    "label": label,
                    "fields_configured": fields,
                    "has_credentials": bool(fields),
                }
        return list(providers.values())

    def has_credentials(self, provider_id: str) -> bool:
        pid = _normalize_provider(provider_id)
        store = _store()
        import json
        meta = _read_meta(getattr(store, "_cache", {}), pid) or store.get_secret(f"{_PROVIDER_PREFIX}{pid}:__meta__")
        if not meta:
            return False
        try:
            fields = json.loads(meta).get("fields", [])
            return any(_get_field_secret(store, pid, f) for f in fields)
        except Exception:
            return False

    def get_credentials(self, provider_id: str, role: str = "operator") -> Dict[str, str]:
        """In-process only — never serialize to chat/API responses."""
        if role not in _ALLOWED_ROLES:
            raise PermissionError("role not allowed")
        pid = _normalize_provider(provider_id)
        store = _store()
        import json
        cache = getattr(store, "_cache", {})
        meta = _read_meta(cache, pid) or store.get_secret(f"{_PROVIDER_PREFIX}{pid}:__meta__")
        if not meta:
            return {}
        out: Dict[str, str] = {}
        try:
            for field in json.loads(meta).get("fields", []):
                val = _get_field_secret(store, pid, field)
                if val:
                    out[field] = val
        except Exception as e:
            logger.error("vault read %s: %s", pid, e)
        return out

    def delete_provider(self, provider_id: str) -> None:
        pid = _normalize_provider(provider_id)
        store = _store()
        to_delete = [
            k for k in list(getattr(store, "_cache", {}))
            if k.startswith(f"{_PROVIDER_PREFIX}{pid}:") or k.startswith(f"{_LEGACY_PREFIX}{pid}:")
        ]
        for k in to_delete:
            store.delete_secret(k)
        audit_log("vault_provider_deleted", provider_id=pid)


def _prefix_for_name(name: str) -> Optional[str]:
    if name.startswith(_PROVIDER_PREFIX):
        return _PROVIDER_PREFIX
    if name.startswith(_LEGACY_PREFIX):
        return _LEGACY_PREFIX
    return None


def _read_meta(cache: Dict[str, Any], pid: str) -> Optional[str]:
    return cache.get(f"{_PROVIDER_PREFIX}{pid}:__meta__") or cache.get(f"{_LEGACY_PREFIX}{pid}:__meta__")


def _get_field_secret(store: Any, pid: str, field: str) -> Optional[str]:
    val = store.get_secret(f"{_PROVIDER_PREFIX}{pid}:{field}")
    if val:
        return val
    return store.get_secret(f"{_LEGACY_PREFIX}{pid}:{field}")


def _normalize_provider(provider_id: str) -> str:
    pid = (provider_id or "").strip().lower()
    if not re.match(r"^[a-z0-9_-]{2,32}$", pid):
        raise ValueError("invalid provider_id")
    return pid
