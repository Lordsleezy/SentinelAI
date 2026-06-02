"""
workers/guardian/tools/httpx_tool.py — ProjectDiscovery httpx via httpx_compat.run_httpx()

Does not hardcode CLI flags. Detects binary flavor (ProjectDiscovery vs Python pip httpx),
probes -help for supported options, logs full command/stdout/stderr with [GUARDIAN] prefix.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, List, Optional

from workers.guardian.tools.httpx_compat import (
    find_projectdiscovery_httpx,
    run_httpx,
)


class HttpxResult:
    """Backward-compatible result wrapper."""

    def __init__(self, success: bool, hosts=None, raw_output: str = "", error: Optional[str] = None):
        self.success = success
        self.hosts = hosts or []
        self.raw_output = raw_output
        self.error = error


class HttpxTool:
    """
    Guardian httpx integration — delegates to run_httpx() compatibility layer.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._pd_info = None
        self._curl_ok: Optional[bool] = None

    def _guardian_log(self, msg: str, level: str = "info") -> None:
        if not msg.startswith("[GUARDIAN]"):
            msg = f"[GUARDIAN] {msg}"
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian",
                    "level": level,
                    "message": msg,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def _log_fn(self) -> Callable[[str, str], None]:
        return self._guardian_log

    def is_available(self) -> bool:
        """True if ProjectDiscovery httpx OR curl fallback exists."""
        if self._pd_info is not None:
            return True
        self._pd_info = find_projectdiscovery_httpx(self._log_fn())
        if self._pd_info:
            return True
        if self._curl_ok is None:
            import shutil
            self._curl_ok = bool(shutil.which("curl"))
            if self._curl_ok:
                self._guardian_log("httpx: ProjectDiscovery binary not found; curl fallback available", "warning")
        return bool(self._curl_ok)

    def probe(self, targets: List[str], timeout: int = 10) -> HttpxResult:
        """
        Probe hosts/URLs. Never passes unsupported flags to the wrong httpx binary.
        """
        if not self.is_available():
            return HttpxResult(success=False, error="httpx (PD) and curl unavailable — skipping")

        self._guardian_log(f"httpx probing {len(targets)} target(s)", "info")
        run = run_httpx(targets, timeout=timeout, log=self._log_fn())

        if run.error and not run.hosts:
            return HttpxResult(
                success=False,
                hosts=[],
                raw_output=run.stdout,
                error=run.error,
            )

        if not run.hosts:
            self._guardian_log(
                f"httpx: 0 hosts parsed ({len(run.stdout)} stdout bytes) — pipeline continues",
                "warning",
            )
        elif run.used_fallback:
            self._guardian_log(f"httpx curl fallback: {len(run.hosts)} host(s)", "success")
        else:
            self._guardian_log(f"httpx: {len(run.hosts)} host(s) from ProjectDiscovery", "success")

        return HttpxResult(
            success=True,
            hosts=run.hosts,
            raw_output=run.stdout or run.stderr,
            error=run.error,
        )
