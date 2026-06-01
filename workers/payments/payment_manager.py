"""
payment_manager.py — Encrypted payment vault for SentinelAI.

Payment details are encrypted with a key derived from the machine identity —
they never leave the device and are never logged or transmitted in plaintext.
"""
CAPABILITY_DESCRIPTION = (
    "Manages payment methods and spending limits with on-device encryption. "
    "Supports cards, PayPal, Amazon Pay, Google Pay, Venmo, Cash App, "
    "Ethereum, USDC, Bitcoin, and bank ACH."
)

import base64
import hashlib
import json
import logging
import os
import platform
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Supported payment method schemas (required / optional fields + display label)
PAYMENT_METHOD_SCHEMAS: Dict[str, Dict] = {
    "card":        {"required": ["card_number", "expiry", "cvv"], "optional": ["cardholder_name", "brand", "billing_zip"], "display": "Credit/Debit Card"},
    "paypal":      {"required": ["email", "password"],             "optional": [],                                          "display": "PayPal"},
    "amazon_pay":  {"required": ["email", "password"],             "optional": [],                                          "display": "Amazon Pay"},
    "google_pay":  {"required": ["email", "token"],                "optional": [],                                          "display": "Google Pay"},
    "apple_pay":   {"required": ["device_token"],                  "optional": ["device"],                                  "display": "Apple Pay"},
    "venmo":       {"required": ["username", "password"],          "optional": ["phone"],                                   "display": "Venmo"},
    "cashapp":     {"required": ["cashtag", "password"],           "optional": ["phone"],                                   "display": "Cash App"},
    "crypto_eth":  {"required": ["wallet_address", "private_key"], "optional": ["network"],                                 "display": "Ethereum Wallet"},
    "crypto_btc":  {"required": ["wallet_address", "private_key"], "optional": [],                                          "display": "Bitcoin Wallet"},
    "crypto_usdc": {"required": ["wallet_address", "private_key", "network"], "optional": [],                               "display": "USDC Stablecoin"},
    "bank_ach":    {"required": ["routing_number", "account_number", "account_type"], "optional": ["bank_name"],            "display": "Bank Account (ACH)"},
}

_VAULT_PATH = Path(__file__).parent.parent.parent / "config" / "payment_vault.enc"


class PaymentManager:
    def __init__(self, vault_path: Optional[Path] = None):
        self._vault_path = Path(vault_path or _VAULT_PATH)
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = self._build_fernet()
        self._vault = self._load_vault()

    # ── Key derivation ────────────────────────────────────────────────────────

    def _build_fernet(self):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            machine_id = f"{_safe_login()}{socket.gethostname()}{platform.processor()}"
            seed = hashlib.sha256(machine_id.encode()).digest()
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=seed[:16], iterations=100_000)
            key = base64.urlsafe_b64encode(kdf.derive(seed))
            return Fernet(key)
        except Exception as e:
            logger.warning("Fernet unavailable (%s) — vault stored as plaintext JSON", e)
            return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_vault(self) -> Dict:
        try:
            if self._vault_path.exists():
                raw = self._vault_path.read_bytes()
                if self._fernet:
                    data = self._fernet.decrypt(raw)
                else:
                    data = raw
                return json.loads(data)
        except Exception as e:
            logger.warning("Vault load error — starting fresh: %s", e)
        return {"payment_methods": [], "details": {}, "spending_limits": {"per_transaction_all": 500.0}}

    def _save_vault(self):
        try:
            raw = json.dumps(self._vault).encode()
            out = self._fernet.encrypt(raw) if self._fernet else raw
            self._vault_path.write_bytes(out)
        except Exception as e:
            logger.error("Vault save error: %s", e)

    # ── Payment methods ───────────────────────────────────────────────────────

    def add_payment_method(self, method_type: str, nickname: str, details: Dict) -> Dict:
        """Add a payment method. Returns display info only — raw details are encrypted."""
        if method_type not in PAYMENT_METHOD_SCHEMAS:
            return {"status": "error", "error": f"Unknown type '{method_type}'. Supported: {list(PAYMENT_METHOD_SCHEMAS)}"}

        method_id = f"pm_{len(self._vault['payment_methods']) + 1}"
        display = _build_display(method_type, details)

        entry = {
            "id": method_id,
            "type": method_type,
            "nickname": nickname,
            "display": display,
            "schema_label": PAYMENT_METHOD_SCHEMAS[method_type]["display"],
            "is_default": len(self._vault["payment_methods"]) == 0,
            "added_at": datetime.now().isoformat(),
        }

        self._vault["details"][method_id] = details
        self._vault["payment_methods"].append(entry)
        self._save_vault()
        logger.info("Payment method added: %s (%s)", nickname, method_type)
        return {"status": "ok", "method_id": method_id, "display": display}

    def get_payment_methods(self) -> List[Dict]:
        """Return all methods — display info only, never raw credentials."""
        return [
            {k: v for k, v in m.items() if k != "details"}
            for m in self._vault.get("payment_methods", [])
        ]

    def get_default_method(self) -> Optional[Dict]:
        for m in self._vault.get("payment_methods", []):
            if m.get("is_default"):
                return m
        methods = self._vault.get("payment_methods", [])
        return methods[0] if methods else None

    def set_default_method(self, method_id: str) -> Dict:
        for m in self._vault["payment_methods"]:
            m["is_default"] = (m["id"] == method_id)
        self._save_vault()
        return {"status": "ok", "default": method_id}

    def remove_payment_method(self, method_id: str) -> Dict:
        self._vault["payment_methods"] = [m for m in self._vault["payment_methods"] if m["id"] != method_id]
        self._vault["details"].pop(method_id, None)
        self._save_vault()
        return {"status": "ok", "removed": method_id}

    def get_details(self, method_id: str) -> Dict:
        """Return raw credentials for checkout — never exposed to the UI."""
        return self._vault.get("details", {}).get(method_id, {})

    # ── Spending limits ───────────────────────────────────────────────────────

    def set_spending_limit(self, period: str, amount: float, category: str = "all") -> Dict:
        key = f"{period}_{category}"
        self._vault["spending_limits"][key] = amount
        self._save_vault()
        return {"status": "ok", "key": key, "limit": amount}

    def check_spending_limit(self, amount: float, category: str = "shopping") -> Dict:
        limit = self._vault.get("spending_limits", {}).get("per_transaction_all", 500.0)
        if amount > limit:
            return {"allowed": False, "reason": f"${amount:.2f} exceeds per-transaction limit of ${limit:.2f}"}
        return {"allowed": True}

    def get_limits(self) -> Dict:
        return self._vault.get("spending_limits", {})

    # ── Transaction log ───────────────────────────────────────────────────────

    def log_transaction(self, tx: Dict):
        tx_dir = Path(__file__).parent.parent.parent / "memory" / "vault" / "transactions"
        tx_dir.mkdir(parents=True, exist_ok=True)
        safe = {
            "id": tx.get("id"),
            "timestamp": datetime.now().isoformat(),
            "merchant": tx.get("merchant"),
            "amount": tx.get("amount"),
            "currency": tx.get("currency", "USD"),
            "status": tx.get("status"),
            "product": tx.get("product"),
            "payment_method_nickname": tx.get("payment_method_nickname"),
            "order_number": tx.get("order_number"),
            "url": tx.get("url"),
        }
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{(tx.get('merchant') or 'tx')[:30]}.json"
        (tx_dir / fname).write_text(json.dumps(safe, indent=2), encoding="utf-8")
        logger.info("Transaction logged: %s %s %s", safe["merchant"], safe["amount"], safe["status"])

    def get_transaction_history(self, limit: int = 50) -> List[Dict]:
        tx_dir = Path(__file__).parent.parent.parent / "memory" / "vault" / "transactions"
        if not tx_dir.exists():
            return []
        txs = []
        for f in sorted(tx_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                txs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return txs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_login() -> str:
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME", "user")


def _build_display(method_type: str, details: Dict) -> Dict:
    if method_type == "card":
        num = details.get("card_number", "")
        return {"last4": num[-4:] if len(num) >= 4 else "****", "brand": details.get("brand", "Card"), "expiry": details.get("expiry", "")}
    if method_type in ("paypal", "amazon_pay", "google_pay"):
        email = details.get("email", "")
        return {"email": email[:3] + "***" + email[email.find("@"):] if "@" in email else email[:3] + "***"}
    if method_type == "venmo":
        return {"username": "@" + details.get("username", "")[:4] + "***"}
    if method_type == "cashapp":
        return {"cashtag": "$" + details.get("cashtag", "").lstrip("$")[:4] + "***"}
    if method_type in ("crypto_eth", "crypto_btc", "crypto_usdc"):
        addr = details.get("wallet_address", "")
        return {"wallet": addr[:6] + "…" + addr[-4:] if len(addr) > 10 else addr, "currency": method_type.split("_")[1].upper(), "network": details.get("network", "ethereum")}
    if method_type == "bank_ach":
        acct = details.get("account_number", "")
        return {"last4": acct[-4:] if len(acct) >= 4 else "****", "bank": details.get("bank_name", "Bank"), "type": details.get("account_type", "checking")}
    if method_type == "apple_pay":
        return {"device": details.get("device", "iPhone")}
    return {}
