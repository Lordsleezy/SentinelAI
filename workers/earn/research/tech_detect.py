"""Technology detection from httpx / host metadata."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from workers.earn.research.models import HostTechnology

_FRAMEWORK_HINTS = {
    "next.js": ["next.js", "x-powered-by: next", "_next/"],
    "react": ["react", "react-dom"],
    "vue": ["vue.js", "vue-router"],
    "angular": ["angular", "ng-version"],
    "graphql": ["graphql", "/graphql"],
}
_CMS_HINTS = {
    "wordpress": ["wordpress", "wp-content", "wp-includes"],
    "drupal": ["drupal"],
    "shopify": ["shopify"],
}
_CLOUD_HINTS = {
    "cloudflare": ["cloudflare", "cf-ray"],
    "aws": ["amazonaws.com", "aws", "x-amz"],
    "azure": ["azure", "windows-azure"],
    "gcp": ["google cloud", "gstatic.com"],
}
_AUTH_HINTS = {
    "oauth": ["oauth", "openid"],
    "auth0": ["auth0"],
    "okta": ["okta"],
    "saml": ["saml"],
}


def _match_hints(blob: str, hints: Dict[str, List[str]]) -> List[str]:
    low = blob.lower()
    found: List[str] = []
    for name, keys in hints.items():
        if any(k in low for k in keys):
            found.append(name)
    return found


def detect_host_technologies(hosts: List[Dict[str, Any]]) -> List[HostTechnology]:
    out: List[HostTechnology] = []
    for h in hosts:
        url = (h.get("url") or "").strip()
        if not url:
            continue
        tech_raw = h.get("tech") or []
        if isinstance(tech_raw, str):
            tech_raw = [tech_raw]
        blob = " ".join([
            url,
            " ".join(str(t) for t in tech_raw),
            str(h.get("title") or ""),
            str(h.get("webserver") or ""),
            str(h.get("content_type") or ""),
        ])
        if re.search(r"graphql|/gql|gql\b", blob, re.I):
            tech_raw = list(tech_raw) + ["GraphQL"]
        ht = HostTechnology(
            url=url,
            framework=_match_hints(blob, _FRAMEWORK_HINTS),
            cms=_match_hints(blob, _CMS_HINTS),
            cloud=_match_hints(blob, _CLOUD_HINTS),
            auth=_match_hints(blob, _AUTH_HINTS),
            api_tech=[t for t in tech_raw if any(x in str(t).lower() for x in ("api", "graphql", "grpc", "rest"))],
            raw_tech=[str(t) for t in tech_raw][:20],
        )
        if "graphql" in blob.lower() and "GraphQL" not in ht.api_tech:
            ht.api_tech.append("GraphQL")
        out.append(ht)
    return out
