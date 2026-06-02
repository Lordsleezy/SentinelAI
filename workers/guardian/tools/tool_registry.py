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
from typing import Any, Dict, List

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
