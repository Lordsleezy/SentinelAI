"""Real provider workflow execution and autonomous verification."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.vision.workflows")


def _vault_secrets(provider_id: str) -> Dict[str, str]:
    try:
        from core.sentinelvision.vault.account_vault import AccountVault
        return AccountVault().get_credentials(provider_id)
    except Exception:
        return {}


def _env_or_vault(provider_id: str, *keys: str) -> Dict[str, str]:
    out = {}
    vault = _vault_secrets(provider_id)
    for k in keys:
        out[k] = os.getenv(k) or vault.get(k.lower()) or vault.get(k) or ""
    return out


class ProviderWorkflowRunner:
    """Executes provider-specific workflow steps with real API/CLI checks."""

    def execute_step(self, provider_id: str, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type") or ""
        handler = getattr(self, f"_step_{provider_id}", None)
        if handler:
            return handler(step, operators)
        return self._step_generic(provider_id, step, operators)

    def verify_autonomous(self, provider_id: str, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        handler = getattr(self, f"_verify_{provider_id}", None)
        if handler:
            return handler(objective, context)
        return {"ok": False, "verified": False, "checks": [], "message": "no autonomous verify"}

    def health_check(self, provider_id: str) -> Dict[str, Any]:
        handler = getattr(self, f"_health_{provider_id}", None)
        if handler:
            return handler()
        return {"provider_id": provider_id, "connected": False, "message": "no health probe"}

    # ── Supabase ──────────────────────────────────────────────────────────────

    def _step_supabase(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        env = _env_or_vault("supabase", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
        url = env.get("SUPABASE_URL", "").rstrip("/")
        key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY", "")

        if atype == "supabase_verify_rest":
            if not url or not key:
                return {"ok": False, "error": "SUPABASE_URL and key required in vault or environment"}
            import httpx
            r = httpx.get(
                f"{url}/rest/v1/",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=15.0,
            )
            return {"ok": r.status_code in (200, 204), "status": r.status_code, "message": "REST reachable"}

        if atype == "supabase_check_env":
            missing = [k for k, v in env.items() if not v]
            return {"ok": not missing, "configured": [k for k, v in env.items() if v], "missing": missing}

        if atype == "browser_navigate" and operators.browser.available:
            return operators.browser.open_url("https://supabase.com/dashboard/projects")
        return {"ok": True, "action": atype, "note": "supabase step logged"}

    def _verify_supabase(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        checks = []
        env = _env_or_vault("supabase", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
        checks.append({"name": "env_configured", "ok": bool(env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"))})
        rest = self._step_supabase({"action_type": "supabase_verify_rest"}, None)
        checks.append({"name": "rest_api", "ok": rest.get("ok", False), "detail": rest.get("message", rest.get("error"))})
        verified = all(c["ok"] for c in checks)
        return {"ok": verified, "verified": verified, "checks": checks, "message": "Supabase autonomous verification"}

    def _health_supabase(self) -> Dict[str, Any]:
        env = _env_or_vault("supabase", "SUPABASE_URL", "SUPABASE_ANON_KEY")
        connected = bool(env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"))
        return {"provider_id": "supabase", "connected": connected, "message": "keys configured" if connected else "missing keys"}

    # ── Stripe ────────────────────────────────────────────────────────────────

    def _step_stripe(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        key = _env_or_vault("stripe", "STRIPE_SECRET_KEY").get("STRIPE_SECRET_KEY", "")
        if atype == "stripe_verify_api":
            if not key:
                return {"ok": False, "error": "STRIPE_SECRET_KEY required"}
            import httpx
            r = httpx.get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15.0,
            )
            return {"ok": r.status_code == 200, "status": r.status_code}
        if atype == "stripe_list_webhooks":
            if not key:
                return {"ok": False, "error": "STRIPE_SECRET_KEY required"}
            import httpx
            r = httpx.get(
                "https://api.stripe.com/v1/webhook_endpoints",
                headers={"Authorization": f"Bearer {key}"},
                params={"limit": 5},
                timeout=15.0,
            )
            data = r.json() if r.status_code == 200 else {}
            count = len(data.get("data", []))
            return {"ok": True, "webhook_count": count, "has_webhook": count > 0}
        return {"ok": True, "action": atype}

    def _verify_stripe(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        checks = []
        api = self._step_stripe({"action_type": "stripe_verify_api"}, None)
        checks.append({"name": "api_key", "ok": api.get("ok", False)})
        wh = self._step_stripe({"action_type": "stripe_list_webhooks"}, None)
        checks.append({"name": "webhooks", "ok": wh.get("has_webhook", False) or "webhook" not in objective.lower()})
        verified = all(c["ok"] for c in checks)
        return {"ok": verified, "verified": verified, "checks": checks}

    def _health_stripe(self) -> Dict[str, Any]:
        key = bool(_env_or_vault("stripe", "STRIPE_SECRET_KEY").get("STRIPE_SECRET_KEY"))
        return {"provider_id": "stripe", "connected": key, "message": "API key set" if key else "missing STRIPE_SECRET_KEY"}

    # ── Netlify ───────────────────────────────────────────────────────────────

    def _step_netlify(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        token = _env_or_vault("netlify", "NETLIFY_AUTH_TOKEN").get("NETLIFY_AUTH_TOKEN", "")
        if atype == "netlify_verify_token":
            if not token:
                return {"ok": False, "error": "NETLIFY_AUTH_TOKEN required"}
            import httpx
            r = httpx.get(
                "https://api.netlify.com/api/v1/sites",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
            return {"ok": r.status_code == 200, "sites": len(r.json()) if r.status_code == 200 else 0}
        if atype == "netlify_deploy_check" and operators.desktop:
            return operators.desktop.run_command("netlify status", timeout=60)
        return {"ok": True, "action": atype}

    def _verify_netlify(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        tok = self._step_netlify({"action_type": "netlify_verify_token"}, None)
        checks = [{"name": "auth_token", "ok": tok.get("ok", False)}]
        verified = all(c["ok"] for c in checks)
        return {"ok": verified, "verified": verified, "checks": checks}

    def _health_netlify(self) -> Dict[str, Any]:
        ok = bool(_env_or_vault("netlify", "NETLIFY_AUTH_TOKEN").get("NETLIFY_AUTH_TOKEN"))
        return {"provider_id": "netlify", "connected": ok, "message": "token set" if ok else "missing token"}

    # ── GitHub ────────────────────────────────────────────────────────────────

    def _step_github(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        token = _env_or_vault("github", "GITHUB_TOKEN").get("GITHUB_TOKEN", "")
        if atype == "github_verify_token":
            if not token:
                return {"ok": False, "error": "GITHUB_TOKEN required"}
            import httpx
            r = httpx.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=15.0,
            )
            login = r.json().get("login") if r.status_code == 200 else None
            return {"ok": r.status_code == 200, "login": login}
        return {"ok": True, "action": atype}

    def _verify_github(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        v = self._step_github({"action_type": "github_verify_token"}, None)
        checks = [{"name": "github_auth", "ok": v.get("ok", False)}]
        verified = all(c["ok"] for c in checks)
        return {"ok": verified, "verified": verified, "checks": checks}

    def _health_github(self) -> Dict[str, Any]:
        ok = bool(_env_or_vault("github", "GITHUB_TOKEN").get("GITHUB_TOKEN"))
        return {"provider_id": "github", "connected": ok, "message": "token set" if ok else "missing GITHUB_TOKEN"}

    # ── Cloudflare / Resend / Amazon ──────────────────────────────────────────

    def _health_cloudflare(self) -> Dict[str, Any]:
        tok = bool(_env_or_vault("cloudflare", "CLOUDFLARE_API_TOKEN").get("CLOUDFLARE_API_TOKEN"))
        return {"provider_id": "cloudflare", "connected": tok, "message": "API token set" if tok else "missing token"}

    def _health_resend(self) -> Dict[str, Any]:
        tok = bool(_env_or_vault("resend", "RESEND_API_KEY").get("RESEND_API_KEY"))
        return {"provider_id": "resend", "connected": tok, "message": "API key set" if tok else "missing key"}

    def _health_google(self) -> Dict[str, Any]:
        cred = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or _vault_secrets("google"))
        return {"provider_id": "google", "connected": cred, "message": "credentials present" if cred else "not configured"}

    def _health_amazon(self) -> Dict[str, Any]:
        vault = _vault_secrets("amazon")
        return {"provider_id": "amazon", "connected": bool(vault), "message": "vault entries" if vault else "connect Amazon in vault"}

    def _step_amazon(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        if atype == "amazon_search" and operators.browser.available:
            query = step.get("params", {}).get("query", "product")
            url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
            return operators.browser.open_url(url)
        if atype == "purchase":
            return {"ok": False, "error": "purchase requires approval gate", "requires_approval": True}
        return {"ok": True, "action": atype}

    def _verify_amazon(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        receipt = context.get("receipt_path") or context.get("order_id")
        if "order" in objective.lower() or "buy" in objective.lower():
            return {"ok": bool(receipt), "verified": bool(receipt), "checks": [{"name": "receipt", "ok": bool(receipt)}]}
        return {"ok": True, "verified": True, "checks": []}

    def _step_generic(self, provider_id: str, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        atype = step.get("action_type", "")
        if atype == "browser_navigate" and operators.browser.available:
            return operators.browser.open_url(step.get("params", {}).get("url", "about:blank"))
        if atype == "desktop_command" and operators.desktop:
            return operators.desktop.run_command(step.get("params", {}).get("command", "echo ok"))
        return {"ok": True, "provider": provider_id, "action": atype}


_workflow_runner: Optional[ProviderWorkflowRunner] = None


def get_workflow_runner() -> ProviderWorkflowRunner:
    global _workflow_runner
    if _workflow_runner is None:
        _workflow_runner = ProviderWorkflowRunner()
    return _workflow_runner
