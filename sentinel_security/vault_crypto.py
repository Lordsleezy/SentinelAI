"""Layer 4 — Authenticated encryption for vault paths (AES-GCM)."""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

from sentinel_security.config import ROOT, VAULT_ENCRYPT_ENABLED

logger = logging.getLogger("sentinel.security.vault")

ENCRYPTED_SUFFIX = ".sentinelenc"
VAULT_ROOTS = (
    ROOT / "memory" / "vault",
    ROOT / "memory",
    ROOT / "data",
)


def _get_vault_key() -> Optional[bytes]:
    try:
        from sentinel_security.secrets_store import SecretsStore
        raw = SecretsStore().get_secret("vault_master_key")
        if raw:
            return base64.b64decode(raw)
    except Exception:
        pass
    env = os.getenv("SENTINEL_VAULT_KEY", "")
    if env:
        return base64.b64decode(env)
    return None


def ensure_vault_key() -> bytes:
    key = _get_vault_key()
    if key and len(key) >= 32:
        return key[:32]
    import secrets as _sec
    key = _sec.token_bytes(32)
    try:
        from sentinel_security.secrets_store import SecretsStore
        SecretsStore().set_secret("vault_master_key", base64.b64encode(key).decode("ascii"))
    except Exception as e:
        logger.warning("Could not persist vault key to secrets store: %s", e)
    return key


def encrypt_bytes(plaintext: bytes, key: Optional[bytes] = None) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = key or ensure_vault_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, b"sentinel-vault-v1")
    return b"SENC1" + nonce + ct


def decrypt_bytes(blob: bytes, key: Optional[bytes] = None) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(b"SENC1"):
        return blob
    key = key or ensure_vault_key()
    nonce, ct = blob[5:17], blob[17:]
    return AESGCM(key).decrypt(nonce, ct, b"sentinel-vault-v1")


def encrypt_file(path: Path) -> bool:
    if not VAULT_ENCRYPT_ENABLED:
        return False
    enc_path = Path(str(path) + ENCRYPTED_SUFFIX)
    if enc_path.is_file():
        return True
    try:
        data = path.read_bytes()
        enc_path.write_bytes(encrypt_bytes(data))
        path.unlink()
        return True
    except Exception as e:
        logger.error("encrypt_file %s: %s", path, e)
        return False


def decrypt_file(enc_path: Path) -> bytes:
    return decrypt_bytes(enc_path.read_bytes())


def vault_status() -> dict:
    return {
        "encryption_enabled": VAULT_ENCRYPT_ENABLED,
        "key_available": _get_vault_key() is not None or bool(os.getenv("SENTINEL_VAULT_KEY")),
        "algorithm": "AES-256-GCM",
        "roots": [str(p) for p in VAULT_ROOTS],
    }
