"""Layer 8 — AI safety: injection, tool abuse, exfiltration, credential access."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sentinel_security.config import SECURITY_STRICT

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"disregard\s+(your\s+)?(system|safety)",
    r"you\s+are\s+now\s+(in\s+)?(developer|admin|root)\s+mode",
    r"jailbreak",
    r"<\s*system\s*>",
    r"###\s*instruction",
]
_EXFIL_PATTERNS = [
    r"send\s+(all|the)\s+(files|data|secrets|credentials)\s+to",
    r"upload\s+.*\s+to\s+https?://",
    r"exfiltrat",
    r"post\s+.*\.env",
]
_CRED_PATTERNS = [
    r"read\s+.*\.env",
    r"dump\s+(all\s+)?(passwords|tokens|keys)",
    r"cat\s+.*id_rsa",
    r"aws_secret",
]
_PRIV_ESC = [
    r"run\s+as\s+root",
    r"sudo\s+",
    r"disable\s+(security|firewall|antivirus)",
    r"chmod\s+777",
]
_TOOL_ABUSE = [
    r"reverse\s+shell",
    r"bind\s+shell",
    r"meterpreter",
    r"rm\s+-rf\s+/",
]


@dataclass
class SafetyVerdict:
    allowed: bool
    blocked: bool
    reasons: List[str] = field(default_factory=list)
    risk_level: str = "low"


def analyze_text(text: str) -> SafetyVerdict:
    if not text:
        return SafetyVerdict(allowed=True, blocked=False)
    low = text.lower()
    reasons: List[str] = []
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, low, re.I):
            reasons.append(f"prompt_injection:{pat[:40]}")
    for pat in _EXFIL_PATTERNS:
        if re.search(pat, low, re.I):
            reasons.append("data_exfiltration")
    for pat in _CRED_PATTERNS:
        if re.search(pat, low, re.I):
            reasons.append("credential_access")
    for pat in _PRIV_ESC:
        if re.search(pat, low, re.I):
            reasons.append("privilege_escalation")
    for pat in _TOOL_ABUSE:
        if re.search(pat, low, re.I):
            reasons.append("tool_abuse")
    blocked = bool(reasons) and SECURITY_STRICT
    return SafetyVerdict(
        allowed=not blocked,
        blocked=blocked,
        reasons=reasons,
        risk_level="critical" if len(reasons) >= 2 else ("high" if reasons else "low"),
    )


def check_tool_invocation(module: str, tool: str, args: str, user_message: str = "") -> SafetyVerdict:
    combined = f"{user_message}\n{tool} {args}"
    verdict = analyze_text(combined)
    if verdict.blocked:
        return verdict
    dangerous_tools = {"metasploit", "msfconsole"}
    if tool.lower() in dangerous_tools and "exploit" in args.lower():
        verdict.reasons.append("dangerous_exploit_path")
        if SECURITY_STRICT:
            verdict.blocked = True
            verdict.allowed = False
    return verdict
