"""
Capability Registry — every Sentinel feature declares required capabilities.

Tiers:
  1 = required (installer / always present)
  2 = recommended (first launch auto-install)
  3 = optional (on demand when feature requested)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional


class InstallTier(IntEnum):
    REQUIRED = 1
    RECOMMENDED = 2
    OPTIONAL = 3


@dataclass
class CapabilitySpec:
    id: str
    label: str
    tier: InstallTier
    domain: str  # GAME, WEB, DESKTOP, ANDROID, AI, GUARDIAN, CORE, BUILD
    description: str = ""


# ── Capability catalog ───────────────────────────────────────────────────────

CAPABILITIES: Dict[str, CapabilitySpec] = {}

def _reg(spec: CapabilitySpec) -> None:
    CAPABILITIES[spec.id] = spec


# CORE (Tier 1)
for cid, label in (
    ("python", "Python"),
    ("git", "Git"),
    ("sqlite", "SQLite"),
    ("venv", "Python venv"),
):
    _reg(CapabilitySpec(cid, label, InstallTier.REQUIRED, "CORE"))

# AI (Tier 1–2)
_reg(CapabilitySpec("ollama", "Ollama", InstallTier.REQUIRED, "AI", "Local LLM runtime"))
_reg(CapabilitySpec("ollama_models", "Default model pack", InstallTier.RECOMMENDED, "AI"))

# BUILD stack (Tier 1–2)
_reg(CapabilitySpec("nodejs", "Node.js", InstallTier.REQUIRED, "BUILD"))
_reg(CapabilitySpec("npm", "npm", InstallTier.REQUIRED, "BUILD"))
_reg(CapabilitySpec("electron", "Electron", InstallTier.RECOMMENDED, "BUILD"))
_reg(CapabilitySpec("chromium", "Chromium", InstallTier.OPTIONAL, "BUILD"))
_reg(CapabilitySpec("playwright", "Playwright", InstallTier.RECOMMENDED, "WEB"))

# GAME
_reg(CapabilitySpec("godot", "Godot Engine", InstallTier.RECOMMENDED, "GAME"))
_reg(CapabilitySpec("godot_export_templates", "Godot Export Templates", InstallTier.OPTIONAL, "GAME"))

# WEB
_reg(CapabilitySpec("nextjs_stack", "Next.js stack", InstallTier.RECOMMENDED, "WEB"))

# DESKTOP
_reg(CapabilitySpec("electron_builder", "Electron builder", InstallTier.RECOMMENDED, "DESKTOP"))

# ANDROID (Tier 2/3)
for cid, label in (
    ("android_sdk", "Android SDK"),
    ("android_platform_tools", "Android Platform Tools"),
    ("android_build_tools", "Android Build Tools"),
    ("jdk", "JDK"),
    ("gradle", "Gradle"),
):
    _reg(CapabilitySpec(cid, label, InstallTier.OPTIONAL, "ANDROID"))

# GUARDIAN (Tier 1–2)
for cid, label in (
    ("httpx", "httpx"),
    ("subfinder", "subfinder"),
    ("katana", "katana"),
    ("nuclei", "nuclei"),
    ("dnsx", "dnsx"),
    ("naabu", "naabu"),
    ("ffuf", "ffuf"),
    ("assetfinder", "assetfinder"),
    ("amass", "amass"),
    ("gowitness", "gowitness"),
    ("zap", "OWASP ZAP"),
):
    _reg(CapabilitySpec(cid, label, InstallTier.REQUIRED if cid in (
        "httpx", "subfinder", "katana", "nuclei",
    ) else InstallTier.RECOMMENDED, "GUARDIAN"))


# Domain → required capability ids for a task
DOMAIN_CAPABILITIES: Dict[str, List[str]] = {
    "GAME": ["godot", "godot_export_templates"],
    "WEB": ["nodejs", "npm", "playwright"],
    "DESKTOP": ["nodejs", "npm", "electron"],
    "ANDROID": ["jdk", "android_sdk", "android_platform_tools", "gradle"],
    "PYTHON": ["python"],
    "AI": ["ollama"],
    "GUARDIAN": [
        "httpx", "subfinder", "katana", "nuclei", "dnsx", "naabu",
        "ffuf", "assetfinder", "amass", "gowitness", "zap",
    ],
    "FORGE": ["python", "git", "nodejs", "npm"],
    "CORE": ["python", "git", "sqlite", "venv"],
}


def capabilities_for_domain(domain: str) -> List[CapabilitySpec]:
    ids = DOMAIN_CAPABILITIES.get(domain.upper(), [])
    return [CAPABILITIES[i] for i in ids if i in CAPABILITIES]


def capability_ids_for_build_type(build_type_value: str) -> List[str]:
    """Map router BuildType value to domain capabilities."""
    mapping = {
        "GAME": "GAME",
        "WEB": "WEB",
        "DESKTOP": "DESKTOP",
        "ANDROID": "ANDROID",
        "PYTHON": "PYTHON",
        "UNKNOWN": "PYTHON",
    }
    domain = mapping.get(build_type_value.upper(), "PYTHON")
    return DOMAIN_CAPABILITIES.get(domain, ["python"])
