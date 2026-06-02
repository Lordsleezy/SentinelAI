"""Generate per-target research plans from scope + technologies."""
from __future__ import annotations

from typing import Dict, List

from workers.earn.hackerone_intel import ProgramIntel
from workers.earn.research.models import ResearchPlanItem
from workers.earn.research.tech_detect import HostTechnology


_GRAPHQL_RESEARCH = [
    "IDOR",
    "Authorization",
    "Schema exposure",
    "Introspection abuse",
    "Batch query abuse",
]
_API_RESEARCH = [
    "Broken object-level authorization",
    "Mass assignment",
    "Rate limiting bypass",
    "API versioning inconsistencies",
]
_WEB_RESEARCH = [
    "XSS (stored/reflected)",
    "CSRF on state-changing actions",
    "Access control on admin paths",
]
_AUTH_RESEARCH = [
    "OAuth redirect manipulation",
    "Session fixation",
    "Token leakage in referrers",
]


def build_research_plan(
    intel: ProgramIntel,
    host_tech: List[HostTechnology],
) -> List[ResearchPlanItem]:
    plans: List[ResearchPlanItem] = []
    by_url = {h.url: h for h in host_tech}

    for asset in intel.in_scope:
        if not asset.eligible_for_bounty:
            continue
        target = asset.identifier
        if not target.startswith("http") and "." in target:
            target = f"https://{target.split('/')[0]}"

        detected: List[str] = [asset.category, asset.asset_type]
        suggestions: List[str] = []

        ht = by_url.get(target) or by_url.get(target.rstrip("/"))
        if ht:
            detected.extend(ht.framework + ht.cms + ht.cloud + ht.auth + ht.api_tech)

        if asset.category == "api" or "graphql" in " ".join(detected).lower():
            suggestions.extend(_GRAPHQL_RESEARCH)
        elif asset.category == "authentication" or any(a in detected for a in ("oauth", "auth0", "okta", "saml")):
            suggestions.extend(_AUTH_RESEARCH)
        elif asset.category == "mobile":
            suggestions.extend(["Mobile API IDOR", "Deep link abuse", "Insecure local storage"])
        else:
            suggestions.extend(_WEB_RESEARCH)

        if "cloudflare" in detected:
            suggestions.append("Origin IP discovery (authorized testing only)")
        suggestions = list(dict.fromkeys(suggestions))[:8]

        plans.append(ResearchPlanItem(
            target=target,
            detected=list(dict.fromkeys(detected))[:12],
            suggested_research=suggestions,
        ))

    # Hosts discovered by recon not in explicit asset list
    for ht in host_tech:
        if any(p.target == ht.url for p in plans):
            continue
        sug = list(_GRAPHQL_RESEARCH) if "GraphQL" in ht.api_tech else list(_WEB_RESEARCH)
        plans.append(ResearchPlanItem(
            target=ht.url,
            detected=ht.framework + ht.cms + ht.cloud + ht.api_tech,
            suggested_research=sug[:6],
        ))

    return plans[:30]
