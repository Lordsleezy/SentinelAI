"""
workers/guardian/tools/tool_registry.py — Guardian Tool Registry

Detects every supported security tool at import time.
Provides a single source of truth for tool availability shown in the UI
and used by _run_full_assessment() to decide which stages to execute.

Usage:
    from workers.guardian.tools.tool_registry import ToolRegistry
    reg = ToolRegistry(socketio)
    print(reg.status_summary())        # "✓ Nuclei  ✗ Katana  ✓ httpx …"
    tool = reg.nuclei                  # NucleiTool instance (always created)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolStatus:
    name: str
    available: bool
    note: str = ""

    def icon(self) -> str:
        return "✓" if self.available else "✗"

    def __str__(self) -> str:
        note = f"  ({self.note})" if self.note else ""
        return f"{self.icon()} {self.name}{note}"


class ToolRegistry:
    """
    Detects and exposes all Guardian security tools.
    Safe to instantiate even when tools are missing — availability is checked
    lazily and failures are always graceful.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._statuses: List[ToolStatus] = []
        self._init_tools()

    # ── Tool instances (always created, check .is_available() before use) ─────

    def _init_tools(self) -> None:
        """Instantiate all tool wrappers and probe availability."""
        from workers.guardian.tools.nuclei_tool   import NucleiTool
        from workers.guardian.tools.httpx_tool    import HttpxTool
        from workers.guardian.tools.subfinder_tool import SubfinderTool
        from workers.guardian.tools.katana_tool   import KatanaTool
        from workers.guardian.tools.zap_tool      import ZAPTool
        from workers.guardian.tools.amass_tool    import AmassTool
        from workers.guardian.tools.faraday_store import FaradayStore
        from workers.guardian.tools.reconftw_tool import ReconftfTool as ReconFTWTool

        self.nuclei    = NucleiTool(self.socketio)
        self.httpx     = HttpxTool(self.socketio)
        self.subfinder = SubfinderTool(self.socketio)
        self.katana    = KatanaTool(self.socketio)
        self.zap       = ZAPTool(self.socketio)
        self.amass     = AmassTool(self.socketio)
        self.faraday   = FaradayStore()
        self.reconftw  = ReconFTWTool(self.socketio)

        self._statuses = [
            ToolStatus("Nuclei",    self.nuclei.is_available(),    "github.com/projectdiscovery/nuclei"),
            ToolStatus("httpx",     self.httpx.is_available(),     "github.com/projectdiscovery/httpx"),
            ToolStatus("Subfinder", self.subfinder.is_available(), "github.com/projectdiscovery/subfinder"),
            ToolStatus("Katana",    self.katana.is_available(),    "github.com/projectdiscovery/katana"),
            ToolStatus("ZAP",       self.zap.is_available(),       "zaproxy.org"),
            ToolStatus("Amass",     self.amass.is_available(),     "github.com/owasp-amass/amass"),
            ToolStatus("ReconFTW",  self.reconftw.is_available(),  "github.com/six2dez/reconftw"),
        ]

        available = [s.name for s in self._statuses if s.available]
        missing   = [s.name for s in self._statuses if not s.available]
        logger.info("[GUARDIAN/tools] Available: %s", available or "none")
        if missing:
            logger.info("[GUARDIAN/tools] Missing (gracefully skipped): %s", missing)

    # ── Status accessors ──────────────────────────────────────────────────────

    def all_statuses(self) -> List[ToolStatus]:
        return list(self._statuses)

    def status_dict(self) -> Dict[str, bool]:
        return {s.name: s.available for s in self._statuses}

    def status_summary(self) -> str:
        """One-line summary: '✓ Nuclei  ✓ httpx  ✗ Katana …'"""
        return "  ".join(str(s) for s in self._statuses)

    def status_block(self) -> str:
        """Multi-line formatted status block for Guardian report."""
        lines = ["### Tool Status\n"]
        for s in self._statuses:
            lines.append(f"- {s}")
        missing = [s for s in self._statuses if not s.available]
        if missing:
            lines.append(f"\n**Missing tools** (install to enable):")
            for s in missing:
                lines.append(f"  - {s.name}: {s.note}")
        return "\n".join(lines)

    def has_any_scanner(self) -> bool:
        """Returns True if at least one active scanner is available."""
        return any([
            self.nuclei.is_available(),
            self.zap.is_available(),
        ])

    def has_recon(self) -> bool:
        return self.subfinder.is_available() or self.amass.is_available()


def _probe_roadmap_binary(tool_id: str, label: str, exe_names: Optional[List[str]] = None) -> Dict[str, object]:
    """Probe bundled → system paths for roadmap / optional modules."""
    import shutil
    from pathlib import Path

    from workers.guardian.bundled_toolchain import _path_is_bundled, iter_candidate_paths, resolve_tool_binary

    exe_names = exe_names or [f"{tool_id}.exe", tool_id]
    resolved = resolve_tool_binary(tool_id)
    path: Optional[str] = resolved.path if resolved else None

    if not path:
        for name in exe_names:
            w = shutil.which(name)
            if w:
                path = w
                break
            try:
                for p, _src in iter_candidate_paths(tool_id):
                    if Path(p).is_file():
                        path = p
                        break
            except Exception:
                pass
            if path:
                break

    installed = bool(path and Path(path).is_file())
    if installed and path and _path_is_bundled(path):
        status_line, src = "✓ Bundled", "bundled"
    elif installed:
        status_line, src = "✓ System", "system"
    else:
        status_line, src = "✗ Missing", None

    return {
        "id": tool_id,
        "label": label,
        "installed": installed,
        "bundled": src == "bundled",
        "system": src == "system",
        "source": src,
        "path": path,
        "status_line": status_line,
        "roadmap": True,
    }


def get_tool_diagnostics() -> List[Dict[str, object]]:
    """
    Read-only install probe for the Guardian Tool Status panel.
    Shows ✓ Bundled / ✓ System / ✗ Missing per tool (core + roadmap modules).
    """
    from workers.guardian.bundled_toolchain import CORE_TOOL_IDS, diagnose_core_tool, diagnose_optional_tool
    from workers.guardian.tools.amass_tool import AmassTool
    from workers.guardian.tools.zap_tool import ZAPTool

    amass = AmassTool(None)
    zap = ZAPTool(None)

    def _amass_path() -> Optional[str]:
        getter = getattr(amass, "_get_bin", None)
        return getter() if getter else None

    zap_ok = zap.is_available()
    zap_path = f"{zap.base}/JSON/core/view/version/" if zap_ok else None

    rows: List[Dict[str, object]] = [diagnose_core_tool(tid) for tid in CORE_TOOL_IDS]
    rows.append(
        diagnose_optional_tool(
            "amass", "Amass",
            is_available=amass.is_available(),
            path=_amass_path(),
        )
    )
    rows.append(
        diagnose_optional_tool(
            "zap", "ZAP",
            is_available=zap_ok,
            path=zap_path,
        )
    )

    rows.append(_probe_roadmap_binary("gowitness", "gowitness"))

    try:
        from workers.guardian import guardian_threat_intel
        ti_ok = bool(guardian_threat_intel)
    except Exception:
        ti_ok = False

    rows.append({
        "id": "reconftw",
        "label": "ReconFTW",
        "installed": False,
        "bundled": False,
        "system": False,
        "source": None,
        "path": None,
        "status_line": "✗ Missing",
        "roadmap": True,
        "note": "Optional orchestration script",
    })
    rows.append({
        "id": "threat_intel",
        "label": "Threat Intel (OTX / AbuseIPDB / KEV)",
        "installed": ti_ok,
        "bundled": False,
        "system": ti_ok,
        "source": "module" if ti_ok else None,
        "path": "workers/guardian/guardian_threat_intel.py" if ti_ok else None,
        "status_line": "✓ Module" if ti_ok else "✗ Missing",
        "version": "v3",
        "health": "ok" if ti_ok else "missing",
        "roadmap": False,
    })
    rows.append({
        "id": "crypto_intel",
        "label": "Crypto Intel",
        "installed": False,
        "bundled": False,
        "system": False,
        "source": None,
        "path": None,
        "status_line": "Phase 6 — planned",
        "roadmap": True,
    })
    return rows
