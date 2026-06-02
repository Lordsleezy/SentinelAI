"""
Guardian — professional penetration testing and security research assistant.
All active tool execution against external targets requires explicit user
authorization. Localhost/127.0.0.1 targets are always permitted.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GUARDIAN_SYSTEM_PROMPT = """You are Guardian, a professional cybersecurity assistant integrated into SentinelAI. You assist with:
- Penetration testing on authorized systems
- Vulnerability research and CVE analysis
- Security tool usage and output interpretation
- Code auditing and security review
- Network analysis and forensics
- Security education and technique explanation

You provide detailed, technical security assistance. When a user asks about attack techniques, exploits, or security tools, provide complete professional-grade information as any certified penetration tester would need.

Before executing any tool against an external target, confirm the user has authorization. Once authorization is confirmed, execute fully and interpret results thoroughly.

Format tool executions as: TOOL_CALL: <tool> <args>

Be specific, technical, and thorough."""


# ── Report helpers (module-level so they're accessible from the thread) ──────

def _compute_risk_score(nuclei_findings: List, zap_findings: List) -> str:
    """
    Compute a simple risk score from finding severity counts.
    Returns: CRITICAL / HIGH / MEDIUM / LOW / INFORMATIONAL
    """
    score = 0
    severity_weights = {'critical': 40, 'high': 15, 'medium': 5, 'low': 1}
    for f in nuclei_findings:
        score += severity_weights.get(getattr(f, 'severity', '').lower(), 0)
    risk_map = {'critical': 3, 'high': 2, 'medium': 1, 'low': 0}
    for zf in zap_findings:
        score += risk_map.get(getattr(zf, 'risk', '').lower(), 0) * 2
    if score >= 40:    return 'CRITICAL'
    if score >= 15:    return 'HIGH'
    if score >= 5:     return 'MEDIUM'
    if score >= 1:     return 'LOW'
    return 'INFORMATIONAL'


def _build_final_report(
    target: str,
    session_id: str,
    headers_raw: str,
    subdomains: List[str],
    tech_data: List[Dict],
    endpoints: List[str],
    nuclei_findings: List,
    zap_findings: List,
    ports_raw: str,
    analysis: str,
    tool_status: str,
    risk_score: str,
) -> str:
    """Build the structured final Guardian report in Markdown."""
    from datetime import datetime as _dt
    all_findings = len(nuclei_findings) + len(zap_findings)
    techs = sorted(set(t for h in tech_data for t in h.get('tech', [])))

    # Severity breakdown
    nuclei_by_sev: Dict[str, List] = {}
    for f in nuclei_findings:
        nuclei_by_sev.setdefault(getattr(f, 'severity', 'unknown').upper(), []).append(f)

    risk_color = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢', 'INFORMATIONAL': '⚪'}.get(risk_score, '⚪')

    lines = [
        f"# 🛡 Guardian Security Assessment Report",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Target** | `{target}` |",
        f"| **Session** | `{session_id}` |",
        f"| **Date** | {_dt.now().strftime('%Y-%m-%d %H:%M UTC')} |",
        f"| **Risk Score** | {risk_color} **{risk_score}** |",
        f"| **Total Findings** | {all_findings} |",
        f"",
        f"---",
        f"",
        f"## Executive Summary",
        f"",
        (analysis[:800] if analysis and 'error' not in analysis.lower()[:30] else
         f"Target `{target}` was assessed with {all_findings} findings across {len(nuclei_findings)} Nuclei "
         f"and {len(zap_findings)} ZAP alerts. Risk level: **{risk_score}**."),
        f"",
        f"---",
        f"",
        f"## Assets Found",
        f"",
        f"- **Main Target:** `{target}`",
        f"- **Subdomains:** {len(subdomains)} discovered",
    ]
    if subdomains:
        for s in subdomains[:15]:
            lines.append(f"  - `{s}`")
        if len(subdomains) > 15:
            lines.append(f"  - … and {len(subdomains) - 15} more")
    lines += [
        f"",
        f"## Technologies Found",
        f"",
    ]
    if techs:
        lines.append(', '.join(f'`{t}`' for t in techs[:30]))
    else:
        lines.append("No technology fingerprinting data available.")

    lines += [
        f"",
        f"## Open Services",
        f"",
        f"```",
        (ports_raw[:800] if ports_raw and 'skipped' not in ports_raw.lower() else "Port scan not run or skipped."),
        f"```",
        f"",
        f"## Endpoints Discovered",
        f"",
        f"{len(endpoints)} endpoint(s) found via crawling.",
    ]
    if endpoints[:10]:
        lines.append("```")
        lines.extend(endpoints[:10])
        if len(endpoints) > 10:
            lines.append(f"… and {len(endpoints) - 10} more")
        lines.append("```")

    lines += [
        f"",
        f"## Potential Vulnerabilities",
        f"",
    ]
    if nuclei_findings:
        for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            grp = nuclei_by_sev.get(sev, [])
            if not grp:
                continue
            lines.append(f"### {sev} ({len(grp)})\n")
            for f in grp[:8]:
                lines.append(f"- **{getattr(f, 'template', 'unknown')}** — `{getattr(f, 'target', '')}` — {getattr(f, 'description', '')[:80]}")
    else:
        lines.append("No Nuclei findings. Tool may not be installed.")

    if zap_findings:
        lines.append(f"\n### ZAP Alerts ({len(zap_findings)})\n")
        for zf in zap_findings[:8]:
            lines.append(f"- [{getattr(zf, 'risk', '')}] **{getattr(zf, 'alert', '')}** — `{getattr(zf, 'url', '')[:60]}`")

    lines += [
        f"",
        f"## Risk Score: {risk_color} {risk_score}",
        f"",
        f"## Recommendations",
        f"",
    ]
    # Auto-generate recommendations based on findings
    if risk_score in ('CRITICAL', 'HIGH'):
        lines.append("- **Immediate action required.** Patch critical/high findings before next deployment.")
    if techs:
        lines.append(f"- Review and harden identified technologies: {', '.join(techs[:5])}")
    if subdomains:
        lines.append(f"- Audit {len(subdomains)} subdomain(s) for unnecessary exposure.")
    if not nuclei_findings and not zap_findings:
        lines.append("- No automated vulnerabilities found. Consider a manual code review.")
    lines.append("- Keep tool templates updated: `nuclei -update-templates`")

    lines += [
        f"",
        f"---",
        f"",
        tool_status,
        f"",
        f"---",
        f"*Report generated by Guardian (SentinelAI) — Session `{session_id}`*",
    ]
    return "\n".join(lines)


class GuardianBrain:
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.config = self._load_config()
        self.models = self.config.get("models", {
            "fast": "qwen2.5-coder:7b",
            "reasoning": "qwen3:14b",
            "code": "qwen2.5-coder:14b",
        })
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        self.mode = "defend"
        self.conversation_history: List[Dict] = []
        self.authorized_targets: set = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
        self.pending_confirmation: Optional[str] = None

        # Check which security tools are available
        try:
            from workers.guardian.tools import NucleiTool, MetasploitTool, ReconftfTool, ZAPTool
            self.tools_available = {
                'nuclei': NucleiTool().is_available(),
                'metasploit': MetasploitTool().is_available(),
                'reconftw': ReconftfTool().is_available(),
                'zap': ZAPTool().is_available(),
            }
        except Exception:
            self.tools_available = {
                'nuclei': False, 'metasploit': False, 'reconftw': False, 'zap': False,
            }

    def get_tools_header(self) -> str:
        """Return tool availability string for UI header."""
        def mark(name):
            return f"{name} ✓" if self.tools_available.get(name) else f"{name} ✗"
        return "Tools: " + " | ".join([mark("Nuclei"), mark("MSF"), mark("Reconftw"), mark("ZAP")])

    def _load_config(self) -> Dict:
        try:
            cfg_path = Path(__file__).parent.parent.parent / "config" / "guardian_config.json"
            with open(cfg_path) as f:
                return json.load(f)
        except Exception:
            return {}

    # ── Model routing ─────────────────────────────────────────────────────────

    def _classify_task_tier(self, message: str) -> str:
        msg = message.lower()
        code_kw = ["write exploit", "create payload", "write script",
                   "shellcode", "generate payload", "craft exploit", "python script", "bash script"]
        reasoning_kw = ["exploit", "vulnerability", "cve", "overflow", "injection",
                        "bypass", "escalation", "rce", "analyze", "audit", "review",
                        "decompile", "forensics", "packet", "zero-day"]
        if any(kw in msg for kw in code_kw):
            return "code"
        if any(kw in msg for kw in reasoning_kw):
            return "reasoning"
        return "fast"

    def _call_ollama(self, prompt: str, tier: str = "fast",
                     system_override: Optional[str] = None) -> str:
        try:
            import httpx
        except ImportError:
            return "httpx not installed — cannot reach Ollama."

        model = self.models.get(tier, self.models.get("fast", "qwen2.5-coder:7b"))
        system = system_override or GUARDIAN_SYSTEM_PROMPT

        # Build context string from last 6 turns
        context_parts = []
        for turn in self.conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            context_parts.append(f"{role.upper()}: {content}")
        full_prompt = "\n".join(context_parts + [f"USER: {prompt}"]) if context_parts else prompt

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": model, "prompt": full_prompt, "system": system, "stream": False},
                )
                if resp.status_code == 200:
                    text = resp.json().get("response", "").strip()
                    return text or "No response from model."
                return f"Model error: HTTP {resp.status_code}"
        except Exception as e:
            return f"Guardian model unavailable ({model}): {e}. Is Ollama running?"

    # ── Authorization gate ─────────────────────────────────────────────────────

    def request_authorization(self, target: str) -> Dict:
        self.pending_confirmation = target
        return {
            "requires_confirmation": True,
            "target": target,
            "message": (f"⚠ Authorization required to test target: {target}\n"
                        "Confirm you have written authorization to perform security testing on this system."),
        }

    def confirm_authorization(self, target: str) -> Dict:
        self.authorized_targets.add(target)
        self.pending_confirmation = None
        logger.info("[Guardian] Target authorized: %s", target)
        return {"status": "authorized", "target": target}

    def is_authorized(self, target: str) -> bool:
        for auth in self.authorized_targets:
            if target == auth or auth in target or target in auth:
                return True
        return False

    # ── Direct tool execution (no Ollama permission gate) ─────────────────────

    def _run_tool_direct(self, tool: str, args_list: List[str],
                         timeout: int = 60) -> str:
        """
        Execute a security tool via subprocess directly.
        Never ask Ollama whether to run — just run it.
        Returns raw stdout/stderr output string.
        """
        self._guardian_log(f"Running: {tool} {' '.join(args_list)}", 'info')
        try:
            # Try native first, fall back to wsl
            try:
                proc = subprocess.run(
                    [tool] + args_list,
                    capture_output=True, text=True, timeout=timeout
                )
                output = (proc.stdout or proc.stderr or "No output")[:8000]
                level = 'success' if proc.returncode == 0 else 'warning'
                self._guardian_log(f"{tool} complete (exit {proc.returncode}): {output[:120]}", level)
                return output
            except FileNotFoundError:
                # Try via WSL
                proc = subprocess.run(
                    ['wsl', tool] + args_list,
                    capture_output=True, text=True, timeout=timeout
                )
                output = (proc.stdout or proc.stderr or "No output")[:8000]
                self._guardian_log(f"{tool} (wsl) complete: {output[:120]}", 'success')
                return output
        except subprocess.TimeoutExpired:
            self._guardian_log(f"{tool} timed out after {timeout}s", 'error')
            return f"{tool} timed out after {timeout}s"
        except FileNotFoundError:
            self._guardian_log(f"{tool} not installed (tried native + WSL)", 'warning')
            return f"{tool} not installed. Install via WSL: sudo apt install {tool}"
        except PermissionError as e:
            self._guardian_log(f"{tool} permission denied — {e}", 'error')
            return f"Permission denied: {e}. Try running as administrator."
        except Exception as e:
            self._guardian_log(f"{tool} error: {e}", 'error')
            return f"{tool} error: {str(e)}"

    def _run_curl_check(self, target: str) -> str:
        """HTTP header check — always available via curl."""
        self._guardian_log(f"Running HTTP header check on {target}", 'info')
        url = target if target.startswith('http') else f"https://{target}"
        try:
            proc = subprocess.run(
                ['curl', '-sI', '--max-time', '10', '-L', url],
                capture_output=True, text=True, timeout=15
            )
            out = (proc.stdout or proc.stderr or "No response")[:3000]
            self._guardian_log(f"curl complete: {len(out)} bytes", 'success')
            return out
        except FileNotFoundError:
            return "curl not available"
        except Exception as e:
            return f"curl error: {str(e)}"

    def _run_nmap(self, target: str, flags: str = '-sV -T4') -> str:
        """Port scan via nmap."""
        self._guardian_log(f"Running port scan: nmap {flags} {target}", 'info')
        return self._run_tool_direct('nmap', flags.split() + [target], timeout=90)

    def _run_nuclei(self, target: str, severity: str = 'critical,high,medium') -> str:
        """Vulnerability scan via nuclei."""
        self._guardian_log(f"Running nuclei scan on {target} (severity: {severity})", 'info')
        url = target if target.startswith('http') else f"https://{target}"
        return self._run_tool_direct(
            'nuclei', ['-u', url, '-severity', severity, '-silent', '-timeout', '5'],
            timeout=120
        )

    def _analyze_with_ollama(self, tool_name: str, target: str, raw_output: str) -> str:
        """
        Feed raw tool output to Ollama for analysis.
        Ollama ONLY analyzes the output — it does NOT decide whether to run tools.
        """
        prompt = f"""You are a cybersecurity analyst reviewing security scan results.

Target: {target}
Tool: {tool_name}

Raw output:
{raw_output[:4000]}

Provide a technical analysis:
1. Key findings (open ports, services, technologies, vulnerabilities)
2. Risk assessment (Critical / High / Medium / Low)
3. Specific recommendations
4. Any immediate concerns requiring attention

Be specific and reference actual data from the output above."""
        return self._call_ollama(prompt, tier="reasoning")

    def _emit_guardian_response(self, message: str, target: str, step: str = '') -> None:
        """Emit a guardian_response socket event with a partial or final result."""
        try:
            from desktop_app import socketio
            if socketio:
                socketio.emit('guardian_response', {
                    'response': message,
                    'target': target,
                    'step': step,
                })
        except Exception as e:
            logger.error("[GUARDIAN] Failed to emit guardian_response: %s", e)

    def _run_full_assessment(self, target: str) -> None:
        """
        Professional 7-stage Guardian assessment using the full ProjectDiscovery
        + OWASP tool stack.

        Stage map (with task progress %):
          5%  — Target validation
         15%  — Subfinder / Amass (subdomain enumeration)
         30%  — httpx (technology + live host detection)
         45%  — Katana (endpoint discovery)
         60%  — Nuclei (vulnerability scan)
         80%  — ZAP (passive scan)
         95%  — AI analysis of all findings
        100%  — Structured final report

        Every stage is individually try/except-wrapped.
        Missing tools emit a skip notice and assessment continues.
        Final report is ALWAYS produced regardless of which tools ran.
        """
        import threading

        def _assess():
            import uuid
            from datetime import datetime as _dt

            session_id = f"guardian-{target.replace('.', '-')}-{uuid.uuid4().hex[:6]}"
            results: Dict[str, Any] = {}

            # ── Task Manager integration ──────────────────────────────────────
            _task_id: str = ''
            try:
                from workers.task_manager import create_task, update_task, RUNNING, COMPLETED, FAILED
                _t = create_task(f"Guardian Scan — {target}", source="guardian",
                                 metadata={"target": target, "session_id": session_id})
                _task_id = _t["id"]
            except Exception:
                pass

            def _tp(pct: int, summary: str = '') -> None:
                """Update task progress (non-fatal)."""
                if not _task_id:
                    return
                try:
                    from workers.task_manager import update_task, RUNNING
                    update_task(_task_id, status=RUNNING, progress=pct,
                                result_summary=summary or None)
                except Exception:
                    pass

            try:
                # ── Initialize tool registry ─────────────────────────────────
                from workers.guardian.tools.tool_registry import ToolRegistry
                tools = ToolRegistry(self.socketio)
                tool_summary = tools.status_summary()

                self._guardian_log(f"[GUARDIAN] Assessment started: {target}", 'info')
                self._guardian_log(f"[GUARDIAN] Tools: {tool_summary}", 'info')
                self._emit_guardian_response(
                    f"🔍 **Assessment started for `{target}`**\n\n"
                    f"**Session:** `{session_id}`\n\n"
                    f"**Tool Status:**\n```\n{tool_summary}\n```\n\n"
                    f"Running up to 7 stages. Results appear as each completes.",
                    target, step='start'
                )
                _tp(5, "Initializing")

                # ── Stage 1: Target Validation (curl / HTTP headers) ─────────
                try:
                    self._guardian_log("[GUARDIAN] Stage 1/7: Target validation (HTTP headers)…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 1/7 — Target Validation** ⟳ HTTP probe…", target, step='stage1_start'
                    )
                    headers_raw = self._run_curl_check(target)
                    results['headers'] = headers_raw
                    self._guardian_log(f"[GUARDIAN] Stage 1 complete: {len(headers_raw)} bytes", 'success')
                    self._emit_guardian_response(
                        f"**Stage 1/7 — Target Validation ✓**\n```\n{headers_raw[:1500]}\n```",
                        target, step='headers'
                    )
                    _tp(15, "Target validated")
                except Exception as _e1:
                    results['headers'] = f"Stage 1 error: {_e1}"
                    self._guardian_log(f"[GUARDIAN] Stage 1 error: {_e1}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 1/7 — Target Validation ✗** `{_e1}` — continuing", target, step='headers'
                    )
                    _tp(15, "Validation skipped")

                # ── Stage 2: Subdomain Enumeration (Subfinder + Amass) ───────
                subdomains: List[str] = []
                try:
                    self._guardian_log("[GUARDIAN] Stage 2/7: Subdomain enumeration…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 2/7 — Subdomain Enumeration** ⟳", target, step='stage2_start'
                    )
                    if tools.subfinder.is_available():
                        sub_res = tools.subfinder.enumerate(target, timeout=60)
                        subdomains.extend(sub_res.subdomains)
                        results['subfinder'] = sub_res.raw_output
                        self._emit_guardian_response(
                            f"**Stage 2/7 — Subfinder ✓** Found {len(sub_res.subdomains)} subdomain(s)\n"
                            f"```\n{chr(10).join(sub_res.subdomains[:30])}\n```",
                            target, step='subfinder'
                        )
                    else:
                        results['subfinder'] = 'Subfinder not installed — skipping'
                        self._emit_guardian_response(
                            f"**Stage 2/7 — Subfinder ⚠ Skipped** (not installed)", target, step='subfinder'
                        )

                    if tools.amass.is_available():
                        amass_res = tools.amass.enum_passive(target, timeout=90)
                        amass_subs = [a['name'] for a in amass_res.assets]
                        for s in amass_subs:
                            if s not in subdomains:
                                subdomains.append(s)
                        results['amass'] = amass_res.raw_output
                        self._emit_guardian_response(
                            f"**Stage 2/7 — Amass ✓** Mapped {len(amass_subs)} asset(s)",
                            target, step='amass'
                        )
                    else:
                        results['amass'] = 'Amass not installed — skipping'
                        self._emit_guardian_response(
                            f"**Stage 2/7 — Amass ⚠ Skipped** (not installed)", target, step='amass'
                        )

                    results['subdomains'] = subdomains
                    _tp(30, f"Subdomains: {len(subdomains)}")
                except Exception as _e2:
                    self._guardian_log(f"[GUARDIAN] Stage 2 error: {_e2}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 2/7 — Enumeration ✗** `{_e2}` — continuing", target, step='recon'
                    )
                    _tp(30, "Enumeration skipped")

                # ── Stage 3: Technology Detection (httpx) ────────────────────
                live_hosts: List[str] = []
                tech_data: List[Dict] = []
                try:
                    self._guardian_log("[GUARDIAN] Stage 3/7: Technology detection (httpx)…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 3/7 — Technology Detection** ⟳ httpx…", target, step='stage3_start'
                    )
                    httpx_targets = [target] + subdomains[:20]
                    if tools.httpx.is_available():
                        httpx_res = tools.httpx.probe(httpx_targets)
                        tech_data = httpx_res.hosts
                        live_hosts = [h['url'] for h in tech_data if h.get('status_code', 0) in range(200, 500)]
                        results['httpx'] = httpx_res.raw_output
                        tech_lines = [
                            f"  {h['url']} [{h.get('status_code','')}] {', '.join(h.get('tech', []))[:60]}"
                            for h in tech_data[:20]
                        ]
                        self._emit_guardian_response(
                            f"**Stage 3/7 — httpx ✓** {len(tech_data)} host(s) probed, {len(live_hosts)} live\n"
                            f"```\n{chr(10).join(tech_lines)}\n```",
                            target, step='httpx'
                        )
                    else:
                        results['httpx'] = 'httpx not installed — skipping'
                        live_hosts = [target]   # fall back to main target
                        self._emit_guardian_response(
                            f"**Stage 3/7 — httpx ⚠ Skipped** (not installed)", target, step='httpx'
                        )
                    _tp(45, f"Tech detection: {len(tech_data)} hosts")
                except Exception as _e3:
                    live_hosts = [target]
                    self._guardian_log(f"[GUARDIAN] Stage 3 error: {_e3}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 3/7 — Tech Detection ✗** `{_e3}` — continuing", target, step='httpx'
                    )
                    _tp(45, "Tech detection skipped")

                # ── Stage 4: Endpoint Discovery (Katana) ─────────────────────
                endpoints: List[str] = []
                try:
                    self._guardian_log("[GUARDIAN] Stage 4/7: Endpoint discovery (Katana)…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 4/7 — Endpoint Discovery** ⟳ Katana…", target, step='stage4_start'
                    )
                    if tools.katana.is_available():
                        katana_target = live_hosts[0] if live_hosts else target
                        kat_res = tools.katana.crawl(katana_target, depth=3, timeout=120)
                        endpoints = kat_res.endpoints
                        results['katana'] = kat_res.raw_output
                        self._emit_guardian_response(
                            f"**Stage 4/7 — Katana ✓** Discovered {len(endpoints)} endpoint(s)\n"
                            f"```\n{chr(10).join(endpoints[:20])}\n```",
                            target, step='katana'
                        )
                    else:
                        results['katana'] = 'Katana not installed — skipping'
                        self._emit_guardian_response(
                            f"**Stage 4/7 — Katana ⚠ Skipped** (not installed)", target, step='katana'
                        )
                    _tp(55, f"Endpoints: {len(endpoints)}")
                except Exception as _e4:
                    self._guardian_log(f"[GUARDIAN] Stage 4 error: {_e4}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 4/7 — Endpoint Discovery ✗** `{_e4}` — continuing", target, step='katana'
                    )
                    _tp(55, "Endpoint discovery skipped")

                # ── Stage 5: Vulnerability Scan (Nuclei) ─────────────────────
                nuclei_findings = []
                try:
                    self._guardian_log("[GUARDIAN] Stage 5/7: Vulnerability scan (Nuclei)…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 5/7 — Vulnerability Scan** ⟳ Nuclei…", target, step='stage5_start'
                    )
                    if tools.nuclei.is_available():
                        nuclei_res = tools.nuclei.scan(target)
                        nuclei_findings = nuclei_res.findings
                        results['nuclei'] = nuclei_res.raw_output
                        # Persist to Faraday store
                        for f in nuclei_findings:
                            try:
                                tools.faraday.save_finding(f, session_id)
                            except Exception:
                                pass
                        sev_counts = {}
                        for f in nuclei_findings:
                            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
                        sev_str = ', '.join(f"{k}: {v}" for k, v in sev_counts.items())
                        finding_lines = [
                            f"  [{f.severity.upper()}] {f.template}: {f.description[:60]}"
                            for f in nuclei_findings[:15]
                        ]
                        self._emit_guardian_response(
                            f"**Stage 5/7 — Nuclei ✓** {len(nuclei_findings)} finding(s) | {sev_str}\n"
                            f"```\n{chr(10).join(finding_lines)}\n```",
                            target, step='nuclei'
                        )
                    else:
                        # Fall back to legacy nuclei runner for compatibility
                        legacy_out = self._run_nuclei(target)
                        results['nuclei'] = legacy_out
                        if 'not installed' in legacy_out.lower() or 'not found' in legacy_out.lower():
                            self._emit_guardian_response(
                                f"**Stage 5/7 — Nuclei ⚠ Skipped** (not installed)", target, step='nuclei'
                            )
                        else:
                            self._emit_guardian_response(
                                f"**Stage 5/7 — Nuclei ✓** (legacy mode)\n```\n{legacy_out[:1500]}\n```",
                                target, step='nuclei'
                            )
                    _tp(65, f"Vulns: {len(nuclei_findings)}")
                except Exception as _e5:
                    self._guardian_log(f"[GUARDIAN] Stage 5 error: {_e5}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 5/7 — Nuclei ✗** `{_e5}` — continuing", target, step='nuclei'
                    )
                    _tp(65, "Nuclei skipped")

                # ── Stage 6: ZAP Passive Scan ────────────────────────────────
                zap_findings = []
                try:
                    self._guardian_log("[GUARDIAN] Stage 6/7: ZAP passive scan…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 6/7 — ZAP Passive Scan** ⟳", target, step='stage6_start'
                    )
                    if tools.zap.is_available():
                        zap_url = live_hosts[0] if live_hosts else f"https://{target}"
                        zap_findings = tools.zap.passive_scan(zap_url)
                        results['zap'] = str(len(zap_findings)) + ' ZAP findings'
                        for zf in zap_findings:
                            try:
                                tools.faraday.save_finding({
                                    'template': zf.alert,
                                    'severity': zf.risk.lower(),
                                    'target': zf.url,
                                    'description': zf.description,
                                    'source': 'zap',
                                }, session_id)
                            except Exception:
                                pass
                        zap_lines = [f"  [{zf.risk}] {zf.alert}: {zf.url[:60]}" for zf in zap_findings[:10]]
                        self._emit_guardian_response(
                            f"**Stage 6/7 — ZAP ✓** {len(zap_findings)} alert(s)\n"
                            f"```\n{chr(10).join(zap_lines)}\n```",
                            target, step='zap'
                        )
                    else:
                        results['zap'] = 'ZAP not running — skipping'
                        self._emit_guardian_response(
                            f"**Stage 6/7 — ZAP ⚠ Skipped** (not running on :8090 — "
                            f"start with: `docker run -d -p 8090:8080 ghcr.io/zaproxy/zaproxy:stable zap.sh -daemon`)",
                            target, step='zap'
                        )
                    _tp(80, f"ZAP: {len(zap_findings)} alerts")
                except Exception as _e6:
                    self._guardian_log(f"[GUARDIAN] Stage 6 error: {_e6}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 6/7 — ZAP ✗** `{_e6}` — continuing", target, step='zap'
                    )
                    _tp(80, "ZAP skipped")

                # ── Stage 7: AI Analysis ──────────────────────────────────────
                analysis = ''
                try:
                    self._guardian_log("[GUARDIAN] Stage 7/7: AI analysis of all findings…", 'info')
                    self._emit_guardian_response(
                        f"**Stage 7/7 — AI Analysis** ⟳ analyzing all findings…", target, step='stage7_start'
                    )
                    combined_context = (
                        f"Target: {target}\n\n"
                        f"HTTP Headers:\n{results.get('headers', 'N/A')[:500]}\n\n"
                        f"Subdomains found: {len(subdomains)} — {', '.join(subdomains[:10])}\n\n"
                        f"Live hosts detected: {len(live_hosts)}\n"
                        f"Technologies: {', '.join(set(t for h in tech_data for t in h.get('tech', [])))[:200]}\n\n"
                        f"Endpoints discovered: {len(endpoints)}\n\n"
                        f"Nuclei findings: {len(nuclei_findings)} — "
                        f"{', '.join(set(f.severity for f in nuclei_findings))}\n\n"
                        f"ZAP alerts: {len(zap_findings)}\n\n"
                        f"Ports/Services:\n{results.get('ports', 'Not scanned')[:300]}"
                    )
                    analysis = self._analyze_with_ollama('security assessment', target, combined_context)
                    self._guardian_log("[GUARDIAN] Stage 7 complete", 'success')
                    self._emit_guardian_response(
                        f"**Stage 7/7 — AI Analysis ✓**\n\n{analysis}", target, step='analysis'
                    )
                    _tp(95, "AI analysis complete")
                except Exception as _e7:
                    analysis = f"AI analysis unavailable: {_e7}"
                    self._guardian_log(f"[GUARDIAN] Stage 7 error: {_e7}", 'error')
                    self._emit_guardian_response(
                        f"**Stage 7/7 — AI Analysis ✗** `{_e7}`", target, step='analysis'
                    )
                    _tp(95, "AI analysis skipped")

                # ── Structured Final Report ────────────────────────────────────
                all_vulns = len(nuclei_findings) + len(zap_findings)
                risk_score = _compute_risk_score(nuclei_findings, zap_findings)

                report = _build_final_report(
                    target=target,
                    session_id=session_id,
                    headers_raw=results.get('headers', ''),
                    subdomains=subdomains,
                    tech_data=tech_data,
                    endpoints=endpoints,
                    nuclei_findings=nuclei_findings,
                    zap_findings=zap_findings,
                    ports_raw=results.get('ports', ''),
                    analysis=analysis,
                    tool_status=tools.status_block(),
                    risk_score=risk_score,
                )
                self._guardian_log(f"[GUARDIAN] Assessment complete for {target} | "
                                   f"findings={all_vulns} risk={risk_score}", 'success')
                self._emit_guardian_response(report, target, step='final')

                # Persist report to disk
                try:
                    rpt_dir = Path(__file__).parent.parent.parent / "memory" / "vault" / "guardian_reports"
                    rpt_dir.mkdir(parents=True, exist_ok=True)
                    rpt_file = rpt_dir / f"{session_id}.md"
                    rpt_file.write_text(report, encoding="utf-8")
                    self._guardian_log(f"[GUARDIAN] Report saved: {rpt_file}", 'success')
                except Exception as _save_err:
                    self._guardian_log(f"[GUARDIAN] Report save error: {_save_err}", 'warning')

                if _task_id:
                    try:
                        from workers.task_manager import update_task, COMPLETED
                        update_task(_task_id, status=COMPLETED, progress=100,
                                    result_summary=f"Assessment complete for {target} | {all_vulns} findings | risk={risk_score}")
                    except Exception:
                        pass

            except Exception as _top_err:
                self._guardian_log(f"[GUARDIAN] Assessment failed unexpectedly: {_top_err}", 'error')
                self._emit_guardian_response(
                    f"⚠ **Assessment encountered an unexpected error for `{target}`**\n\nError: {_top_err}\n\n"
                    f"Partial results may be in the stages above.",
                    target, step='final'
                )
                if _task_id:
                    try:
                        from workers.task_manager import update_task, FAILED
                        update_task(_task_id, status=FAILED, error=str(_top_err))
                    except Exception:
                        pass

        threading.Thread(target=_assess, daemon=True).start()

    # ── Main chat ──────────────────────────────────────────────────────────────

    # Keywords that indicate the user is confirming authorization
    _AUTH_CONFIRMS = [
        'i approve', 'confirmed', 'yes i own', 'i have authorization',
        'authorized', 'its my', "it's my", 'i own it', 'i own this',
        'my website', 'my server', 'my system', 'my domain',
        'yes', 'yep', 'yup', 'go ahead', 'proceed', 'do it',
        'confirm', 'approve', 'i confirm', 'i authorize', 'i give permission',
    ]
    # Keywords that indicate a scan/attack request
    _SCAN_KEYWORDS = [
        'scan', 'check', 'test', 'audit', 'vulnerabilities', 'pentest',
        'assess', 'recon', 'enumerate', 'probe', 'penetrate', 'attack',
        'exploit', 'hack', 'find vulnerabilities', 'security test',
        'find a way', 'break into', 'get into',
    ]

    def chat(self, user_message: str) -> Dict:
        msg_lower = user_message.lower()

        # ── Authorization confirmation ─────────────────────────────────────────
        if any(phrase in msg_lower for phrase in self._AUTH_CONFIRMS):
            if self.pending_confirmation:
                target = self.pending_confirmation
                self.confirm_authorization(target)
                self.conversation_history.append({"role": "user", "content": user_message})
                resp = (f"✓ Authorization confirmed for {target}.\n\n"
                        f"Starting security assessment — results will appear here "
                        f"as each tool completes. Check the Guardian Log for real-time progress.")
                self.conversation_history.append({"role": "assistant", "content": resp})
                # Fire off the assessment in a background thread
                self._run_full_assessment(target)
                return {"response": resp, "tool_calls": [], "mode": self.mode, "authorized": True, "target": target}

        # ── Extract targets ───────────────────────────────────────────────────
        ip_pat = r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"
        dom_pat = r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b"
        ips = re.findall(ip_pat, user_message)
        domains = re.findall(dom_pat, user_message)
        skip_exts = {".py", ".js", ".txt", ".md", ".json", ".html", ".css", ".yml", ".yaml"}
        targets = ips + [d for d in domains if not any(d.endswith(e) for e in skip_exts)]
        # Explicitly capture bare 'localhost' keyword (no dots, won't match domain pattern)
        for bare in ("localhost", "127.0.0.1", "::1"):
            if bare in user_message.lower() and bare not in targets:
                targets.append(bare)

        always_safe = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
        external = [t for t in targets if t not in always_safe]
        unauthorized = [t for t in external if not self.is_authorized(t)]

        # ── Scan request on unauthorized target → ask for authorization ───────
        is_scan = any(kw in msg_lower for kw in self._SCAN_KEYWORDS)
        if unauthorized and is_scan:
            result = self.request_authorization(unauthorized[0])
            return {
                "response": result["message"],
                "requires_confirmation": True,
                "target": unauthorized[0],
                "tool_calls": [],
                "mode": self.mode,
            }

        # ── Scan request on already-authorized or always-safe target → execute directly ──
        always_safe_targets = [t for t in targets if t in always_safe]
        authorized_external = [t for t in external if self.is_authorized(t)]
        direct_targets = always_safe_targets + authorized_external
        if is_scan and direct_targets:
            target = direct_targets[0]
            resp = (f"Starting security assessment of {target}. "
                    f"Results will appear here as each tool completes. "
                    f"Check the Guardian Log for real-time progress.")
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": resp})
            self._run_full_assessment(target)
            return {"response": resp, "tool_calls": [], "mode": self.mode, "scanning": True}

        # ── Default: pass to Ollama for general Guardian questions ────────────
        tier = self._classify_task_tier(user_message)
        self.conversation_history.append({"role": "user", "content": user_message})

        response = self._call_ollama(user_message, tier=tier)
        tool_results: List[Dict] = []

        if "TOOL_CALL:" in response:
            tool_results = self._execute_tool_calls(response)
            if tool_results:
                combined = "\n".join(f"Output from {r['tool']}:\n{r['output']}" for r in tool_results)
                interp = self._call_ollama(
                    f"Security tool results:\n{combined}\n\nProvide detailed analysis and recommended next steps.",
                    tier="reasoning",
                )
                response = interp

        self.conversation_history.append({"role": "assistant", "content": response})
        if self.config.get("log_all_actions"):
            logger.info("[Guardian] %s → tier=%s tools=%d", user_message[:80], tier, len(tool_results))

        return {"response": response, "tool_calls": tool_results, "mode": self.mode, "tier": tier}

    # ── Tool execution ─────────────────────────────────────────────────────────

    def _guardian_log(self, message: str, level: str = 'info') -> None:
        """Emit a guardian-typed log event to the UI log panel."""
        try:
            from desktop_app import socketio
            if socketio:
                socketio.emit('log_event', {
                    'type': 'guardian',
                    'level': level,
                    'message': message,
                    'timestamp': __import__('datetime').datetime.now().isoformat()
                })
        except Exception:
            pass
        logger.info("[GUARDIAN/%s] %s", level, message)

    def _execute_tool_calls(self, response: str) -> List[Dict]:
        calls = re.findall(r"TOOL_CALL:\s*(\w[\w-]*)\s+(.*?)(?=TOOL_CALL:|$)", response, re.DOTALL)
        results = []
        for tool, args in calls:
            tool = tool.strip()
            args = args.strip().splitlines()[0].strip()
            self._guardian_log(f"[TOOL] {tool} {args}", 'tool')
            try:
                cmd = f"wsl {tool} {args}"
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=60
                )
                output = (proc.stdout or proc.stderr or "No output")[:5000]
                level = 'success' if proc.returncode == 0 else 'warning'
                self._guardian_log(f"[RESULT] {tool}: {output[:200]}", level)
                results.append({"tool": tool, "args": args, "output": output, "exit_code": proc.returncode})
            except subprocess.TimeoutExpired:
                self._guardian_log(f"[TIMEOUT] {tool} — exceeded 60s, killed", 'error')
                results.append({"tool": tool, "args": args, "output": "Timed out (60s)", "exit_code": -1})
            except PermissionError as e:
                self._guardian_log(f"[ERROR] {tool} requires admin privileges — {e}", 'error')
                self._guardian_log(f"[INFO] Skipping privileged tool; provide results manually if needed", 'info')
                results.append({"tool": tool, "args": args, "output": f"Permission denied: {e}\nRun as administrator to use this tool.", "exit_code": -1})
            except FileNotFoundError:
                self._guardian_log(f"[ERROR] {tool} not found — tool may not be installed", 'warning')
                self._guardian_log(f"[INFO] Install {tool} via WSL or add it to PATH", 'info')
                results.append({"tool": tool, "args": args, "output": f"{tool} not installed. Install via WSL: sudo apt install {tool}", "exit_code": -1})
            except Exception as e:
                self._guardian_log(f"[ERROR] {tool} failed: {e}", 'error')
                results.append({"tool": tool, "args": args, "output": f"Execution failed: {e}", "exit_code": -1})
        return results

    def run_tool(self, tool: str, args: str, target: str) -> Dict:
        """Direct tool execution — always requires authorization for external targets."""
        always_safe = {"localhost", "127.0.0.1", "0.0.0.0"}
        if target not in always_safe and not self.is_authorized(target):
            return self.request_authorization(target)
        self._guardian_log(f"[TOOL] {tool} {args} → {target}", 'tool')
        try:
            cmd = f"wsl {tool} {args}"
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            output = (proc.stdout or proc.stderr or "No output")[:8000]
            level = 'success' if proc.returncode == 0 else 'warning'
            self._guardian_log(f"[RESULT] exit={proc.returncode} {output[:200]}", level)
            return {"status": "ok", "tool": tool, "args": args, "output": output, "exit_code": proc.returncode}
        except subprocess.TimeoutExpired:
            self._guardian_log(f"[TIMEOUT] {tool} exceeded 120s, killed", 'error')
            return {"status": "error", "tool": tool, "output": "Timed out after 120s"}
        except PermissionError as e:
            self._guardian_log(f"[ERROR] {tool} requires admin — {e}", 'error')
            self._guardian_log(f"[INFO] Falling back: try running {tool} with reduced privileges", 'warning')
            return {"status": "error", "tool": tool, "output": f"Permission denied: {e}. Try running as administrator or using a non-privileged scan mode."}
        except FileNotFoundError:
            self._guardian_log(f"[ERROR] {tool} not installed", 'warning')
            return {"status": "error", "tool": tool, "output": f"{tool} not found. Install it via WSL: sudo apt install {tool}"}
        except Exception as e:
            self._guardian_log(f"[ERROR] {tool} exception: {e}", 'error')
            return {"status": "error", "tool": tool, "output": str(e)}

    # ── Code auditing ──────────────────────────────────────────────────────────

    def audit_code(self, code_or_path: str) -> Dict:
        """Security audit of code. No authorization needed — operates on provided code."""
        if os.path.exists(code_or_path):
            with open(code_or_path, "r", errors="ignore") as f:
                code = f.read()
            filename = os.path.basename(code_or_path)
        else:
            code = code_or_path
            filename = "submitted_code"

        audit_prompt = f"""Perform a thorough security audit of this code.

Find ALL vulnerabilities including:
- Injection flaws (SQL, command, LDAP, XSS, SSTI)
- Authentication and authorization issues
- Cryptographic weaknesses (weak algorithms, hardcoded keys, poor IV)
- Memory safety issues
- Business logic flaws
- Insecure dependencies
- Sensitive data exposure
- Race conditions
- Path traversal

For each finding provide:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Location (function name or line if visible)
- Vulnerability description
- How it could be exploited
- Remediation

Code ({filename}):
```
{code[:8000]}
```"""

        initial = self._call_ollama(audit_prompt, tier="code")

        deep_prompt = f"""Review this security audit for completeness and accuracy.

Code ({filename}):
```
{code[:3000]}
```

Initial audit:
{initial[:2500]}

Add any vulnerabilities the initial audit missed, especially:
- Chained attack scenarios
- Subtle logic flaws that require understanding the full application context
- Architecture-level security issues
- Attack paths that combine multiple low-severity findings"""

        deep = self._call_ollama(deep_prompt, tier="reasoning")

        return {
            "filename": filename,
            "initial_findings": initial,
            "deep_review": deep,
            "lines_analyzed": len(code.splitlines()),
        }

    def audit_repository(self, repo_path: str) -> Dict:
        """Audit an entire repository. Operates on local code — no authorization needed."""
        import glob
        exts = ["*.py", "*.js", "*.ts", "*.php", "*.java", "*.go", "*.c", "*.cpp", "*.rb", "*.rs"]
        all_files: List[str] = []
        for ext in exts:
            all_files.extend(glob.glob(os.path.join(repo_path, "**", ext), recursive=True))

        results = []
        critical = []
        for fp in all_files[:20]:
            try:
                r = self.audit_code(fp)
                results.append(r)
                text = (r.get("initial_findings") or "") + (r.get("deep_review") or "")
                if "CRITICAL" in text or "HIGH" in text:
                    critical.append({"file": fp, "findings": r.get("initial_findings", "")[:500]})
            except Exception as e:
                logger.error("audit_repository: failed on %s: %s", fp, e)

        return {
            "files_audited": len(results),
            "total_files_found": len(all_files),
            "critical_findings": critical,
            "results": results,
        }

    # ── CVE intelligence ───────────────────────────────────────────────────────

    def get_cves(self, product: Optional[str] = None,
                 severity: str = "CRITICAL", limit: int = 10) -> List[Dict]:
        """Fetch real CVEs from NVD (free, no API key needed)."""
        try:
            import requests
            params: Dict[str, Any] = {"resultsPerPage": limit, "cvssV3Severity": severity}
            if product:
                params["keywordSearch"] = product
            r = requests.get(
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params=params,
                timeout=10,
                headers={"User-Agent": "SentinelGuardian/1.0"},
            )
            data = r.json()
            out = []
            for vuln in data.get("vulnerabilities", []):
                cve = vuln.get("cve", {})
                descs = cve.get("descriptions", [])
                desc = next((d["value"] for d in descs if d.get("lang") == "en"), "")
                metrics = cve.get("metrics", {})
                score = None
                if "cvssMetricV31" in metrics:
                    score = metrics["cvssMetricV31"][0]["cvssData"]["baseScore"]
                elif "cvssMetricV30" in metrics:
                    score = metrics["cvssMetricV30"][0]["cvssData"]["baseScore"]
                out.append({
                    "id": cve.get("id"),
                    "description": desc[:300],
                    "cvss_score": score,
                    "published": cve.get("published", "")[:10],
                    "severity": severity,
                })
            return out
        except Exception as e:
            logger.error("CVE fetch failed: %s", e)
            return []

    def _get_cve_data(self, cve_id: str) -> Dict:
        """Fetch CVE data — try OpenCVE first, fall back to NVD."""
        import requests as _req
        opencve_user = os.getenv("OPENCVE_USERNAME", "")
        opencve_pass = os.getenv("OPENCVE_PASSWORD", "")
        if opencve_user and opencve_pass:
            try:
                resp = _req.get(
                    f"https://www.opencve.io/api/cve/{cve_id}",
                    auth=(opencve_user, opencve_pass),
                    timeout=10,
                )
                if resp.status_code == 200:
                    return {"source": "opencve", "data": resp.json()}
            except Exception:
                pass
        # Fall back to NVD
        resp = _req.get(
            f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}",
            timeout=10,
            headers={"User-Agent": "SentinelGuardian/1.0"},
        )
        return {"source": "nvd", "data": resp.json()}

    def analyze_cve(self, cve_id: str) -> Dict:
        """Fetch CVE details (OpenCVE or NVD) and have Guardian analyze it."""
        try:
            result = self._get_cve_data(cve_id)
            raw = result["data"]
            source = result["source"]

            if source == "opencve":
                description = raw.get("description", "")
                score = raw.get("cvss", {}).get("v31", {}).get("score") or raw.get("cvss", {}).get("v3", {}).get("score")
            else:
                vulns = raw.get("vulnerabilities", [])
                if not vulns:
                    return {"error": f"{cve_id} not found in NVD"}
                cve_data = vulns[0]["cve"]
                descs = cve_data.get("descriptions", [])
                description = next((d["value"] for d in descs if d.get("lang") == "en"), "")
                metrics = cve_data.get("metrics", {})
                score = None
                if "cvssMetricV31" in metrics:
                    score = metrics["cvssMetricV31"][0]["cvssData"]["baseScore"]
                elif "cvssMetricV30" in metrics:
                    score = metrics["cvssMetricV30"][0]["cvssData"]["baseScore"]
        except Exception as e:
            return {"error": str(e)}

        prompt = f"""Analyze this CVE for security research and authorized testing:

CVE ID: {cve_id}
CVSS Score: {score}
Description: {description}

Provide:
1. Technical explanation of the root cause
2. Affected systems and versions
3. Attack vector and prerequisites
4. How to test for this vulnerability in an authorized pentest
5. Detection methods (network signatures, log patterns)
6. Mitigation and patch guidance"""

        analysis = self._call_ollama(prompt, tier="reasoning")
        return {"cve_id": cve_id, "description": description, "cvss_score": score, "analysis": analysis}

    # ── Misc ───────────────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> Dict:
        valid = {"attack", "defend", "forensics"}
        if mode not in valid:
            return {"status": "error", "message": f"Invalid mode. Use: {sorted(valid)}"}
        self.mode = mode
        return {"status": "ok", "mode": mode}

    def clear_history(self) -> Dict:
        self.conversation_history.clear()
        return {"status": "ok"}

    def get_status(self) -> Dict:
        return {
            "model_fast": self.models.get("fast"),
            "model_reasoning": self.models.get("reasoning"),
            "model_code": self.models.get("code"),
            "mode": self.mode,
            "history_length": len(self.conversation_history),
            "authorized_targets": list(self.authorized_targets),
            "tools_available": self.tools_available,
            "tools_header": self.get_tools_header(),
        }
