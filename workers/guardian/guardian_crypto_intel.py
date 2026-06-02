"""
Crypto Threat Intelligence — roadmap module (v3).

Not a wallet targeting tool. Monitors public scam/phishing/malware infrastructure
and correlates public blockchain security research feeds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CryptoIntelRoadmap:
    status: str = "roadmap"
    capabilities: List[str] = field(default_factory=lambda: [
        "scam_campaign_monitoring",
        "wallet_malware_analysis",
        "phishing_infrastructure_analysis",
        "blockchain_security_research",
        "public_threat_feed_correlation",
    ])
    note: str = (
        "Crypto Threat Intelligence is planned for Guardian v3.1. "
        "It will correlate public feeds only — no wallet targeting or private key operations."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "capabilities": self.capabilities,
            "note": self.note,
        }

    def to_markdown(self) -> str:
        lines = ["## Crypto Threat Intelligence (Roadmap)", "", self.note, "", "**Planned capabilities:**"]
        for c in self.capabilities:
            lines.append(f"- {c.replace('_', ' ').title()}")
        return "\n".join(lines)


def get_roadmap() -> CryptoIntelRoadmap:
    return CryptoIntelRoadmap()
