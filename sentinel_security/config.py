"""Security configuration — env-driven, local-first defaults."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURITY_DIR = ROOT / "memory" / "vault" / "security"
MANIFEST_PATH = SECURITY_DIR / "module_manifest.json"
AUDIT_LOG_PATH = SECURITY_DIR / "audit.jsonl"
POLICY_PATH = SECURITY_DIR / "module_policy.json"


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


# Layer 1 — local first
CLOUD_SYNC_ENABLED = _env_bool("SENTINEL_CLOUD_SYNC", False)

# Layer 4 — encrypted vault (opt-in)
VAULT_ENCRYPT_ENABLED = _env_bool("SENTINEL_VAULT_ENCRYPT", False)

# Layer 5 — hybrid PQC when libraries present
PQC_HYBRID_ENABLED = _env_bool("SENTINEL_PQC_HYBRID", False)

# Layer 8 — block dangerous paths when strict
SECURITY_STRICT = _env_bool("SENTINEL_SECURITY_STRICT", True)

# Paths that must stay local
LOCAL_DATA_ROOTS = (
    ROOT / "memory",
    ROOT / "memory" / "vault",
    ROOT / "data",
)
