"""Guardian system monitor — real psutil-based telemetry (no fake data)."""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.guardian.monitor")

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

_ROOT = Path(__file__).resolve().parents[2]
_HISTORY_SIZE = 120


class GuardianSystemMonitor:
    def __init__(self, sample_interval: float = 10.0) -> None:
        self.sample_interval = sample_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._history: deque = deque(maxlen=_HISTORY_SIZE)
        self._alerts: deque = deque(maxlen=50)
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="guardian-monitor", daemon=True)
        self._thread.start()
        logger.info("Guardian system monitor started")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                snap = self.collect_snapshot()
                with self._lock:
                    self._history.append(snap)
                    self._evaluate_alerts(snap)
            except Exception as e:
                logger.exception("guardian monitor: %s", e)
            time.sleep(self.sample_interval)

    def collect_snapshot(self) -> Dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat()
        if psutil is None:
            return {"timestamp": ts, "error": "psutil not installed", "healthy": False}

        cpu = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "percent": round(usage.percent, 1),
                    "free_gb": round(usage.free / 1e9, 2),
                    "total_gb": round(usage.total / 1e9, 2),
                })
            except PermissionError:
                continue

        net = psutil.net_io_counters()
        network = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }

        processes = []
        sentinel_pids = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = proc.info
                if info.get("cpu_percent", 0) and info["cpu_percent"] > 15:
                    processes.append({
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu_percent": round(info["cpu_percent"] or 0, 1),
                        "memory_percent": round(info["memory_percent"] or 0, 1),
                        "status": info.get("status"),
                    })
                if info.get("name") and "python" in (info["name"] or "").lower():
                    cmd = " ".join(proc.cmdline()[:3]) if hasattr(proc, "cmdline") else ""
                    if "desktop_app" in cmd or "sentinel" in cmd.lower():
                        sentinel_pids.append(info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda x: x["cpu_percent"], reverse=True)

        services = self._check_services()

        healthy = (
            cpu < 95
            and vm.percent < 95
            and all(d["percent"] < 98 for d in disks)
        )

        return {
            "timestamp": ts,
            "healthy": healthy,
            "cpu_percent": round(cpu, 1),
            "ram_percent": round(vm.percent, 1),
            "ram_used_gb": round(vm.used / 1e9, 2),
            "ram_total_gb": round(vm.total / 1e9, 2),
            "disks": disks,
            "network": network,
            "top_processes": processes[:15],
            "sentinel_process_pids": sentinel_pids,
            "services": services,
        }

    def _check_services(self) -> List[Dict[str, Any]]:
        checks = []
        port = int(os.environ.get("SENTINEL_PORT", "5001"))
        checks.append(self._probe_port("sentinel_api", "127.0.0.1", port))
        checks.append(self._probe_http("sentinel_health", f"http://127.0.0.1:{port}/api/health/live"))
        return checks

    def _probe_port(self, name: str, host: str, port: int) -> Dict[str, Any]:
        try:
            with socket.create_connection((host, port), timeout=2):
                return {"name": name, "up": True, "detail": f"{host}:{port}"}
        except OSError as e:
            return {"name": name, "up": False, "detail": str(e)}

    def _probe_http(self, name: str, url: str) -> Dict[str, Any]:
        try:
            import httpx
            r = httpx.get(url, timeout=3.0)
            return {"name": name, "up": r.status_code < 500, "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"name": name, "up": False, "detail": str(e)[:120]}

    def _evaluate_alerts(self, snap: Dict[str, Any]) -> None:
        suggestions = []
        if snap.get("cpu_percent", 0) > 85:
            self._push_alert("warning", "High CPU", "CPU above 85%", "Close heavy processes or pause scans.")
            suggestions.append("Reduce concurrent Guardian scans.")
        if snap.get("ram_percent", 0) > 85:
            self._push_alert("warning", "High memory", "RAM above 85%", "Restart idle workers or clear hot memory.")
        for d in snap.get("disks", []):
            if d.get("percent", 0) > 90:
                self._push_alert(
                    "critical",
                    "Disk space low",
                    f"{d.get('mountpoint')} at {d['percent']}%",
                    "Run memory cleanup or archive vault data.",
                )
        for svc in snap.get("services", []):
            if not svc.get("up"):
                self._push_alert(
                    "critical",
                    "Service down",
                    svc.get("name", "unknown"),
                    f"Check {svc.get('detail')}; restart Sentinel backend.",
                )

    def _push_alert(self, level: str, title: str, message: str, remediation: str) -> None:
        self._alerts.append({
            "level": level,
            "title": title,
            "message": message,
            "remediation": remediation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def dashboard(self) -> Dict[str, Any]:
        with self._lock:
            latest = self._history[-1] if self._history else self.collect_snapshot()
            history = list(self._history)[-30:]
            alerts = list(self._alerts)[-20:]
        return {
            "status": "ok" if latest.get("healthy") else "degraded",
            "latest": latest,
            "history_count": len(history),
            "alerts": alerts,
            "remediation_hints": [a["remediation"] for a in alerts[-5:]],
        }

    def get_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._alerts)[-limit:]


_monitor: Optional[GuardianSystemMonitor] = None


def get_guardian_monitor() -> GuardianSystemMonitor:
    global _monitor
    if _monitor is None:
        _monitor = GuardianSystemMonitor()
        _monitor.start()
    return _monitor
