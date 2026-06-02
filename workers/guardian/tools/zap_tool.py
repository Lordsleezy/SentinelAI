"""
OWASP ZAP wrapper via its REST API.
ZAP must be running: zap.sh -daemon -port 8090
Or: docker run -d -p 8090:8080 ghcr.io/zaproxy/zaproxy:stable zap.sh -daemon
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

ZAP_API_BASE = "http://localhost:8090"
ZAP_TIMEOUT = 10


@dataclass
class ZAPFinding:
    alert: str
    risk: str
    confidence: str
    url: str
    description: str
    solution: str
    reference: str = ""

    def to_dict(self) -> dict:
        return {
            "alert": self.alert,
            "risk": self.risk,
            "confidence": self.confidence,
            "url": self.url,
            "description": self.description,
            "solution": self.solution,
        }


class ZAPTool:
    """
    Wraps OWASP ZAP via its REST API.
    ZAP must be running on port 8090 (default) or ZAP_PORT env var.
    """

    def __init__(self, socketio: Any = None, port: int = 8090):
        self.socketio = socketio
        self.base = f"http://localhost:{port}"

    def _emit(self, message: str, level: str = "info") -> None:
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian",
                    "level": level,
                    "message": f"[ZAP] {message}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def is_available(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.base}/JSON/core/view/version/", timeout=ZAP_TIMEOUT)
            return r.status_code == 200
        except Exception:
            return False

    def spider(self, target_url: str) -> List[str]:
        """Crawl target, return all discovered URLs."""
        try:
            import requests
            self._emit(f"Spidering {target_url}")
            r = requests.get(
                f"{self.base}/JSON/spider/action/scan/",
                params={"url": target_url},
                timeout=ZAP_TIMEOUT,
            )
            scan_id = r.json().get("scan", "0")
            import time
            while True:
                status = requests.get(
                    f"{self.base}/JSON/spider/view/status/",
                    params={"scanId": scan_id},
                    timeout=ZAP_TIMEOUT,
                ).json().get("status", "100")
                if int(status) >= 100:
                    break
                self._emit(f"Spider progress: {status}%")
                time.sleep(2)
            results_r = requests.get(
                f"{self.base}/JSON/spider/view/results/",
                params={"scanId": scan_id},
                timeout=ZAP_TIMEOUT,
            )
            urls = results_r.json().get("results", [])
            self._emit(f"Spider found {len(urls)} URLs", "success")
            return urls
        except Exception as e:
            self._emit(str(e), "error")
            return []

    def active_scan(self, target_url: str) -> List[ZAPFinding]:
        """Run active vulnerability scan."""
        try:
            import requests, time
            self._emit(f"Active scan: {target_url}")
            r = requests.get(
                f"{self.base}/JSON/ascan/action/scan/",
                params={"url": target_url},
                timeout=ZAP_TIMEOUT,
            )
            scan_id = r.json().get("scan", "0")
            while True:
                status = requests.get(
                    f"{self.base}/JSON/ascan/view/status/",
                    params={"scanId": scan_id},
                    timeout=ZAP_TIMEOUT,
                ).json().get("status", "100")
                if int(status) >= 100:
                    break
                self._emit(f"Scan progress: {status}%")
                time.sleep(3)
            return self._get_alerts(target_url)
        except Exception as e:
            self._emit(str(e), "error")
            return []

    def passive_scan(self, target_url: str) -> List[ZAPFinding]:
        """Run passive scan (safer, less intrusive)."""
        try:
            import requests
            self._emit(f"Passive scan: {target_url}")
            requests.get(
                f"{self.base}/JSON/pscan/action/enableAllScanners/",
                timeout=ZAP_TIMEOUT,
            )
            return self._get_alerts(target_url)
        except Exception as e:
            self._emit(str(e), "error")
            return []

    def _get_alerts(self, base_url: str) -> List[ZAPFinding]:
        try:
            import requests
            r = requests.get(
                f"{self.base}/JSON/alert/view/alerts/",
                params={"baseurl": base_url},
                timeout=ZAP_TIMEOUT,
            )
            alerts = r.json().get("alerts", [])
            findings = [
                ZAPFinding(
                    alert=a.get("alert", ""),
                    risk=a.get("risk", ""),
                    confidence=a.get("confidence", ""),
                    url=a.get("url", ""),
                    description=a.get("description", ""),
                    solution=a.get("solution", ""),
                    reference=a.get("reference", ""),
                )
                for a in alerts
            ]
            self._emit(f"Found {len(findings)} alerts", "success" if findings else "info")
            return findings
        except Exception as e:
            self._emit(str(e), "error")
            return []
