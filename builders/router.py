"""
builders/router.py — Classify build requests and select specialized builders.

Log format: [BUILDER] Route: GAME
"""
from __future__ import annotations

import re
from enum import Enum

from builders.common.logging_util import log_builder


class BuildType(str, Enum):
    GAME = "GAME"
    ANDROID = "ANDROID"
    WEB = "WEB"
    DESKTOP = "DESKTOP"
    PYTHON = "PYTHON"
    UNKNOWN = "UNKNOWN"


# Order matters: more specific patterns first
_RULES: list[tuple[BuildType, list[str]]] = [
    (BuildType.GAME, [
        r"\bflappy\b", r"\bbird\b", r"\bgame\b", r"\bgodot\b", r"\bplatformer\b",
        r"\barcade\b", r"\bpong\b", r"\btetris\b", r"\bsnake\b", r"\b2d\s+game\b",
        r"\bgdevelop\b",
    ]),
    (BuildType.ANDROID, [
        r"\bandroid\b", r"\bapk\b", r"\bkotlin\b", r"\bjetpack\s+compose\b",
        r"\bmobile\s+app\b", r"\bplay\s+store\b",
    ]),
    (BuildType.WEB, [
        r"\bwebsite\b", r"\bweb\s+site\b", r"\blanding\s+page\b", r"\bnext\.?js\b",
        r"\breact\b", r"\btailwind\b", r"\bdashboard\b", r"\badmin\s+panel\b",
        r"\bcompany\s+site\b", r"\bportfolio\s+site\b",
    ]),
    (BuildType.DESKTOP, [
        r"\bcalculator\b", r"\bdesktop\s+app\b", r"\belectron\b", r"\btauri\b",
        r"\bwindows\s+app\b", r"\bmac\s+app\b",
    ]),
    (BuildType.PYTHON, [
        r"\bpython\s+script\b", r"\bcli\b", r"\butility\b", r"\bautomation\b",
        r"\bscript\b", r"\b\.py\b",
    ]),
]


def classify_build(description: str) -> BuildType:
    """Classify a natural-language build request."""
    text = description.lower().strip()
    for build_type, patterns in _RULES:
        for pat in patterns:
            if re.search(pat, text, re.I):
                return build_type
    if re.search(r"\bbuild\b|\bcreate\b|\bmake\b", text):
        return BuildType.UNKNOWN
    return BuildType.UNKNOWN


def route_build(description: str, socketio=None) -> BuildType:
    """Classify and log the routing decision."""
    build_type = classify_build(description)
    log_builder(f"Route: {build_type.value}", "info", socketio)
    return build_type
