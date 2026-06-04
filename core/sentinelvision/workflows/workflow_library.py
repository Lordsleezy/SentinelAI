"""Workflow library — reusable templates for provider and deploy tasks."""
from __future__ import annotations

from typing import Any, Dict, List

from core.sentinelvision.playbooks.recorder import list_playbooks, load_playbook

BUILTIN_TEMPLATES: List[Dict[str, str]] = [
    {"id": "connect_supabase", "objective": "Connect Supabase", "provider_id": "supabase"},
    {"id": "connect_stripe", "objective": "Set up Stripe", "provider_id": "stripe"},
    {"id": "connect_netlify", "objective": "Connect Netlify", "provider_id": "netlify"},
    {"id": "deploy_sentinel", "objective": "Deploy Sentinel AI", "provider_id": "netlify"},
    {"id": "create_github_repo", "objective": "Create GitHub Repo", "provider_id": "github"},
    {"id": "configure_cloudflare", "objective": "Configure Cloudflare", "provider_id": "cloudflare"},
    {"id": "connect_resend", "objective": "Connect Resend", "provider_id": "resend"},
    {"id": "connect_google", "objective": "Connect Google", "provider_id": "google"},
    {"id": "connect_amazon", "objective": "Connect Amazon", "provider_id": "amazon"},
]


class WorkflowLibrary:
    def list_templates(self) -> List[Dict[str, Any]]:
        saved = {p.get("objective", "").lower(): p for p in list_playbooks()}
        out: List[Dict[str, Any]] = []
        for t in BUILTIN_TEMPLATES:
            entry = dict(t)
            pb = load_playbook(t["provider_id"], t["objective"])
            entry["has_playbook"] = pb is not None
            entry["saved"] = t["objective"].lower() in saved
            out.append(entry)
        for p in list_playbooks():
            if not any(p.get("objective") == t["objective"] for t in BUILTIN_TEMPLATES):
                out.append({
                    "id": p.get("path", ""),
                    "objective": p.get("objective", ""),
                    "provider_id": p.get("provider_id", ""),
                    "has_playbook": True,
                    "saved": True,
                })
        return out

    def resolve_template(self, message: str) -> Dict[str, str] | None:
        lower = message.lower()
        for t in BUILTIN_TEMPLATES:
            if t["id"].replace("_", " ") in lower or t["objective"].lower() in lower:
                return t
            if t["provider_id"] in lower:
                return t
        return None
