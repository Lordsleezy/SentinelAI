"""Multi-step objective decomposition into sub-goals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SubGoalSpec:
    provider_id: str
    objective: str
    order: int


_LAUNCH_SENTINEL_CHAIN = [
    SubGoalSpec("github", "Verify GitHub repository and token access", 1),
    SubGoalSpec("supabase", "Verify Supabase project and database connectivity", 2),
    SubGoalSpec("stripe", "Verify Stripe API and webhook configuration", 3),
    SubGoalSpec("resend", "Verify Resend API key and domain setup", 4),
    SubGoalSpec("netlify", "Configure Netlify site and environment variables", 5),
    SubGoalSpec("netlify", "Deploy application to Netlify and verify build", 6),
    SubGoalSpec("supabase", "Verify auth enabled and schema deployed", 7),
    SubGoalSpec("stripe", "Test payment flow configuration", 8),
    SubGoalSpec("resend", "Test email delivery configuration", 9),
    SubGoalSpec("general", "Report launch readiness summary", 10),
]


def decompose_objective(objective: str) -> Optional[List[SubGoalSpec]]:
    lower = (objective or "").lower()
    if any(p in lower for p in ("launch sentinel", "deploy sentinel", "ship sentinel")):
        return list(_LAUNCH_SENTINEL_CHAIN)
    if "full stack" in lower and "setup" in lower:
        return [
            SubGoalSpec("github", "Connect GitHub", 1),
            SubGoalSpec("supabase", "Connect Supabase", 2),
            SubGoalSpec("stripe", "Connect Stripe", 3),
            SubGoalSpec("netlify", "Deploy to Netlify", 4),
        ]
    return None
