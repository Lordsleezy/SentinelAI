"""Account operator — login, setup, credentials, environment configuration."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from core.sentinelvision.audit import audit_log
from core.sentinelvision.vault.account_vault import AccountVault

logger = logging.getLogger("sentinel.vision.account")


class AccountOperator:
    def __init__(self, vault: Optional[AccountVault] = None) -> None:
        self.vault = vault or AccountVault()

    def login(self, provider_id: str, operators: Any) -> Dict[str, Any]:
        """Browser login using vault credentials (never logged)."""
        creds = self.vault.get_credentials(provider_id)
        if not creds:
            return {"ok": False, "error": f"No credentials in vault for {provider_id}"}
        browser = operators.browser
        if not browser.available:
            return {"ok": False, "error": "Playwright required for login"}
        urls = {
            "amazon": "https://www.amazon.com/ap/signin",
            "stripe": "https://dashboard.stripe.com/login",
            "github": "https://github.com/login",
            "supabase": "https://supabase.com/dashboard",
            "netlify": "https://app.netlify.com",
            "cloudflare": "https://dash.cloudflare.com/login",
            "google": "https://accounts.google.com",
            "resend": "https://resend.com/login",
        }
        url = urls.get(provider_id, f"https://{provider_id}.com/login")
        browser.open_url(url)
        email = creds.get("email") or creds.get("username") or ""
        password = creds.get("password") or ""
        if email:
            browser.smart_fill(email, placeholder="email")
            browser.smart_fill(email, placeholder="Email")
        if password:
            browser.smart_fill(password, placeholder="password")
            browser.smart_fill(password, placeholder="Password")
        browser.smart_click(text="Sign in", vision_target="Sign in")
        audit_log("account_login_attempt", provider_id=provider_id, action="login")
        return {"ok": True, "message": "Login flow initiated", "provider_id": provider_id}

    def logout(self, provider_id: str, operators: Any) -> Dict[str, Any]:
        audit_log("account_logout", provider_id=provider_id)
        return {"ok": True, "message": "Logout recorded — clear session in browser"}

    def setup_account(self, provider_id: str, fields: Dict[str, str], label: Optional[str] = None) -> Dict[str, Any]:
        result = self.vault.register_provider_account(provider_id, fields, label=label)
        audit_log("account_setup", provider_id=provider_id, action="vault_register")
        return {"ok": True, **result}

    def configure_environment(self, provider_id: str, env_vars: Dict[str, str]) -> Dict[str, Any]:
        """Set process env vars for current session (deployment helpers)."""
        set_keys = []
        for k, v in env_vars.items():
            if v:
                os.environ[k] = v
                set_keys.append(k)
        audit_log("env_configure", provider_id=provider_id, action="set_env", detail=",".join(set_keys))
        return {"ok": True, "configured": set_keys}

    def rotate_credential(self, provider_id: str, field: str, new_value: str) -> Dict[str, Any]:
        return self.setup_account(provider_id, {field: new_value})

    def connection_status(self, provider_id: str) -> Dict[str, Any]:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().health_check(provider_id)
