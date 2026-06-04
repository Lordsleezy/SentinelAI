"""
Unified Router — the single source of intent classification for Sentinel chat.

User always talks to Sentinel; internal engines:
    guardian | forge | earn | earn_research | memory | market | home | general

This module owns ALL of the keyword lists. Callers (api_chat,
SentinelCapabilityRouter, etc.) must not maintain parallel copies — see the
2026 audit if you're tempted to reintroduce one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class RouteDecision:
    """Internal routing decision. user_facing is always Sentinel."""

    internal_engine: str
    confidence: float
    requires_approval: bool = False
    execute: bool = False
    reason: str = ""
    extracted_target: str = ""

    @property
    def user_facing(self) -> str:
        return "sentinel"


_FORGE_KW = (
    "write a", "write me", "build a", "build me", "create a", "create me",
    "implement", "debug", "fix the", "fix my", "refactor",
    "python function", "python script", "javascript", "bash script",
    "new function", "new class", "new module", "new worker", "def ",
    "import ", "code to", "script to", "program to", "snippet", "flappy",
)

_GUARDIAN_KW = (
    "scan ", "pentest", "recon ", "subdomain", "nuclei", "guardian",
    "security scan", "vulnerability", "assess ", "enumerate ",
    "sentinelprime", "bug bounty target",
)

_EARN_RESEARCH_KW = ("research ", "investigate program", "analyze program", "bounty research")

_EARN_KW = (
    "bounty", "bug bounty", "bounties", "freelance", "remote job",
    "find jobs", "find work", "hackerone", "bugcrowd", "upwork",
    "earn money", "earn online", "paid task",
)

_MARKET_KW = (
    "bitcoin price", "eth price", "crypto price", "stock price",
    "btc price", "bitcoin", "ethereum price", "market cap",
    "market data", "trading view", "chart for",
)

_HOME_KW = (
    "turn on", "turn off", "switch on", "switch off",
    "lights", "thermostat", "home automation", "smart home",
    "home assistant", "lock the", "unlock the", "dim the",
    "fan on", "fan off", "air conditioning", "temperature to",
)

# Memory recall / save intents. Used to short-circuit to memory_v2.recall
# before generic intent classification.
_MEMORY_KW = (
    "remember this", "save to memory", "recall ", "search memory",
    "what do you remember", "memory about", "forget ",
)

# Explicit "run guardian" phrasing that should jump straight to a security
# assessment instead of waiting for the generic guardian-scan keywords.
_GUARDIAN_EXPLICIT_KW = (
    "analyze this target", "run guardian", "guardian assessment",
    "security assessment", "enumerate subdomains",
)

# Verbs that look like unknown-capability requests when no other engine matches.
_UNKNOWN_TASK_VERBS = re.compile(
    r"\b(make|create|install|deploy|convert|integrate)\b", re.I,
)

# Words that prove the message *did* match an engine signal already and should
# not be re-promoted to the learning engine.
_UNKNOWN_TASK_EXCLUDE = (
    "scan", "build", "research", "bounty", "price", "hello", "hi ",
)


def _extract_scan_target(message: str) -> str:
    """Best-effort target from 'scan example.com' style messages."""
    m = re.search(
        r"(?:scan|pentest|recon|assess|enumerate)\s+(?:target\s+)?([a-zA-Z0-9][-a-zA-Z0-9._]{1,253})",
        message,
        re.I,
    )
    if m:
        return m.group(1).strip().rstrip(".")
    m = re.search(r"(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9._]+\.[a-z]{2,})", message)
    return m.group(1) if m else ""


def _extract_research_program(message: str) -> str:
    m = re.search(r"research\s+(.+)", message, re.I)
    if m:
        return m.group(1).strip()[:120]
    return ""


def looks_like_unknown_task(lower: str) -> bool:
    """True when the message reads like a request for a capability we don't have.

    Used by callers (e.g. SentinelCapabilityRouter) to promote an otherwise
    "general" classification into the learning engine.
    """
    if len(lower) < 12:
        return False
    if any(kw in lower for kw in _UNKNOWN_TASK_EXCLUDE):
        return False
    return bool(_UNKNOWN_TASK_VERBS.search(lower))


def classify_intent(message: str) -> RouteDecision:
    """
    Classify user message to internal engine.

    Priority order:
        memory > explicit-guardian > forge > guardian > earn_research >
        earn > market > home > general
    """
    lower = (message or "").lower().strip()
    if not lower:
        return RouteDecision("general", 0.0, reason="empty")

    if any(kw in lower for kw in _MEMORY_KW):
        return RouteDecision("memory", 0.8, execute=True, reason="memory intent")

    if any(kw in lower for kw in _GUARDIAN_EXPLICIT_KW):
        target = _extract_scan_target(message)
        return RouteDecision(
            "guardian", 0.88, execute=True,
            reason="explicit security assessment", extracted_target=target,
        )

    if any(kw in lower for kw in _FORGE_KW):
        return RouteDecision("forge", 0.9, requires_approval=True, reason="build keywords")

    if any(kw in lower for kw in _GUARDIAN_KW) or lower.startswith("scan "):
        target = _extract_scan_target(message)
        return RouteDecision(
            "guardian", 0.85, execute=True,
            reason="security scan intent", extracted_target=target,
        )

    if any(kw in lower for kw in _EARN_RESEARCH_KW):
        prog = _extract_research_program(message)
        return RouteDecision(
            "earn_research", 0.8, execute=bool(prog), reason="earn research",
            extracted_target=prog,
        )

    if any(kw in lower for kw in _EARN_KW):
        return RouteDecision("earn", 0.75, reason="earn keywords")

    if any(kw in lower for kw in _MARKET_KW):
        return RouteDecision("market", 0.7, reason="market keywords")

    if any(kw in lower for kw in _HOME_KW):
        return RouteDecision("home", 0.65, reason="home automation keywords")

    return RouteDecision("general", 0.3, reason="no strong signal")


def sentinel_response_prefix(engine: str) -> str:
    """Optional prefix — keep minimal so user feels one voice."""
    return ""  # Single voice; no "Guardian says:"
