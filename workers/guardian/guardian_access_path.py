"""
Guardian Access Path Analysis — find bug/vulnerability-based ways in.

Explicitly excludes:
  - Password brute force / credential stuffing
  - Backdoor or persistence deployment

Uses recon + targeted Nuclei (RCE, SQLi, auth bypass, etc.) + correlation + AI synthesis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# User intent: access via weaknesses / bugs
ACCESS_PATH_KEYWORDS = (
    "find a way",
    "way to access",
    "way into",
    "get access",
    "gain access",
    "break in",
    "break into",
    "get into",
    "get in to",
    "access this network",
    "access this system",
    "access the network",
    "access the system",
    "exploit weakness",
    "exploiting weakness",
    "exploit vulnerabilities",
    "find a bug",
    "bug that allows",
    "allows you in",
    "allows me in",
    "initial access",
    "entry point",
    "how to get in",
    "path into",
    "vulnerability to access",
)

# If user explicitly wants access analysis without offensive techniques
NO_BRUTE_KEYWORDS = ("no brute", "without brute", "no password", "without password", "no hydra")
NO_BACKDOOR_KEYWORDS = ("no backdoor", "without backdoor", "no persistence")

ACCESS_NUCLEI_TAGS = (
    "rce,sqli,lfi,ssrf,xss,auth-bypass,unauth,exposure,cve,"
    "redirect,traversal,misconfig,default-login,token,oauth,idor"
)

ACCESS_TEMPLATE_HINTS = {
    "rce": ("rce", "remote-code", "command-injection", "cmd-injection", "exec"),
    "sqli": ("sqli", "sql-injection", "sql injection"),
    "auth_bypass": ("auth-bypass", "bypass", "unauth", "unauthenticated", "login"),
    "lfi": ("lfi", "file-read", "traversal", "path-traversal"),
    "ssrf": ("ssrf", "server-side-request"),
    "xss": ("xss", "cross-site-scripting"),
    "idor": ("idor", "insecure-direct"),
    "misconfig": ("misconfig", "exposure", "debug", "admin", "panel"),
    "cve": ("cve-", "cve_"),
}


@dataclass
class AccessVector:
    category: str
    severity: str
    template: str
    target: str
    description: str
    suggested_next_step: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "category": self.category,
            "severity": self.severity,
            "template": self.template,
            "target": self.target,
            "description": self.description,
            "suggested_next_step": self.suggested_next_step,
        }


@dataclass
class AccessPathResult:
    vectors: List[AccessVector] = field(default_factory=list)
    extra_nuclei_findings: List[Any] = field(default_factory=list)
    endpoints_reviewed: int = 0
    nuclei_access_hits: int = 0
    ai_plan: str = ""
    policy_note: str = (
        "Analysis uses vulnerability discovery only — no brute force, no backdoor deployment."
    )

    def to_markdown(self) -> str:
        lines = [
            "## Access Path Analysis",
            "",
            f"_{self.policy_note}_",
            "",
        ]
        if not self.vectors:
            lines.append(
                "No high-confidence vulnerability-based access paths were confirmed automatically. "
                "Review recon data and run manual validation on interesting endpoints."
            )
            return "\n".join(lines)

        lines.append(f"**{len(self.vectors)} potential access vector(s)** (prioritized):\n")
        for i, v in enumerate(self.vectors[:20], 1):
            lines.append(f"### {i}. {v.category.replace('_', ' ').title()} — `{v.template}`")
            lines.append(f"- **Severity:** {v.severity.upper()}")
            lines.append(f"- **Target:** `{v.target}`")
            lines.append(f"- **Finding:** {v.description[:300]}")
            if v.suggested_next_step:
                lines.append(f"- **Next step:** {v.suggested_next_step}")
            lines.append("")
        if self.ai_plan:
            lines += ["### Recommended exploitation research plan", "", self.ai_plan[:3500]]
        return "\n".join(lines)


def user_wants_access_path_analysis(message: str) -> bool:
    m = message.lower()
    return any(k in m for k in ACCESS_PATH_KEYWORDS)


def user_excludes_brute_force(message: str) -> bool:
    m = message.lower()
    return any(k in m for k in NO_BRUTE_KEYWORDS) or user_wants_access_path_analysis(message)


def user_excludes_backdoors(message: str) -> bool:
    m = message.lower()
    return any(k in m for k in NO_BACKDOOR_KEYWORDS) or user_wants_access_path_analysis(message)


def _classify_finding(template: str, description: str) -> Tuple[str, str]:
    blob = f"{template} {description}".lower()
    for category, hints in ACCESS_TEMPLATE_HINTS.items():
        if any(h in blob for h in hints):
            step = {
                "rce": "Validate command execution with a harmless PoC (e.g. id/uname); document for report.",
                "sqli": "Confirm with a single benign boolean/time-based test; capture request/response.",
                "auth_bypass": "Map bypass to privileged function; prove with one authorized-scope action.",
                "lfi": "Read a non-sensitive file path allowed by program rules; avoid /etc/shadow.",
                "ssrf": "Test internal metadata endpoints with program-approved payloads only.",
                "xss": "Demonstrate alert(1) or equivalent minimal PoC in scoped environment.",
                "idor": "Swap object IDs between two test accounts you control.",
                "misconfig": "Verify exposed panel/API; check for default creds via docs not brute force.",
                "cve": "Match installed version from httpx/headers; look up CVE exploit preconditions.",
            }.get(category, "Manual validation required.")
            return category, step
    return "other", "Review template output and chain with other findings."


def correlate_access_vectors(
    nuclei_findings: List[Any],
    zap_findings: List[Any],
    endpoints: List[str],
) -> List[AccessVector]:
    vectors: List[AccessVector] = []
    seen: set = set()

    for f in nuclei_findings or []:
        template = getattr(f, "template", "") or ""
        desc = getattr(f, "description", "") or ""
        sev = (getattr(f, "severity", "info") or "info").lower()
        tgt = getattr(f, "target", "") or ""
        cat, step = _classify_finding(template, desc)
        if sev in ("info", "unknown") and cat == "other":
            continue
        key = (template, tgt)
        if key in seen:
            continue
        seen.add(key)
        vectors.append(AccessVector(
            category=cat,
            severity=sev,
            template=template,
            target=tgt,
            description=desc,
            suggested_next_step=step,
        ))

    for zf in zap_findings or []:
        risk = (getattr(zf, "risk", "") or "").lower()
        if risk not in ("high", "critical", "medium"):
            continue
        alert = getattr(zf, "alert", "") or ""
        url = getattr(zf, "url", "") or ""
        cat, step = _classify_finding(alert, alert)
        key = ("zap", url, alert)
        if key in seen:
            continue
        seen.add(key)
        vectors.append(AccessVector(
            category=cat,
            severity="high" if risk in ("high", "critical") else "medium",
            template=f"ZAP:{alert}",
            target=url,
            description=alert,
            suggested_next_step=step,
        ))

    # Interesting endpoints without scanner hit
    for ep in endpoints[:30]:
        low = ep.lower()
        if any(x in low for x in ("/admin", "/api/", "/login", "/graphql", "/debug", "/.env", "/config")):
            key = ("ep", ep)
            if key not in seen:
                seen.add(key)
                vectors.append(AccessVector(
                    category="misconfig",
                    severity="low",
                    template="endpoint-discovery",
                    target=ep,
                    description="Sensitive path discovered during crawl — manual review recommended.",
                    suggested_next_step="Probe for auth requirements and IDOR/auth bypass manually.",
                ))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "unknown": 5}
    vectors.sort(key=lambda v: (order.get(v.severity, 9), v.category))
    return vectors


def run_access_nuclei_scan(tools: Any, url: str) -> List[Any]:
    """Extra Nuclei pass focused on access-enabling vulnerability tags."""
    if not tools or not getattr(tools, "nuclei", None):
        return []
    nuclei = tools.nuclei
    if not nuclei.is_available():
        return []
    res = nuclei.scan(
        url,
        severity=["critical", "high", "medium"],
        tags=ACCESS_NUCLEI_TAGS,
    )
    return list(res.findings or []) if res.success else []


def synthesize_access_plan(
    target: str,
    vectors: List[AccessVector],
    context: str,
) -> str:
    from workers.guardian.guardian_runtime_manager import generate

    vec_text = "\n".join(
        f"- [{v.severity}] {v.category}: {v.template} @ {v.target} — {v.description[:120]}"
        for v in vectors[:15]
    ) or "No automated vectors yet."
    system = (
        "You are Guardian Access Path Analyst. The operator wants to find how to gain access "
        "via security bugs on an AUTHORIZED target. "
        "Never recommend brute force, password spraying, or installing backdoors/persistence. "
        "Recommend: validation steps, exploit preconditions, chaining bugs, and bug-bounty-style PoC."
    )
    prompt = (
        f"Target: {target}\n\n"
        f"Confirmed/potential vectors:\n{vec_text}\n\n"
        f"Recon context:\n{context[:4000]}\n\n"
        "Produce:\n"
        "1) Most likely path to access (ordered)\n"
        "2) Exact validation steps per path (minimal, ethical)\n"
        "3) What evidence to capture for a bounty report\n"
        "4) Dead ends ruled out\n"
    )
    return generate(prompt, system=system, task_label="access path planning")


def run_access_path_analysis(
    target: str,
    *,
    tools: Any,
    nuclei_findings: List[Any],
    zap_findings: List[Any],
    endpoints: List[str],
    live_hosts: List[str],
    results: Dict[str, Any],
    log_fn: Optional[Any] = None,
) -> AccessPathResult:
    out = AccessPathResult(endpoints_reviewed=len(endpoints))

    extra: List[Any] = []
    primary = live_hosts[0] if live_hosts else (
        target if target.startswith("http") else f"https://{target}"
    )
    if log_fn:
        log_fn("[GUARDIAN] Access path: targeted Nuclei (RCE/SQLi/auth bypass tags)", "info")
    try:
        extra = run_access_nuclei_scan(tools, primary)
        out.nuclei_access_hits = len(extra)
        out.extra_nuclei_findings = extra
        results["access_nuclei"] = len(extra)
    except Exception as e:
        if log_fn:
            log_fn(f"[GUARDIAN] Access Nuclei pass: {e}", "warning")

    combined = list(nuclei_findings or []) + extra
    out.vectors = correlate_access_vectors(combined, zap_findings, endpoints)

    ctx = (
        f"Subdomains/hosts: {len(live_hosts)}\n"
        f"Endpoints: {len(endpoints)}\n"
        f"Headers snippet: {str(results.get('headers', ''))[:400]}\n"
    )
    try:
        out.ai_plan = synthesize_access_plan(target, out.vectors, ctx)
    except Exception as e:
        out.ai_plan = f"Access plan synthesis unavailable: {e}"

    return out
