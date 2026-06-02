"""
Program-specific Earn report — attack surface map + prioritized recommendations.

Output reads like a researcher reviewed the actual HackerOne scope, not a generic checklist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from workers.earn.hackerone_intel import ProgramIntel, ScopeAsset


@dataclass
class Recommendation:
    title: str
    target: str
    asset_type: str
    category: str
    confidence: float  # 0.0–1.0
    evidence: str
    approach: str
    max_severity: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "target": self.target,
            "asset_type": self.asset_type,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "approach": self.approach,
            "max_severity": self.max_severity,
        }


def build_attack_surface_map(intel: ProgramIntel) -> Dict[str, List[ScopeAsset]]:
    """Group in-scope assets by testing category."""
    groups: Dict[str, List[ScopeAsset]] = {
        "mobile": [],
        "api": [],
        "commerce": [],
        "ads_partners": [],
        "file_upload": [],
        "authentication": [],
        "cms_admin": [],
        "messaging": [],
        "web_general": [],
    }
    for a in intel.in_scope:
        if not a.eligible_for_bounty:
            continue
        key = a.category if a.category in groups else "web_general"
        groups[key].append(a)
    return {k: v for k, v in groups.items() if v}


def _conf(base: float, asset: ScopeAsset, extra: float = 0.0) -> float:
    sev_boost = {"critical": 0.08, "high": 0.05, "medium": 0.0, "low": -0.05}.get(asset.max_severity, 0)
    return min(0.98, max(0.45, base + sev_boost + extra))


def _rec(
    title: str,
    asset: ScopeAsset,
    category: str,
    confidence: float,
    evidence: str,
    approach: str,
) -> Recommendation:
    return Recommendation(
        title=title,
        target=asset.identifier,
        asset_type=asset.asset_type,
        category=category,
        confidence=confidence,
        evidence=evidence,
        approach=approach,
        max_severity=asset.max_severity,
    )


def generate_recommendations(intel: ProgramIntel) -> List[Recommendation]:
    """Asset-tied recommendations with confidence + evidence."""
    recs: List[Recommendation] = []
    surface = build_attack_surface_map(intel)

    for asset in surface.get("mobile", []):
        platform = "Android" if "AOS" in asset.identifier.upper() or "GOOGLE" in asset.asset_type else "iOS"
        if "AOS" in asset.identifier.upper() or asset.asset_type == "GOOGLE_PLAY_APP_ID":
            platform = "Android"
        elif "IOS" in asset.identifier.upper() or asset.asset_type == "APPLE_STORE_APP_ID":
            platform = "iOS"
        recs.append(_rec(
            f"{platform} deep-link and intent-filter testing on {asset.identifier}",
            asset,
            "mobile",
            _conf(0.86, asset),
            f"In-scope {asset.asset_type} '{asset.identifier}' (severity: {asset.max_severity}). "
            f"{'Store link: ' + asset.instruction[:80] if asset.instruction else 'Mobile surface explicitly listed.'}",
            "Test custom URL schemes, App Links/Universal Links, exported components, and "
            "parameter injection via deep links into authenticated WebViews.",
        ))
        recs.append(_rec(
            f"Mobile API authorization and session token handling ({asset.identifier})",
            asset,
            "mobile",
            _conf(0.84, asset),
            f"Mobile app in scope — API calls from {asset.identifier} typically share backend hosts "
            f"also listed in web scope ({len(surface.get('api', []))} API assets on program).",
            "Intercept traffic from the app; replay mobile tokens against web/API endpoints; test "
            "refresh-token rotation, logout invalidation, and cross-account IDOR on mobile-specific headers.",
        ))

    for asset in surface.get("api", [])[:18]:
        host = asset.identifier
        recs.append(_rec(
            f"Broken object-level authorization on {host}",
            asset,
            "api",
            _conf(0.82, asset),
            f"In-scope API URL '{host}' ({asset.asset_type}, max severity {asset.max_severity}).",
            "Map object IDs in cart/checkout/account APIs; swap IDs between two test accounts; "
            "probe GraphQL/REST batch endpoints for mass assignment.",
        ))
        if "cart" in host or "checkout" in host:
            recs.append(_rec(
                f"Business logic abuse on commerce API {host}",
                asset,
                "commerce",
                _conf(0.8, asset, 0.03),
                f"Commerce/API host '{host}' in scope — paired with checkout/cart surfaces.",
                "Price tampering, coupon stacking, negative quantities, race conditions on "
                "inventory holds, and payment-step parameter manipulation.",
            ))

    for asset in surface.get("ads_partners", [])[:10]:
        recs.append(_rec(
            f"Open redirect and partner callback abuse on {asset.identifier}",
            asset,
            "ads_partners",
            _conf(0.79, asset),
            f"Ads/partner domain '{asset.identifier}' listed in-scope (severity {asset.max_severity}).",
            "Test redirect_uri validation, click-tracking parameters, SSRF via partner webhooks, "
            "and subdomain takeover if DNS points to third parties.",
        ))

    for asset in surface.get("commerce", [])[:12]:
        if any(r.target == asset.identifier for r in recs):
            continue
        recs.append(_rec(
            f"Checkout/cart workflow tampering on {asset.identifier}",
            asset,
            "commerce",
            _conf(0.81, asset),
            f"Commerce surface '{asset.identifier}' in program scope ({asset.max_severity}).",
            "Multi-step checkout bypass, shipping/payment option manipulation, and "
            "session fixation across cart → checkout → payment hosts.",
        ))

    for asset in surface.get("file_upload", [])[:8]:
        recs.append(_rec(
            f"Unrestricted upload and content-type bypass on {asset.identifier}",
            asset,
            "file_upload",
            _conf(0.77, asset),
            f"Upload endpoint '{asset.identifier}' in-scope ({asset.asset_type}).",
            "Polyglot files, SVG/HTML in image pipelines, oversized payloads, and "
            "path traversal in object storage keys.",
        ))

    for asset in surface.get("authentication", [])[:8]:
        recs.append(_rec(
            f"OAuth/session token lifecycle on {asset.identifier}",
            asset,
            "authentication",
            _conf(0.83, asset),
            f"Authentication-related asset '{asset.identifier}' explicitly in scope.",
            "Test refresh reuse after logout, token binding to device/IP, scope escalation in "
            "OAuth consent, and password-reset token entropy.",
        ))

    for asset in surface.get("cms_admin", [])[:6]:
        recs.append(_rec(
            f"Privileged workflow exposure on {asset.identifier}",
            asset,
            "cms_admin",
            _conf(0.74, asset),
            f"Admin/CMS host '{asset.identifier}' in scope — often higher impact.",
            "Test role separation, draft/publish IDOR, SSRF from CMS importers, and "
            "stored XSS reaching operators.",
        ))

    # High-value web assets not yet covered
    covered = {r.target for r in recs}
    for asset in intel.in_scope:
        if not asset.eligible_for_bounty or asset.identifier in covered:
            continue
        if len(recs) >= 28:
            break
        recs.append(_rec(
            f"Targeted recon and authz testing on {asset.identifier}",
            asset,
            asset.category or "web_general",
            _conf(0.7, asset),
            f"Residual in-scope asset '{asset.identifier}' ({asset.asset_type}, {asset.max_severity}).",
            "Baseline: subdomain enumeration, authenticated crawl, CORS, cache poisoning, "
            "and header-based bypasses specific to this host.",
        ))

    recs.sort(key=lambda r: (-r.confidence, {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.max_severity, 4)))
    return recs[:25]


def render_markdown_report(
    intel: ProgramIntel,
    surface_map: Dict[str, List[ScopeAsset]],
    recommendations: List[Recommendation],
) -> str:
    lines: List[str] = [
        f"# Program-Specific Bug Bounty Analysis: {intel.name}",
        "",
        f"**Program handle:** `{intel.handle}`  ",
        f"**Policy URL:** {intel.url}  ",
        f"**Website:** {intel.website or '—'}  ",
        f"**Submission state:** {intel.submission_state}  ",
        f"**Bounty range (derived):** {intel.bounty_range_display}  ",
        "",
        "> This report is generated from parsed HackerOne scope data (bounty-targets-data), "
        "not a generic vulnerability checklist.",
        "",
    ]

    if intel.parse_warnings:
        lines.append("## Parse Notes")
        for w in intel.parse_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Bounty Ranges (by severity)")
    for sev, val in intel.bounty_by_severity.items():
        lines.append(f"- **{sev.title()}:** {val}")
    if intel.avg_days_to_bounty is not None:
        lines.append(f"- **Avg. days to bounty (program stat):** {intel.avg_days_to_bounty}")
    lines.append("")

    lines.append("## In-Scope Assets")
    lines.append(f"**Total in-scope:** {len(intel.in_scope)} | **Bounty-eligible:** "
                  f"{sum(1 for a in intel.in_scope if a.eligible_for_bounty)} | "
                  f"**Mobile:** {len(intel.mobile_targets)} | **Web/other:** {len(intel.web_targets)}")
    lines.append("")
    lines.append("| Asset | Type | Severity | Category |")
    lines.append("|-------|------|----------|----------|")
    for a in intel.in_scope[:60]:
        lines.append(
            f"| `{a.identifier}` | {a.asset_type} | {a.max_severity} | {a.category} |"
        )
    if len(intel.in_scope) > 60:
        lines.append(f"| … | +{len(intel.in_scope) - 60} more | | |")
    lines.append("")

    if intel.out_of_scope:
        lines.append("## Out-of-Scope Assets")
        lines.append(f"**Count:** {len(intel.out_of_scope)} — do not report findings on these.")
        lines.append("")
        for a in intel.out_of_scope[:25]:
            lines.append(f"- `{a.identifier}` ({a.asset_type})")
        if len(intel.out_of_scope) > 25:
            lines.append(f"- … +{len(intel.out_of_scope) - 25} more")
        lines.append("")

    lines.append("## Known Exclusions")
    for ex in intel.exclusions:
        lines.append(f"- {ex}")
    lines.append("")

    lines.append("## Authentication Requirements")
    for note in intel.authentication_notes:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## Attack Surface Map")
    _labels = {
        "mobile": "Mobile applications",
        "api": "APIs & backend services",
        "commerce": "Commerce / checkout",
        "ads_partners": "Ads & partner integrations",
        "file_upload": "File upload & media",
        "authentication": "Authentication & session",
        "cms_admin": "CMS / admin / internal",
        "messaging": "Feeds & messaging",
        "web_general": "General web",
    }
    for key, assets in sorted(surface_map.items(), key=lambda x: -len(x[1])):
        label = _labels.get(key, key.replace("_", " ").title())
        lines.append(f"### {label} ({len(assets)})")
        for a in assets[:15]:
            lines.append(f"- `{a.identifier}` — {a.asset_type}, **{a.max_severity}**")
        if len(assets) > 15:
            lines.append(f"- … +{len(assets) - 15} more")
        lines.append("")

    lines.append("## Prioritized Recommendations")
    lines.append("Each item is tied to an in-scope asset with confidence and evidence.")
    lines.append("")
    for i, r in enumerate(recommendations, 1):
        lines.extend([
            f"### {i}. {r.title}",
            f"- **Confidence:** {r.confidence:.0%}",
            f"- **Target:** `{r.target}` ({r.asset_type})",
            f"- **Category:** {r.category}",
            f"- **Evidence:** {r.evidence}",
            f"- **Approach:** {r.approach}",
            "",
        ])

    lines.append("## Recon Plan (program-specific)")
    api_first = [a.identifier for a in surface_map.get("api", [])[:8]]
    mobile_first = [a.identifier for a in surface_map.get("mobile", [])]
    if mobile_first:
        lines.append(f"1. Configure mobile proxy for {', '.join(mobile_first)} — capture API host list from traffic.")
    if api_first:
        lines.append(f"2. Map authorization on API hosts: {', '.join(api_first)}.")
    lines.append("3. Spider each unique in-scope hostname; diff authenticated vs unauthenticated responses.")
    lines.append("4. Cross-check any finding hostname against **Out-of-Scope** before submission.")
    lines.append("")

    return "\n".join(lines)


def build_program_report(intel: ProgramIntel) -> Tuple[str, List[Recommendation], Dict[str, List[ScopeAsset]]]:
    surface = build_attack_surface_map(intel)
    recs = generate_recommendations(intel)
    md = render_markdown_report(intel, surface, recs)
    return md, recs, surface
