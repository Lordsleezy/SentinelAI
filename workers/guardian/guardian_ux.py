"""Guardian UX helpers — conversational progress lines."""
from __future__ import annotations

import re
from typing import Optional


def humanize_progress(step: str, raw_message: str) -> str:
    """Turn pipeline markdown into ChatGPT-style status lines when possible."""
    s = (step or "").lower()
    text = raw_message or ""

    if s == "start":
        m = re.search(r"`([^`]+)`", text)
        t = m.group(1) if m else "the target"
        return f"Starting a security assessment of {t}. I'll post updates as each step completes."

    if "subfinder" in s or "subfinder" in text.lower():
        n = re.search(r"(\d+)\s+subdomain", text, re.I)
        if n:
            return f"Found {n.group(1)} subdomains."
        if "skipped" in text.lower():
            return "Subfinder isn't installed — continuing with other discovery tools."
        return "Running subdomain enumeration."

    if "amass" in s or "assetfinder" in s:
        n = re.search(r"(\d+)\s+", text)
        if n and "sub" in text.lower():
            return f"Discovered additional assets ({n.group(1)} new)."
        return "Expanding the asset list."

    if "httpx" in s:
        n = re.search(r"(\d+)\s+live", text, re.I)
        if n:
            return f"Identified {n.group(1)} live HTTP hosts."
        return "Probing web services and technologies."

    if "katana" in s:
        n = re.search(r"(\d+)\s+endpoint", text, re.I)
        if n:
            return f"Found {n.group(1)} endpoints while crawling."
        return "Crawling for endpoints."

    if "nuclei" in s:
        n = re.search(r"(\d+)\s+finding", text, re.I)
        if n:
            return f"Nuclei reported {n.group(1)} potential issues."
        return "Running vulnerability templates with Nuclei."

    if "zap" in s:
        n = re.search(r"(\d+)\s+alert", text, re.I)
        if n:
            return f"ZAP flagged {n.group(1)} alerts."
        return "Running passive application checks."

    if "access_path" in s or "access path" in text.lower():
        return "Analyzing vulnerability-based ways in (no brute force)."

    if "analysis" in s or "ai" in s:
        return "Reviewing everything found and preparing recommendations."

    if s == "final" or "final report" in text.lower():
        return "Assessment complete — full report is ready."

    # Strip markdown noise for short chat lines
    plain = re.sub(r"\*+", "", text)
    plain = re.sub(r"`", "", plain)
    plain = plain.strip()
    if len(plain) > 280:
        plain = plain[:277] + "…"
    if plain and not plain.startswith("#"):
        return plain
    return raw_message[:280] if raw_message else "Working on the assessment."


GUARDIAN_CHAT_PERSONALITY = """You are Guardian, Sentinel's security copilot — same professional voice as Sentinel AI.
You help with authorized security work: explain findings clearly, give progress in plain language, and answer questions.
When asked "how's the scan going", summarize counts (subdomains, endpoints, findings) and name the current tool.
Never use robotic phrases like "Assessment running." alone — be specific and helpful.
Do not recommend brute force, backdoor deployment, or attacks outside scope."""


TASK_STAGE_MAP = {
    "Target Validation": "Recon",
    "Subfinder": "Recon",
    "Amass": "Discovery",
    "Assetfinder": "Discovery",
    "dnsx": "Discovery",
    "httpx": "Discovery",
    "Naabu": "Enumeration",
    "Katana": "Enumeration",
    "ffuf": "Enumeration",
    "Nuclei": "Analysis",
    "ZAP": "Analysis",
    "Threat Intel": "Analysis",
    "Access Path Analysis": "Analysis",
    "Offensive Lab": "Analysis",
    "Guardian AI Analysis": "Findings",
    "Generating Final Report": "Report",
}


def task_phase_for_stage(stage_name: str) -> str:
    return TASK_STAGE_MAP.get(stage_name, "Analysis")
