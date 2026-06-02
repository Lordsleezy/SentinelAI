"""Layer 5 — Post-quantum cryptography abstraction (standard libs only, hybrid mode)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from sentinel_security.config import PQC_HYBRID_ENABLED

logger = logging.getLogger("sentinel.security.pqc")


@dataclass
class PQCStatus:
    kyber_available: bool
    dilithium_available: bool
    library: Optional[str]
    hybrid_enabled: bool


def _try_oqs() -> Tuple[bool, bool, Optional[str]]:
    try:
        import oqs  # liboqs-python
        with oqs.KeyEncapsulation("Kyber512") as _kem:
            pass
        with oqs.Signature("Dilithium2") as _sig:
            pass
        return True, True, "liboqs"
    except Exception:
        return False, False, None


def _try_pqcrypto() -> Tuple[bool, bool, Optional[str]]:
    try:
        from pqcrypto.kem.kyber512 import generate_keypair  # type: ignore
        from pqcrypto.sign.dilithium2 import generate_keypair as gen_sig  # type: ignore
        generate_keypair()
        gen_sig()
        return True, True, "pqcrypto"
    except Exception:
        return False, False, None


def pqc_status() -> PQCStatus:
    k, d, lib = _try_oqs()
    if not k:
        k, d, lib = _try_pqcrypto()
    return PQCStatus(
        kyber_available=k,
        dilithium_available=d,
        library=lib,
        hybrid_enabled=PQC_HYBRID_ENABLED and k,
    )


class PQCHybrid:
    """
    Hybrid classical + PQC wrapper. Uses SHA-256 + optional Kyber KEM when available.
    No custom crypto — defers to liboqs/pqcrypto when installed.
    """

    def __init__(self) -> None:
        self._status = pqc_status()

    def encapsulate(self, peer_public: Optional[bytes] = None) -> Dict[str, object]:
        import hashlib
        import os
        classical_secret = os.urandom(32)
        result: Dict[str, object] = {
            "mode": "classical-only",
            "classical_digest": hashlib.sha256(classical_secret).hexdigest(),
        }
        if self._status.kyber_available and self._status.hybrid_enabled:
            try:
                import oqs
                with oqs.KeyEncapsulation("Kyber512") as kem:
                    public = kem.generate_keypair()
                    ciphertext, shared = kem.encap_secret(peer_public or public)
                    result["mode"] = "hybrid-kyber512"
                    result["pqc_ciphertext_len"] = len(ciphertext)
                    result["shared_secret_len"] = len(shared)
            except Exception as e:
                logger.debug("Kyber encaps failed: %s", e)
        return result
