"""Provider onboarding — detect, guide, vault, verify, create playbook."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from core.sentinelvision.operator.account_operator import AccountOperator
from core.sentinelvision.playbooks.recorder import load_playbook, save_playbook
from core.sentinelvision.planner.planner import VisionPlanner
from core.sentinelvision.planner.research import ResearchEngine
from core.sentinelvision.providers.registry import get_provider, resolve_provider
from core.sentinelvision.providers.workflows import get_workflow_runner

logger = logging.getLogger("sentinel.vision.onboarding")

ONBOARDING_PROVIDERS = (
    "supabase", "stripe", "github", "cloudflare", "netlify", "resend", "google", "amazon",
)

TEMPLATE_OBJECTIVES = {
    "supabase": "Connect Supabase",
    "stripe": "Set up Stripe",
    "github": "Connect GitHub",
    "cloudflare": "Configure Cloudflare",
    "netlify": "Connect Netlify",
    "resend": "Connect Resend",
    "google": "Connect Google",
    "amazon": "Connect Amazon",
}


class ProviderOnboardingEngine:
    def __init__(self, vision_engine: Any) -> None:
        self.engine = vision_engine
        self.research = ResearchEngine()
        self.planner = VisionPlanner()
        self.accounts = AccountOperator(vision_engine.vault)
        self.workflows = get_workflow_runner()

    def detect_missing(self, provider_id: str) -> Dict[str, Any]:
        health = self.workflows.health_check(provider_id)
        return {
            "provider_id": provider_id,
            "configured": health.get("connected", False),
            "message": health.get("message", ""),
            "needs_onboarding": not health.get("connected", False),
        }

    def onboard_provider(
        self,
        provider_id: str,
        *,
        objective: Optional[str] = None,
        credentials: Optional[Dict[str, str]] = None,
        emit: Optional[Callable[..., None]] = None,
    ) -> Dict[str, Any]:
        """
        Full onboarding: store creds → verify health → run goal → save playbook template.
        """
        pid = provider_id.lower()
        if pid not in ONBOARDING_PROVIDERS:
            return {"ok": False, "error": f"unsupported provider: {pid}"}

        obj = objective or TEMPLATE_OBJECTIVES.get(pid, f"Connect {pid}")
        _emit = emit or (lambda *_: None)

        status = self.detect_missing(pid)
        if status.get("configured") and not credentials:
            _emit("onboarding", f"{pid} already configured", "info")
            return {"ok": True, "already_configured": True, "health": status}

        if credentials:
            self.accounts.setup_account(pid, credentials, label=f"{pid} account")
            _emit("onboarding", f"Credentials stored for {pid}", "info")

        health = self.workflows.health_check(pid)
        if not health.get("connected") and pid != "amazon":
            _emit("onboarding", f"Configuration incomplete: {health.get('message')}", "warn")
            return {"ok": False, "health": health, "needs_credentials": True}

        goal = self.engine.submit_goal(obj, provider_id=pid)
        _emit("onboarding", f"Running onboarding goal: {obj}", "info")

        return {
            "ok": True,
            "goal_id": goal.goal_id,
            "objective": obj,
            "provider_id": pid,
            "health": health,
            "template": f"workflow_{pid}_connect",
        }

    def create_template_playbook(self, provider_id: str, objective: str, plan: Dict[str, Any], research: Dict[str, Any]) -> str:
        path = save_playbook(provider_id, objective, plan, research)
        return path

    def list_templates(self) -> list:
        from core.sentinelvision.playbooks.recorder import list_playbooks
        return list_playbooks()

    def resolve_onboarding_objective(self, message: str) -> Optional[str]:
        lower = message.lower()
        for pid, obj in TEMPLATE_OBJECTIVES.items():
            if pid in lower or obj.lower() in lower:
                return pid
        prov = resolve_provider(message)
        return prov.provider_id if prov else None
