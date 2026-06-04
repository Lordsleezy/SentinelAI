"""Planner — convert research into executable plans."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

from core.sentinelvision.types import ExecutionPlan, PlanStep, utc_now


class VisionPlanner:
    def build_plan(
        self,
        goal_id: str,
        objective: str,
        provider_id: str,
        research: Dict[str, Any],
    ) -> ExecutionPlan:
        plan_id = str(uuid.uuid4())
        steps: List[PlanStep] = []
        idx = 0

        for action in research.get("required_actions") or research.get("summary", {}).get("required_actions") or []:
            idx += 1
            atype = self._infer_action_type(action)
            steps.append(PlanStep(
                step_id=f"s{idx}",
                action_type=atype,
                description=str(action),
                params={"provider_id": provider_id},
                requires_approval=atype in ("purchase", "payment", "account_create", "subscription", "credential_change"),
            ))

        if not steps:
            steps = self._default_steps(objective, provider_id)

        return ExecutionPlan(
            plan_id=plan_id,
            goal_id=goal_id,
            steps=steps,
            provider_id=provider_id,
            created_at=utc_now(),
        )

    @staticmethod
    def _infer_action_type(action: str) -> str:
        lower = action.lower()
        if any(w in lower for w in ("buy", "purchase", "order", "checkout")):
            return "purchase"
        if any(w in lower for w in ("pay", "payment", "stripe charge")):
            return "payment"
        if "login" in lower or "sign in" in lower:
            return "browser_login"
        if "deploy" in lower or "terminal" in lower or "cli" in lower:
            return "desktop_command"
        if "open" in lower and "http" in lower:
            return "browser_navigate"
        if "env" in lower or "variable" in lower or "api key" in lower:
            return "configure"
        return "execute"

    @staticmethod
    def _default_steps(objective: str, provider_id: str) -> List[PlanStep]:
        workflow_steps = {
            "supabase": [
                ("supabase_check_env", "Verify Supabase environment variables"),
                ("supabase_verify_rest", "Verify Supabase REST API connectivity"),
                ("browser_navigate", "Open Supabase dashboard", {"url": "https://supabase.com/dashboard"}),
            ],
            "stripe": [
                ("stripe_verify_api", "Verify Stripe API key"),
                ("stripe_list_webhooks", "Check Stripe webhook endpoints"),
            ],
            "netlify": [
                ("netlify_verify_token", "Verify Netlify auth token"),
                ("netlify_deploy_check", "Check Netlify deploy status"),
            ],
            "github": [
                ("github_verify_token", "Verify GitHub token and account"),
            ],
            "amazon": [
                ("amazon_search", "Search Amazon for product", {"query": objective}),
            ],
        }
        if provider_id in workflow_steps:
            steps = []
            for i, item in enumerate(workflow_steps[provider_id], 1):
                atype, desc = item[0], item[1]
                params = item[2] if len(item) > 2 else {}
                steps.append(PlanStep(
                    step_id=f"s{i}",
                    action_type=atype,
                    description=desc,
                    params=params,
                    requires_approval=atype == "purchase",
                ))
            steps.append(PlanStep(step_id=f"s{len(steps)+1}", action_type="verify", description="Autonomous verification", params={}))
            return steps
        return [
            PlanStep(
                step_id="s1",
                action_type="research_confirm",
                description=f"Confirm requirements for: {objective}",
                params={"provider_id": provider_id},
            ),
            PlanStep(
                step_id="s2",
                action_type="browser_navigate",
                description=f"Open {provider_id} dashboard or docs in browser",
                params={"url": f"https://{provider_id}.com" if provider_id not in ('amazon',) else "https://www.amazon.com"},
            ),
            PlanStep(
                step_id="s3",
                action_type="verify",
                description="Verify task outcome",
                params={},
            ),
        ]
