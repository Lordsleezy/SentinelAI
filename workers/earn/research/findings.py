"""Potential findings from research plan + recon (no auto-submit)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

from workers.earn.research.models import FindingStatus, PotentialFinding, ResearchPlanItem, WorkflowStage


def _category_for(suggestion: str) -> str:
    low = suggestion.lower()
    if "idor" in low or "authorization" in low:
        return "access_control"
    if "graphql" in low or "introspection" in low or "schema" in low:
        return "api_graphql"
    if "xss" in low or "csrf" in low:
        return "web"
    if "oauth" in low or "session" in low:
        return "authentication"
    if "nuclei" in low:
        return "scanner"
    return "research"


def findings_from_plan(
    plans: List[ResearchPlanItem],
    nuclei_findings: List[Dict[str, Any]],
) -> List[PotentialFinding]:
    findings: List[PotentialFinding] = []

    for plan in plans:
        for sug in plan.suggested_research[:3]:
            findings.append(PotentialFinding(
                id=f"pf_{uuid.uuid4().hex[:8]}",
                title=f"Investigate {sug} on {plan.target}",
                target=plan.target,
                category=_category_for(sug),
                evidence=f"Detected: {', '.join(plan.detected[:6])}. Suggested from scope + technology mapping.",
                confidence=0.55 if "GraphQL" in plan.detected else 0.5,
                status=FindingStatus.IDEA.value,
                workflow_stage=WorkflowStage.IDEA.value,
                suggested_research=[sug],
                detected_technologies=plan.detected,
            ))

    for nf in nuclei_findings[:10]:
        findings.append(PotentialFinding(
            id=f"pf_{uuid.uuid4().hex[:8]}",
            title=f"Nuclei: {nf.get('template', 'finding')}",
            target=nf.get("target", ""),
            category="scanner",
            evidence=nf.get("description", "Nuclei template matched in-scope target"),
            confidence=0.72,
            status=FindingStatus.NEEDS_VALIDATION.value,
            workflow_stage=WorkflowStage.VALIDATION.value,
            suggested_research=["Manual validation required", "Capture request/response evidence"],
            detected_technologies=[],
        ))

    return findings[:40]
