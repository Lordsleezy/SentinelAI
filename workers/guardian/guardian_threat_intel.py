"""
Guardian Threat Intelligence — public feeds (OTX, AbuseIPDB, CISA KEV, IOC lists).

Requires optional API keys in environment:
  OTX_API_KEY, ABUSEIPDB_API_KEY
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_RE = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")


@dataclass
class ThreatIntelResult:
    domain_reputation: Dict[str, Any] = field(default_factory=dict)
    ip_reputation: Dict[str, Any] = field(default_factory=dict)
    threat_summaries: List[str] = field(default_factory=list)
    known_indicators: List[Dict[str, Any]] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = ["## Threat Intelligence", ""]
        if self.threat_summaries:
            lines.append("### Summaries")
            for s in self.threat_summaries[:10]:
                lines.append(f"- {s}")
            lines.append("")
        if self.known_indicators:
            lines.append("### Known Indicators")
            for i in self.known_indicators[:15]:
                lines.append(f"- `{i.get('indicator', '')}` ({i.get('type', '')}) — {i.get('source', '')}")
            lines.append("")
        if self.domain_reputation:
            lines.append("### Domain Reputation")
            for dom, rep in list(self.domain_reputation.items())[:5]:
                lines.append(f"- **{dom}**: {rep.get('summary', rep)}")
            lines.append("")
        if self.ip_reputation:
            lines.append("### IP Reputation")
            for ip, rep in list(self.ip_reputation.items())[:5]:
                lines.append(f"- **{ip}**: {rep.get('summary', rep)}")
            lines.append("")
        if self.errors:
            lines.append("### Intel Notes")
            for e in self.errors[:5]:
                lines.append(f"- {e}")
        if len(lines) <= 2:
            lines.append("_No threat intelligence data retrieved (configure API keys or check network)._")
        return "\n".join(lines)


def _http_get(url: str, headers: Optional[Dict] = None, timeout: int = 20) -> Optional[Dict]:
    try:
        import httpx
        r = httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=True)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug("threat intel GET %s: %s", url, e)
    return None


def query_otx_domain(domain: str) -> Dict[str, Any]:
    key = os.environ.get("OTX_API_KEY", "").strip()
    if not key:
        return {"summary": "OTX_API_KEY not set"}
    url = f"https://otx.alienvault.com/api/v1/indicators/domain/{domain}/general"
    data = _http_get(url, headers={"X-OTX-API-KEY": key})
    if not data:
        return {"summary": "OTX query failed"}
    pulse = data.get("pulse_info") or {}
    return {
        "summary": f"pulses={pulse.get('count', 0)}",
        "reputation": data.get("reputation", 0),
        "validation": data.get("validation", []),
    }


def query_abuseipdb(ip: str) -> Dict[str, Any]:
    key = os.environ.get("ABUSEIPDB_API_KEY", "").strip()
    if not key:
        return {"summary": "ABUSEIPDB_API_KEY not set"}
    try:
        import httpx
        r = httpx.get(
            "https://api.abuseipdb.com/api/v2/check",
            headers={"Key": key, "Accept": "application/json"},
            params={"ipAddress": ip, "maxAgeInDays": 90},
            timeout=20,
        )
        if r.status_code == 200:
            d = r.json().get("data") or {}
            return {
                "summary": f"score={d.get('abuseConfidenceScore', 0)} reports={d.get('totalReports', 0)}",
                "country": d.get("countryCode"),
                "is_public": d.get("isPublic"),
            }
    except Exception as e:
        return {"summary": f"AbuseIPDB error: {e}"}
    return {"summary": "AbuseIPDB query failed"}


def fetch_cisa_kev() -> List[Dict[str, Any]]:
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    data = _http_get(url, timeout=45)
    if not data:
        return []
    vulns = data.get("vulnerabilities") or []
    return [{"cve": v.get("cveID"), "product": v.get("product"), "due": v.get("dueDate")}
            for v in vulns[:50]]


def fetch_public_ioc_sample() -> List[Dict[str, Any]]:
    """Best-effort public IOC text feed (may be blocked offline)."""
    indicators: List[Dict[str, Any]] = []
    try:
        import httpx
        # OpenPhish free list (domain IOCs)
        r = httpx.get("https://openphish.com/feed.txt", timeout=15, follow_redirects=True)
        if r.status_code == 200:
            for line in r.text.splitlines()[:20]:
                line = line.strip()
                if line.startswith("http"):
                    indicators.append({"indicator": line, "type": "url", "source": "openphish"})
    except Exception:
        pass
    return indicators


def analyze_target(target: str) -> ThreatIntelResult:
    result = ThreatIntelResult()
    domain = target.strip().lower()
    if domain.startswith("http"):
        domain = domain.split("//", 1)[-1].split("/")[0]

    # OTX
    try:
        rep = query_otx_domain(domain)
        result.domain_reputation[domain] = rep
        result.sources_used.append("alienvault_otx")
        if rep.get("summary"):
            result.threat_summaries.append(f"OTX {domain}: {rep['summary']}")
    except Exception as e:
        result.errors.append(f"OTX: {e}")

    # IPs in target string
    for ip in _IP_RE.findall(target)[:3]:
        try:
            rep = query_abuseipdb(ip)
            result.ip_reputation[ip] = rep
            result.sources_used.append("abuseipdb")
            result.threat_summaries.append(f"AbuseIPDB {ip}: {rep.get('summary', '')}")
        except Exception as e:
            result.errors.append(f"AbuseIPDB: {e}")

    # CISA KEV sample
    try:
        kev = fetch_cisa_kev()
        if kev:
            result.sources_used.append("cisa_kev")
            result.threat_summaries.append(f"CISA KEV catalog: {len(kev)} recent entries loaded")
            for entry in kev[:5]:
                result.known_indicators.append({
                    "indicator": entry.get("cve", ""),
                    "type": "cve",
                    "source": "cisa_kev",
                })
    except Exception as e:
        result.errors.append(f"CISA KEV: {e}")

    # Public phishing IOC sample
    try:
        iocs = fetch_public_ioc_sample()
        if iocs:
            result.sources_used.append("openphish")
            result.known_indicators.extend(iocs[:10])
            result.threat_summaries.append(f"Public phishing feed: {len(iocs)} sample IOC(s)")
    except Exception as e:
        result.errors.append(f"phishing feed: {e}")

    if not os.environ.get("OTX_API_KEY") and not os.environ.get("ABUSEIPDB_API_KEY"):
        result.errors.append(
            "Set OTX_API_KEY and/or ABUSEIPDB_API_KEY for full domain/IP reputation."
        )

    return result
