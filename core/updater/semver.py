"""Semantic version comparison for Sentinel updates (PEP 440 via packaging)."""
from __future__ import annotations

import re
from typing import Union

try:
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover
    Version = None  # type: ignore


def normalize_version(version: str) -> str:
    """Strip leading 'v' and whitespace from tags like v1.0.0-beta.1."""
    v = (version or "").strip()
    if v.lower().startswith("v") and len(v) > 1 and v[1].isdigit():
        return v[1:]
    return v


def parse_version(version: str) -> Union["Version", None]:
    if Version is None:
        return None
    try:
        return Version(normalize_version(version))
    except InvalidVersion:
        return None


def version_newer(remote: str, current: str) -> bool:
    """True if remote is strictly newer than current (proper semver/pre-release)."""
    r = normalize_version(remote)
    c = normalize_version(current)
    if Version is None:
        return _fallback_newer(r, c)
    try:
        return Version(r) > Version(c)
    except InvalidVersion:
        return _fallback_newer(r, c)


def version_at_least(current: str, minimum: str) -> bool:
    """True if current >= minimum (full semver including pre-release)."""
    c = normalize_version(current)
    m = normalize_version(minimum)
    if Version is None:
        return not version_newer(m, c) or c == m
    try:
        return Version(c) >= Version(m)
    except InvalidVersion:
        return not version_newer(m, c)


def version_meets_minimum(current: str, minimum: str) -> bool:
    """True if current release epoch >= minimum (1.0.0-beta.1 satisfies minimum 1.0.0)."""
    c = normalize_version(current)
    m = normalize_version(minimum)
    if Version is None:
        return version_at_least(c, m)
    try:
        return Version(c).release >= Version(m).release
    except InvalidVersion:
        return version_at_least(c, m)


def _fallback_newer(remote: str, current: str) -> bool:
    """Last-resort tuple compare — should not run when packaging is installed."""
    def parts(v: str) -> list:
        return [int(x) for x in re.findall(r"\d+", v)[:4]] or [0]
    return parts(remote) > parts(current)
