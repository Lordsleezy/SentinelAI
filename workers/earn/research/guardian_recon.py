"""Controlled Guardian recon — in-scope assets only (Subfinder, httpx, Katana, Nuclei)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from workers.earn.hackerone_intel import ProgramIntel
from workers.earn.research.store import save_recon_artifact

logger = logging.getLogger("sentinel.earn.research.recon")


def _allowed_hosts(intel: ProgramIntel) -> Set[str]:
    hosts: Set[str] = set()
    for a in intel.in_scope:
        if not a.eligible_for_bounty:
            continue
        ident = (a.identifier or "").strip().lower()
        if ident.startswith("http"):
            try:
                hosts.add(urlparse(ident).netloc.split(":")[0])
            except Exception:
                pass
        elif "." in ident:
            hosts.add(ident.split("/")[0].split(":")[0])
    return hosts


def _filter_in_scope(urls: List[str], allowed: Set[str]) -> List[str]:
    out: List[str] = []
    for u in urls:
        try:
            host = urlparse(u if u.startswith("http") else f"https://{u}").netloc.lower()
            host = host.split(":")[0]
        except Exception:
            continue
        if any(host == a or host.endswith("." + a) for a in allowed):
            out.append(u if u.startswith("http") else f"https://{host}")
    return out


def _root_domains(intel: ProgramIntel, max_n: int = 3) -> List[str]:
    roots: List[str] = []
    seen: Set[str] = set()
    for a in intel.in_scope:
        ident = (a.identifier or "").strip()
        if ident.startswith("http"):
            ident = urlparse(ident).netloc
        host = ident.split("/")[0].split(":")[0].lower()
        if not re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$", host):
            continue
        parts = host.split(".")
        root = ".".join(parts[-2:]) if len(parts) >= 2 else host
        if root not in seen:
            seen.add(root)
            roots.append(root)
    return roots[:max_n]


def run_controlled_recon(
    session_id: str,
    intel: ProgramIntel,
    probe_targets: List[str],
    socketio: Any = None,
) -> Dict[str, Any]:
    """
    Run allowed Guardian tools against in-scope assets only.
    Does not modify Guardian brain workflows.
    """
    allowed = _allowed_hosts(intel)
    if not allowed:
        return {"error": "no in-scope hosts", "hosts": [], "endpoints": [], "findings": []}

    targets = _filter_in_scope(probe_targets, allowed)
    results: Dict[str, Any] = {
        "allowed_hosts": sorted(allowed),
        "targets": targets,
        "subdomains": [],
        "hosts": [],
        "endpoints": [],
        "nuclei_findings": [],
        "tools_run": [],
        "skipped": [],
    }

    def _log(msg: str) -> None:
        logger.info("[EARN Research] %s", msg)
        if socketio:
            try:
                socketio.emit("log_event", {"type": "earn", "level": "info", "message": f"[EARN Research] {msg}"})
            except Exception:
                pass

    subdomains: List[str] = []
    try:
        from workers.guardian.tools.subfinder_tool import SubfinderTool
        sf = SubfinderTool(socketio)
        if sf.is_available():
            for domain in _root_domains(intel):
                res = sf.enumerate(domain, timeout=45)
                raw_subs = [s.strip() for s in (res.subdomains or []) if s.strip()]
                for s in raw_subs:
                    if any(s.endswith("." + a) or s == a for a in allowed):
                        subdomains.append(s)
                save_recon_artifact(session_id, f"subfinder_{domain}", res.raw_output or "")
            results["tools_run"].append("subfinder")
            _log(f"Subfinder: {len(subdomains)} in-scope subdomain(s)")
        else:
            results["skipped"].append("subfinder")
    except Exception as e:
        results["skipped"].append(f"subfinder:{e}")

    httpx_targets = list(dict.fromkeys(targets + [f"https://{s}" for s in subdomains[:15]]))[:30]
    httpx_targets = _filter_in_scope(httpx_targets, allowed)

    hosts: List[Dict] = []
    try:
        from workers.guardian.tools.httpx_tool import HttpxTool
        hx = HttpxTool(socketio)
        if hx.is_available() and httpx_targets:
            hres = hx.probe(httpx_targets[:20], timeout=10)
            hosts = list(hres.hosts or [])
            save_recon_artifact(session_id, "httpx", hres.raw_output or "")
            results["tools_run"].append("httpx")
            _log(f"httpx: {len(hosts)} host(s)")
        else:
            results["skipped"].append("httpx")
    except Exception as e:
        results["skipped"].append(f"httpx:{e}")

    endpoints: List[str] = []
    crawl_url = httpx_targets[0] if httpx_targets else ""
    if crawl_url:
        try:
            from workers.guardian.tools.katana_tool import KatanaTool
            kt = KatanaTool(socketio)
            if kt.is_available():
                kres = kt.crawl(crawl_url, depth=1, timeout=45)
                endpoints = _filter_in_scope(
                    [e if e.startswith("http") else f"{crawl_url.rstrip('/')}/{e}" for e in (kres.endpoints or [])],
                    allowed,
                )[:100]
                save_recon_artifact(session_id, "katana", kres.raw_output or "")
                results["tools_run"].append("katana")
                _log(f"Katana: {len(endpoints)} in-scope endpoint(s)")
            else:
                results["skipped"].append("katana")
        except Exception as e:
            results["skipped"].append(f"katana:{e}")

    nuclei_findings: List[Dict] = []
    if httpx_targets:
        try:
            from workers.guardian.tools.nuclei_tool import NucleiTool
            nc = NucleiTool(socketio)
            if nc.is_available():
                nres = nc.scan(httpx_targets[0], severity=["medium", "high", "critical"])
                for f in (nres.findings or [])[:25]:
                    tgt = getattr(f, "target", "") or ""
                    if _filter_in_scope([tgt], allowed):
                        nuclei_findings.append({
                            "template": getattr(f, "template", ""),
                            "severity": getattr(f, "severity", ""),
                            "target": tgt,
                            "description": getattr(f, "description", "")[:200],
                        })
                save_recon_artifact(session_id, "nuclei", nres.raw_output or "")
                results["tools_run"].append("nuclei")
                _log(f"Nuclei: {len(nuclei_findings)} in-scope finding(s)")
            else:
                results["skipped"].append("nuclei")
        except Exception as e:
            results["skipped"].append(f"nuclei:{e}")

    results["subdomains"] = subdomains
    results["hosts"] = hosts
    results["endpoints"] = endpoints
    results["nuclei_findings"] = nuclei_findings
    return results
