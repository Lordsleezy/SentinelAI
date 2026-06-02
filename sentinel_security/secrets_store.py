"""Layer 3 — Hardware-backed secrets (DPAPI / keyring abstraction). Never plaintext at rest."""
from __future__ import annotations

import base64
import json
import logging
import os
import platform
from pathlib import Path
from typing import Dict, Optional

from sentinel_security.config import SECURITY_DIR

logger = logging.getLogger("sentinel.security.secrets")

SECRETS_BLOB = SECURITY_DIR / "secrets.enc.json"
BACKEND_INFO = SECURITY_DIR / "secrets_backend.json"


def _dpapi_encrypt(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise OSError("DPAPI only on Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    CryptProtectData = ctypes.windll.crypt32.CryptProtectData
    CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    CryptProtectData.restype = wintypes.BOOL

    buf = (ctypes.c_byte * len(data))(*data)
    blob_in = DATA_BLOB(len(data), buf)
    blob_out = DATA_BLOB()
    if not CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData failed")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return out


def _dpapi_decrypt(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise OSError("DPAPI only on Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
    CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    CryptUnprotectData.restype = wintypes.BOOL

    buf = (ctypes.c_byte * len(data))(*data)
    blob_in = DATA_BLOB(len(data), buf)
    blob_out = DATA_BLOB()
    if not CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData failed")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return out


def _derive_key_from_user_secret(secret: str, salt: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
        return kdf.derive(secret.encode("utf-8"))
    except ImportError:
        import hashlib
        return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 480_000)


def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os as _os
    nonce = _os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def _aes_decrypt(blob: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


class SecretsStore:
    """
    Stores API keys, OAuth tokens, session tokens, encryption keys.
    Backends: Windows DPAPI (TPM-backed when available), user-secret PBKDF2 fallback.
    """

    def __init__(self) -> None:
        SECURITY_DIR.mkdir(parents=True, exist_ok=True)
        self._backend = self._detect_backend()
        self._cache: Dict[str, str] = {}
        self._load()

    def _detect_backend(self) -> str:
        if platform.system() == "Windows":
            try:
                _dpapi_encrypt(b"probe")
                return "windows_dpapi"
            except Exception:
                pass
        if os.getenv("SENTINEL_USER_SECRET"):
            return "user_secret"
        return "user_secret_required"

    def _load(self) -> None:
        if not SECRETS_BLOB.is_file():
            return
        try:
            wrapper = json.loads(SECRETS_BLOB.read_text(encoding="utf-8"))
            raw = base64.b64decode(wrapper["blob"])
            if wrapper.get("backend") == "windows_dpapi":
                plain = _dpapi_decrypt(raw)
            else:
                secret = os.getenv("SENTINEL_USER_SECRET", "")
                if not secret:
                    logger.warning("Secrets blob present but SENTINEL_USER_SECRET not set")
                    return
                salt = base64.b64decode(wrapper["salt"])
                key = _derive_key_from_user_secret(secret, salt)
                plain = _aes_decrypt(raw, key)
            self._cache = json.loads(plain.decode("utf-8"))
        except Exception as e:
            logger.error("Failed to load secrets: %s", e)

    def _persist(self) -> None:
        plain = json.dumps(self._cache).encode("utf-8")
        if self._backend == "windows_dpapi":
            blob = _dpapi_encrypt(plain)
            wrapper = {"backend": "windows_dpapi", "blob": base64.b64encode(blob).decode("ascii")}
        else:
            import os as _os
            secret = os.getenv("SENTINEL_USER_SECRET", "")
            if not secret:
                raise RuntimeError("Set SENTINEL_USER_SECRET to persist secrets without DPAPI")
            salt = _os.urandom(16)
            key = _derive_key_from_user_secret(secret, salt)
            blob = _aes_encrypt(plain, key)
            wrapper = {
                "backend": "user_secret",
                "salt": base64.b64encode(salt).decode("ascii"),
                "blob": base64.b64encode(blob).decode("ascii"),
            }
        SECRETS_BLOB.write_text(json.dumps(wrapper), encoding="utf-8")
        BACKEND_INFO.write_text(json.dumps({"backend": self._backend, "yubikey": False, "passkey": False}), encoding="utf-8")

    def set_secret(self, name: str, value: str) -> None:
        if not name or not value:
            raise ValueError("name and value required")
        self._cache[name] = value
        self._persist()

    def get_secret(self, name: str) -> Optional[str]:
        return self._cache.get(name)

    def delete_secret(self, name: str) -> None:
        self._cache.pop(name, None)
        self._persist()

    def backends_supported(self) -> Dict[str, bool]:
        return {
            "windows_dpapi_tpm": platform.system() == "Windows",
            "user_secret": True,
            "yubikey": False,
            "passkey": False,
            "android_strongbox": False,
            "active": self._backend,
        }
