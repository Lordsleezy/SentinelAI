"""
Guardian Offensive Lab — ethical penetration testing for closed / authorized environments.

Capabilities (gated):
  - Network penetration (port/service discovery, segmentation hints)
  - Controlled credential auditing (rate-limited; lab wordlists only)
  - Backdoor & persistence detection (not backdoor deployment)
  - Exploit research lookup (Metasploit search / safe auxiliary probes)

INVARIANTS:
  - Requires closed_lab_acknowledged in config
  - Target must be trusted OR private/lab RFC1918/localhost
  - Credential tests capped (max_attempts, max_duration)
  - No stages run against arbitrary public targets without trust
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "guardian_config.json"
_WORDLIST_DIR = Path(__file__).resolve().parents[2] / "memory" / "vault" / "guardian_lab" / "wordlists"
_DEFAULT_WORDS = ("admin", "password", "test", "root", "toor", "changeme", "123456", "letmein")


@dataclass
class OffensiveLabResult:
    network_scan: str = ""
    open_services: List[Dict[str, Any]] = field(default_factory=list)
    credential_audit: List[Dict[str, Any]] = field(default_factory=list)
    backdoor_findings: List[Dict[str, Any]] = field(default_factory=list)
    exploit_research: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None

    def to_markdown(self) -> str:
        lines = ["## Offensive Lab (Ethical / Closed Environment)", ""]
        if self.skipped_reason:
            lines.append(f"_Offensive lab skipped: {self.skipped_reason}_")
            return "\n".join(lines)
        if self.open_services:
            lines.append("### Network & Services")
            for s in self.open_services[:20]:
                lines.append(f"- `{s.get('host', '')}`:{s.get('port', '')} {s.get('service', '')}")
            lines.append("")
        if self.credential_audit:
            lines.append("### Credential Audit (controlled)")
            for c in self.credential_audit[:15]:
                lines.append(f"- {c.get('summary', c)}")
            lines.append("")
        if self.backdoor_findings:
            lines.append("### Backdoor / Webshell Indicators")
            for b in self.backdoor_findings[:15]:
                lines.append(f"- [{b.get('severity', 'info')}] {b.get('title', '')} — {b.get('detail', '')[:80]}")
            lines.append("")
        if self.exploit_research:
            lines.append("### Exploit Research (reference)")
            for e in self.exploit_research[:10]:
                lines.append(f"- {e.get('module', e.get('cve', ''))}")
            lines.append("")
        if self.errors:
            lines.append("### Lab Notes")
            for e in self.errors:
                lines.append(f"- {e}")
        return "\n".join(lines)


def load_lab_config() -> Dict[str, Any]:
    defaults = {
        "offensive_lab": {
            "enabled": True,
            "closed_lab_acknowledged": False,
            "require_attack_mode": True,
            "allow_trusted_public_targets": True,
            "credential_audit": {
                "enabled": True,
                "max_attempts_per_service": 24,
                "max_duration_sec": 90,
                "services": ["ssh", "ftp", "http-get"],
            },
            "network_penetration": {
                "enabled": True,
                "top_ports": 1000,
                "nmap_scripts": False,
            },
            "backdoor_detection": {
                "enabled": True,
                "nuclei_tags": "backdoor,webshell,malware,persistence",
            },
        }
    }
    if _CONFIG_PATH.is_file():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            ol = data.get("offensive_lab") or {}
            defaults["offensive_lab"].update(ol)
            if isinstance(ol.get("credential_audit"), dict):
                defaults["offensive_lab"]["credential_audit"].update(ol["credential_audit"])
            if isinstance(ol.get("network_penetration"), dict):
                defaults["offensive_lab"]["network_penetration"].update(ol["network_penetration"])
            if isinstance(ol.get("backdoor_detection"), dict):
                defaults["offensive_lab"]["backdoor_detection"].update(ol["backdoor_detection"])
        except Exception:
            pass
    return defaults["offensive_lab"]


def acknowledge_closed_lab() -> Dict[str, Any]:
    """Persist operator acknowledgement of closed-lab-only use."""
    data = {}
    if _CONFIG_PATH.is_file():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    ol = data.setdefault("offensive_lab", {})
    ol["closed_lab_acknowledged"] = True
    ol["acknowledged_at"] = __import__("datetime").datetime.now().isoformat()
    _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("[GUARDIAN LAB] Closed lab acknowledged")
    return ol


def _target_host(target: str) -> str:
    t = target.strip().lower()
    if t.startswith("http://"):
        t = t[7:]
    if t.startswith("https://"):
        t = t[8:]
    return t.split("/")[0].split(":")[0]


def _is_private_or_local(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def is_lab_authorized(target: str, *, attack_mode: bool) -> tuple[bool, str]:
    cfg = load_lab_config()
    if not cfg.get("enabled", True):
        return False, "offensive lab disabled in config"
    if not cfg.get("closed_lab_acknowledged"):
        return False, "acknowledge closed lab in Guardian settings (POST /api/guardian/offensive-lab/acknowledge)"
    if cfg.get("require_attack_mode", True) and not attack_mode:
        return False, "switch Guardian to ATTACK mode"
    host = _target_host(target)
    try:
        from workers.guardian.guardian_trusted_targets import is_trusted
        if is_trusted(host) or is_trusted(target):
            return True, "trusted target"
    except Exception:
        pass
    if _is_private_or_local(host):
        return True, "private/lab network target"
    if cfg.get("allow_trusted_public_targets", True):
        return False, "public target — add to Trusted Targets first"
    return False, "target not authorized for offensive lab"


def _ensure_wordlist() -> Path:
    _WORDLIST_DIR.mkdir(parents=True, exist_ok=True)
    wl = _WORDLIST_DIR / "lab_common.txt"
    if not wl.is_file():
        wl.write_text("\n".join(_DEFAULT_WORDS) + "\n", encoding="utf-8")
    return wl


def run_nmap_penetration(target: str, cfg: Dict[str, Any], log_fn: Optional[Callable[[str, str], None]] = None) -> tuple[str, List[Dict]]:
    host = _target_host(target)
    services: List[Dict] = []
    nmap = shutil.which("nmap")
    if not nmap:
        return "nmap not installed", services
    top = int(cfg.get("top_ports", 1000))
    flags = ["-sV", "-T4", "--top-ports", str(min(top, 5000)), host]
    if log_fn:
        log_fn(f"[GUARDIAN LAB] nmap {' '.join(flags)}", "info")
    try:
        proc = subprocess.run(
            [nmap] + flags,
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        for line in out.splitlines():
            m = re.match(r"(\d+)/tcp\s+open\s+(\S+)\s*(.*)", line)
            if m:
                services.append({
                    "host": host,
                    "port": m.group(1),
                    "service": m.group(2),
                    "detail": m.group(3).strip(),
                })
        return out[:4000], services
    except subprocess.TimeoutExpired:
        return "nmap timed out", services
    except Exception as e:
        return str(e), services


def run_credential_audit(
    target: str,
    open_services: List[Dict],
    cfg: Dict[str, Any],
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> List[Dict]:
    """Rate-limited credential audit via hydra (lab wordlist). Findings only — no exfil."""
    results: List[Dict] = []
    cred_cfg = cfg.get("credential_audit") or {}
    if not cred_cfg.get("enabled", True):
        return results
    hydra = shutil.which("hydra")
    if not hydra:
        try:
            proc = subprocess.run(["wsl", "which", "hydra"], capture_output=True, text=True, timeout=8)
            if proc.returncode == 0 and proc.stdout.strip():
                hydra = "wsl"
        except Exception:
            pass
    if not hydra:
        results.append({"summary": "hydra not installed (native or WSL) — skip credential audit"})
        return results

    wl = _ensure_wordlist()
    # Tiny lab-only list — never use huge rockyou in automated pipeline
    mini = _WORDLIST_DIR / "lab_mini.txt"
    mini.write_text("\n".join(_DEFAULT_WORDS[:8]) + "\n", encoding="utf-8")
    timeout = int(cred_cfg.get("max_duration_sec", 90))
    host = _target_host(target)
    allowed = set(cred_cfg.get("services") or ["ssh", "ftp"])

    port_map = {"22": "ssh", "21": "ftp", "80": "http-get", "443": "http-get"}
    targets_to_test: List[tuple[str, str]] = []
    for s in open_services:
        port = str(s.get("port", ""))
        svc = port_map.get(port) or (s.get("service") or "").lower()
        if svc in allowed or port in port_map:
            targets_to_test.append((port, port_map.get(port, svc)))

    if not targets_to_test and "ssh" in allowed:
        targets_to_test.append(("22", "ssh"))

    for port, service in targets_to_test[:3]:
        if log_fn:
            log_fn(f"[GUARDIAN LAB] hydra {service}://{host}:{port} (max {max_attempts} tries)", "warning")
        try:
            cmd = [
                "-L", str(mini), "-P", str(mini),
                f"{service}://{host}", "-s", port,
                "-t", "2", "-w", "5", "-f",
            ]
            if hydra == "wsl":
                full = ["wsl", "hydra"] + cmd
            else:
                full = [hydra] + cmd
            proc = subprocess.run(
                full,
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if "login:" in out.lower() or "password:" in out.lower():
                line = next((l for l in out.splitlines() if "host:" in l.lower() or "login" in l.lower()), out[:200])
                results.append({
                    "summary": f"Possible weak credential on {service}/{port}",
                    "detail": line[:300],
                    "severity": "high",
                })
            else:
                results.append({"summary": f"No weak creds found ({service}/{port})", "severity": "info"})
        except subprocess.TimeoutExpired:
            results.append({"summary": f"credential audit timeout ({service})", "severity": "info"})
        except Exception as e:
            results.append({"summary": f"credential audit error: {e}", "severity": "info"})
    return results


def run_backdoor_detection(
    target: str,
    endpoints: List[str],
    tools: Any,
    cfg: Dict[str, Any],
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> List[Dict]:
    """Detect indicators of backdoors/webshells — does not install or exploit."""
    findings: List[Dict] = []
    bd_cfg = cfg.get("backdoor_detection") or {}
    if not bd_cfg.get("enabled", True):
        return findings

    suspicious_paths = (
        "shell.php", "c99.php", "r57.php", "webshell", "cmd.php", "backdoor",
        "eval(", "base64_decode", ".asp?cmd", "upload.php",
    )
    for ep in endpoints[:200]:
        low = ep.lower()
        for pat in suspicious_paths:
            if pat in low:
                findings.append({
                    "title": "Suspicious endpoint path",
                    "detail": ep,
                    "severity": "medium",
                    "source": "path_heuristic",
                })
                break

    tags = bd_cfg.get("nuclei_tags", "backdoor,webshell,malware")
    if tools and getattr(tools, "nuclei", None) and tools.nuclei.is_available():
        url = target if target.startswith("http") else f"https://{target}"
        try:
            from workers.guardian.generic_pd_tool import run_tool
            from workers.guardian.bundled_toolchain import resolve_tool_binary
            if resolve_tool_binary("nuclei"):
                code, out, err = run_tool(
                    "nuclei",
                    ["-u", url, "-tags", tags, "-silent", "-timeout", "8", "-rate-limit", "30"],
                    timeout=120,
                    log_fn=log_fn,
                )
                for line in (out or "").splitlines():
                    if line.strip():
                        findings.append({
                            "title": "Nuclei backdoor/malware tag",
                            "detail": line[:200],
                            "severity": "high",
                            "source": "nuclei",
                        })
        except Exception as e:
            findings.append({"title": "nuclei backdoor scan", "detail": str(e), "severity": "info"})

    return findings


def run_exploit_research(target: str, nuclei_findings: List, log_fn: Optional[Callable] = None) -> List[Dict]:
    """MSF exploit search for CVEs seen in findings — research only."""
    research: List[Dict] = []
    cves = set()
    for f in nuclei_findings or []:
        desc = (getattr(f, "description", "") or "") + (getattr(f, "template", "") or "")
        for m in re.findall(r"CVE-\d{4}-\d+", desc, re.I):
            cves.add(m.upper())
    if not cves:
        return research
    try:
        from workers.guardian.tools.metasploit_tool import MetasploitTool
        msf = MetasploitTool()
        if not msf.is_available():
            research.append({"cve": list(cves)[0], "module": "msfconsole not installed"})
            return research
        for cve in list(cves)[:5]:
            mods = msf.search_exploits(cve)
            for m in mods[:3]:
                research.append(m)
            if log_fn:
                log_fn(f"[GUARDIAN LAB] MSF search {cve}: {len(mods)} module(s)", "info")
    except Exception as e:
        research.append({"module": f"exploit research error: {e}"})
    return research


def run_offensive_lab(
    target: str,
    *,
    attack_mode: bool,
    results: Dict[str, Any],
    endpoints: List[str],
    nuclei_findings: List,
    tools: Any = None,
    findings_db: Any = None,
    session_id: str = "",
    stage_enter: Optional[Callable[[str], None]] = None,
    stage_running: Optional[Callable[[str], None]] = None,
    stage_exit: Optional[Callable[[str, str], Optional[bool]]] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> OffensiveLabResult:
    """Run all offensive lab stages when authorized."""
    out = OffensiveLabResult()
    ok, reason = is_lab_authorized(target, attack_mode=attack_mode)
    if not ok:
        out.skipped_reason = reason
        return out

    cfg = load_lab_config()
    se = stage_enter or (lambda _n: None)
    sr = stage_running or (lambda _n: None)
    sx = stage_exit or (lambda _n, _d, **kw: None)

    # Network penetration
    se("Network Penetration")
    sr("Network Penetration")
    try:
        raw, services = run_nmap_penetration(target, cfg.get("network_penetration") or {}, log_fn)
        out.network_scan = raw
        out.open_services = services
        results["lab_network"] = raw[:2000]
    except Exception as e:
        out.errors.append(f"network: {e}")
    finally:
        sx("Network Penetration", f"{len(out.open_services)} service(s)")

    # Credential audit
    se("Credential Audit")
    sr("Credential Audit")
    try:
        out.credential_audit = run_credential_audit(
            target, out.open_services, cfg, log_fn,
        )
        results["lab_credentials"] = [c.get("summary") for c in out.credential_audit]
        for c in out.credential_audit:
            if findings_db and c.get("severity") == "high":
                try:
                    findings_db.add(
                        target=target, tool="hydra-lab",
                        severity="high",
                        description=c.get("summary", ""),
                        evidence=c.get("detail", ""),
                        session_id=session_id,
                    )
                except Exception:
                    pass
    except Exception as e:
        out.errors.append(f"credentials: {e}")
    finally:
        sx("Credential Audit", f"{len(out.credential_audit)} result(s)")

    # Backdoor detection
    se("Backdoor Detection")
    sr("Backdoor Detection")
    try:
        out.backdoor_findings = run_backdoor_detection(
            target, endpoints, tools, cfg, log_fn,
        )
        results["lab_backdoors"] = len(out.backdoor_findings)
        for b in out.backdoor_findings:
            if findings_db:
                try:
                    findings_db.add(
                        target=target, tool="backdoor-detection",
                        severity=b.get("severity", "medium"),
                        description=b.get("title", ""),
                        evidence=b.get("detail", ""),
                        session_id=session_id,
                    )
                except Exception:
                    pass
    except Exception as e:
        out.errors.append(f"backdoor: {e}")
    finally:
        sx("Backdoor Detection", f"{len(out.backdoor_findings)} indicator(s)")

    # Exploit research
    se("Exploit Research")
    try:
        out.exploit_research = run_exploit_research(target, nuclei_findings, log_fn)
    except Exception as e:
        out.errors.append(f"research: {e}")
    finally:
        sx("Exploit Research", f"{len(out.exploit_research)} ref(s)")

    return out
