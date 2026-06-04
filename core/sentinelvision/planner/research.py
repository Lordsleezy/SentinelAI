"""Research engine — documentation, URLs, structured provider knowledge."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("sentinel.vision.research")


class ResearchEngine:
    def research_objective(self, objective: str, provider_id: Optional[str] = None) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        urls_tried: List[str] = []

        if provider_id:
            from core.sentinelvision.providers.registry import get_provider
            prov = get_provider(provider_id)
            if prov:
                doc = prov.research(objective)
                findings.append({"source": f"provider:{provider_id}", "data": doc})

        for url in self._extract_urls(objective):
            page = self._fetch_url(url)
            urls_tried.append(url)
            if page:
                findings.append({"source": url, "data": page})

        doc_urls = self._default_doc_urls(provider_id, objective)
        for url in doc_urls[:3]:
            if url in urls_tried:
                continue
            page = self._fetch_url(url)
            if page:
                findings.append({"source": url, "data": page})

        summary = self._summarize(findings, objective)
        return {
            "objective": objective,
            "provider_id": provider_id,
            "findings": findings,
            "summary": summary,
            "required_actions": summary.get("required_actions", []),
        }

    def _fetch_url(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            import httpx
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                r = client.get(url, headers={"User-Agent": "SentinelVision/1.0 (research)"})
                if r.status_code >= 400:
                    return None
                text = r.text[:50000]
                title = ""
                m = re.search(r"<title[^>]*>([^<]+)</title>", text, re.I)
                if m:
                    title = re.sub(r"\s+", " ", m.group(1)).strip()
                body = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.I | re.S)
                body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.I | re.S)
                body = re.sub(r"<[^>]+>", " ", body)
                body = re.sub(r"\s+", " ", body).strip()[:8000]
                return {"url": url, "title": title, "excerpt": body}
        except Exception as e:
            logger.debug("fetch %s: %s", url, e)
            return None

    @staticmethod
    def _extract_urls(text: str) -> List[str]:
        return re.findall(r"https?://[^\s\)\]\"']+", text or "")

    @staticmethod
    def _default_doc_urls(provider_id: Optional[str], objective: str) -> List[str]:
        base = {
            "supabase": ["https://supabase.com/docs/guides/getting-started"],
            "stripe": ["https://docs.stripe.com/get-started"],
            "cloudflare": ["https://developers.cloudflare.com/fundamentals/"],
            "github": ["https://docs.github.com/en/get-started"],
            "netlify": ["https://docs.netlify.com/"],
            "amazon": [],
        }
        return base.get((provider_id or "").lower(), [])

    @staticmethod
    def _summarize(findings: List[Dict[str, Any]], objective: str) -> Dict[str, Any]:
        actions = []
        env_vars = []
        for f in findings:
            data = f.get("data") or {}
            if isinstance(data, dict):
                for a in data.get("required_actions") or []:
                    if a not in actions:
                        actions.append(a)
                for e in data.get("environment_variables") or []:
                    if e not in env_vars:
                        env_vars.append(e)
        return {
            "objective": objective,
            "finding_count": len(findings),
            "required_actions": actions,
            "environment_variables": env_vars,
            "notes": "Research complete — planner will build execution steps.",
        }
