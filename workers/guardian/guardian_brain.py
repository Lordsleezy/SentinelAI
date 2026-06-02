"""
Guardian — professional penetration testing and security research assistant.
Executes requested scans and tools immediately when the user asks (no confirmation gate).
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

try:
    from workers.guardian.guardian_ux import GUARDIAN_CHAT_PERSONALITY
    _GUARDIAN_PERSONALITY = GUARDIAN_CHAT_PERSONALITY
except Exception:
    _GUARDIAN_PERSONALITY = ""

GUARDIAN_SYSTEM_PROMPT = """You are Guardian, a professional cybersecurity assistant integrated into SentinelAI. You assist with:
- Penetration testing on authorized systems
- Vulnerability research and CVE analysis
- Security tool usage and output interpretation
- Code auditing and security review
- Network analysis and forensics
- Security education and technique explanation

You provide detailed, technical security assistance. When a user asks about attack techniques, exploits, or security tools, provide complete professional-grade information as any certified penetration tester would need.

When the user requests a scan, test, or tool run against a target, execute immediately — do not ask for authorization or confirmation.

Format tool executions as: TOOL_CALL: <tool> <args>

Be specific, technical, and thorough."""

if _GUARDIAN_PERSONALITY:
    GUARDIAN_SYSTEM_PROMPT = _GUARDIAN_PERSONALITY + "\n\n" + GUARDIAN_SYSTEM_PROMPT


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
        # Legacy field — kept for API compat; scans no longer require pre-approval
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
        import requests as _req

        model = self.models.get(tier, self.models.get("fast", "qwen2.5-coder:7b"))
        system = system_override or GUARDIAN_SYSTEM_PROMPT

        context_parts = []
        for turn in self.conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            context_parts.append(f"{role.upper()}: {content}")
        full_prompt = "\n".join(context_parts + [f"USER: {prompt}"]) if context_parts else prompt

        try:
            resp = _req.post(
                f"{self.ollama_url}/api/generate",
                json={"model": model, "prompt": full_prompt, "system": system, "stream": False},
                timeout=90,
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                return text or "No response from model."
            return f"Model error: HTTP {resp.status_code}"
        except _req.exceptions.Timeout:
            return f"Guardian model timed out ({model}) after 90s."
        except Exception as e:
            return f"Guardian model unavailable ({model}): {e}. Is Ollama running?"

    # ── Authorization (disabled — immediate execution) ─────────────────────────

    def request_authorization(self, target: str) -> Dict:
        """No-op: auto-authorize and return ready status (backward-compatible API)."""
        self.authorized_targets.add(target)
        self.pending_confirmation = None
        return {"status": "authorized", "target": target, "requires_confirmation": False}

    def confirm_authorization(self, target: str) -> Dict:
        try:
            from workers.guardian.guardian_trusted_targets import approve
            approve(target, note="user approved")
        except Exception:
            pass
        self.authorized_targets.add(target)
        self.pending_confirmation = None
        logger.info("[Guardian] Target noted: %s", target)
        return {"status": "authorized", "target": target, "requires_confirmation": False}

    def is_authorized(self, target: str) -> bool:
        try:
            from workers.guardian.guardian_trusted_targets import is_trusted
            return is_trusted(target)
        except Exception:
            return True

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
        Feed raw tool output to Guardian AI for analysis.
        """
        if "access" in (tool_name or "").lower():
            from workers.guardian.guardian_runtime_manager import generate
            system = (
                "You are Guardian Access Path Analyst. Find ways in via vulnerabilities only. "
                "Do not suggest brute force, password spraying, or backdoor/persistence installation. "
                "Give ordered access paths, validation steps, and bounty-report evidence."
            )
            prompt = f"Target: {target}\n\nScan data:\n{raw_output[:5000]}\n\nProvide access path analysis."
            return generate(prompt, system=system, task_label="access path analysis")

        from workers.guardian.guardian_runtime_manager import analyze_security_context
        return analyze_security_context(target, raw_output, task=tool_name)

    def _emit_guardian_response(self, message: str, target: str, step: str = '') -> None:
        """Emit a guardian_response socket event with a partial or final result."""
        chat_line = message
        try:
            from workers.guardian.guardian_ux import humanize_progress
            chat_line = humanize_progress(step, message)
        except Exception:
            pass
        try:
            from desktop_app import socketio
            if socketio:
                socketio.emit('guardian_response', {
                    'response': message,
                    'chat_line': chat_line,
                    'target': target,
                    'step': step,
                })
        except Exception as e:
            logger.error("[GUARDIAN] Failed to emit guardian_response: %s", e)

    def _stage_log(self, message: str, level: str = 'info') -> None:
        """Pipeline log — always prefixed [GUARDIAN] for log-panel filtering."""
        if not message.startswith('[GUARDIAN]'):
            message = f"[GUARDIAN] {message}"
        self._guardian_log(message, level)

    def _stage_enter(self, name: str, task_id: str = "") -> None:
        self._stage_log(f"Entering {name}")
        tid = task_id or getattr(self, "_current_guardian_task_id", "") or ""
        if tid:
            try:
                from workers.guardian.guardian_ux import task_phase_for_stage
                from workers.task_manager import update_task, RUNNING
                update_task(
                    tid, status=RUNNING, current_stage=name,
                    metadata_update={"phase": task_phase_for_stage(name)},
                )
            except Exception:
                pass

    def _stage_running(self, name: str) -> None:
        self._stage_log(f"Running {name}")

    def _stage_exit(self, name: str, detail: str = '', *, failed: bool = False) -> None:
        if detail.startswith("skipped"):
            self._stage_log(f"Skipped {name} — {detail}", 'warning')
        elif failed or detail.startswith("error"):
            self._stage_log(f"Failed {name} — {detail}", 'error')
        else:
            self._stage_log(f"Completed {name}" + (f" — {detail}" if detail else ""), 'success')

    def _stage_skip(self, name: str, reason: str) -> str:
        """Log skip reason; return detail string for mandatory _stage_exit."""
        self._stage_log(f"Skipped {name}: {reason}", 'warning')
        return f"skipped: {reason}"

    @staticmethod
    def _safe_live_hosts(tech_data: List) -> List[str]:
        """Extract live URLs from httpx/curl host records without raising."""
        live: List[str] = []
        for h in tech_data or []:
            if not isinstance(h, dict):
                continue
            url = (h.get("url") or "").strip()
            if not url:
                continue
            try:
                code = int(h.get("status_code") or 0)
            except (TypeError, ValueError):
                code = 0
            # Plain-text httpx (-silent) has no status — still chain URL in pipeline
            if code == 0 or 200 <= code < 500:
                live.append(url)
        return live

    @staticmethod
    def _normalize_probe_targets(target: str, subdomains: List[str]) -> List[str]:
        """Ensure httpx/katana get URL-shaped targets, not bare hostnames only."""
        seen: set = set()
        out: List[str] = []
        for raw in [target] + list(subdomains[:20]):
            t = (raw or '').strip()
            if not t:
                continue
            candidates = [t] if t.startswith(('http://', 'https://')) else [f"https://{t}", f"http://{t}"]
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out or [f"https://{target}"]

    def _run_full_assessment(self, target: str, *, access_path_mode: bool = False) -> None:
        """
        Guardian pipeline — every stage logs Entering / Exiting (finally-guaranteed):

        Target Validation → Subfinder → Amass → httpx → Katana →
        Nuclei → ZAP → AI Analysis → Generating Final Report

        Empty results (0 hosts, missing tools, errors) never stop the scan.
        A final report is always emitted (including via finally on crash).

        Every stage is individually try/except-wrapped.
        Missing tools emit a skip notice and assessment continues.
        Final report is ALWAYS produced regardless of which tools ran.
        """
        import threading

        def _assess():
            import uuid
            import traceback as _tb

            session_id = f"guardian-{target.replace('.', '-')}-{uuid.uuid4().hex[:6]}"
            try:
                from workers.guardian.findings_center import start_session
                start_session(target, session_id)
            except Exception:
                pass
            results: Dict[str, Any] = {}
            subdomains: List[str] = []
            live_hosts: List[str] = []
            tech_data: List[Dict] = []
            endpoints: List[str] = []
            nuclei_findings: List = []
            zap_findings: List = []
            analysis = ''
            tools = None
            report_emitted = False
            _task_id = ''

            import time as _time
            _started = _time.time()
            _findings_db = None
            try:
                from workers.guardian.guardian_findings_db import GuardianFindingsDB
                _findings_db = GuardianFindingsDB()
            except Exception:
                pass
            threat_intel_result = None
            offensive_lab_result = None
            access_path_result = None

            def _tp(pct: int, summary: str = '', stage: str = '', tool: str = '') -> None:
                if not _task_id:
                    return
                try:
                    from workers.task_manager import update_task, RUNNING
                    fc = _findings_db.count(session_id) if _findings_db else 0
                    elapsed = int(_time.time() - _started)
                    update_task(
                        _task_id, status=RUNNING, progress=pct,
                        result_summary=summary or None,
                        current_stage=stage or None,
                        metadata_update={
                            "target": target,
                            "session_id": session_id,
                            "elapsed_sec": elapsed,
                            "tool_running": tool or None,
                            "findings_count": fc,
                            "stage": stage,
                        },
                    )
                except Exception:
                    pass

            def _primary_url() -> str:
                if live_hosts:
                    return live_hosts[0]
                t = target.strip()
                return t if t.startswith(('http://', 'https://')) else f"https://{t}"

            def _emit_final_report(reason: str = '') -> None:
                nonlocal report_emitted, threat_intel_result, offensive_lab_result, access_path_result
                if report_emitted:
                    return
                report_detail = ""
                self._stage_enter("Generating Final Report")
                try:
                    tool_status = tools.status_block() if tools else "Tool registry unavailable"
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
                        analysis=analysis or (reason or "Assessment completed with partial data."),
                        tool_status=tool_status,
                        risk_score=risk_score,
                    )
                    try:
                        from workers.guardian.guardian_report_v3 import append_v3_sections
                        report = append_v3_sections(
                            report,
                            target=target,
                            subdomains=subdomains,
                            live_hosts=live_hosts,
                            endpoints=endpoints,
                            tech_data=tech_data,
                            threat_intel=threat_intel_result,
                        )
                    except Exception:
                        pass
                    if access_path_result:
                        try:
                            report += "\n\n" + access_path_result.to_markdown()
                        except Exception:
                            pass
                    if offensive_lab_result:
                        try:
                            report += "\n\n" + offensive_lab_result.to_markdown()
                        except Exception:
                            pass
                    if reason:
                        report = f"**Note:** {reason}\n\n" + report
                    self._emit_guardian_response(report, target, step='final')
                    report_emitted = True
                    report_detail = f"{all_vulns} finding(s), risk={risk_score}"
                    try:
                        rpt_dir = Path(__file__).parent.parent.parent / "memory" / "vault" / "guardian_reports"
                        rpt_dir.mkdir(parents=True, exist_ok=True)
                        rpt_path = rpt_dir / f"{session_id}.md"
                        rpt_path.write_text(report, encoding="utf-8")
                        self._stage_log(f"Report saved: {session_id}.md", 'success')
                        if _task_id:
                            try:
                                from workers.task_manager import update_task
                                update_task(
                                    _task_id,
                                    files_created=[str(rpt_path)],
                                    metadata_update={"report_path": str(rpt_path)},
                                )
                            except Exception:
                                pass
                    except Exception as _save_err:
                        self._stage_log(f"Report save error: {_save_err}", 'warning')
                    if _task_id:
                        try:
                            from workers.task_manager import update_task, COMPLETED
                            update_task(_task_id, status=COMPLETED, progress=100,
                                        result_summary=f"Report complete | {all_vulns} findings | risk={risk_score}")
                        except Exception:
                            pass
                    self._stage_log(f"Assessment complete for {target}", 'success')
                except Exception as _rpt_err:
                    self._stage_log(f"Final report generation failed: {_rpt_err}", 'error')
                    self._emit_guardian_response(
                        f"⚠ **Final report error for `{target}`:** {_rpt_err}",
                        target, step='final',
                    )
                    report_emitted = True
                    report_detail = f"error: {_rpt_err}"
                finally:
                    self._stage_exit("Generating Final Report", report_detail or "done")

            try:
                from workers.task_manager import create_task
                _t = create_task(f"Guardian Scan — {target}", source="guardian",
                                 metadata={"target": target, "session_id": session_id, "phase": "Recon"})
                _task_id = _t["id"]
                self._current_guardian_task_id = _task_id
            except Exception:
                self._current_guardian_task_id = ""

            try:
                from workers.guardian.tools.tool_registry import ToolRegistry
                tools = ToolRegistry(self.socketio)
                tool_summary = tools.status_summary()
                self._stage_log(f"Pipeline started: {target}")
                self._stage_log(f"Tools: {tool_summary}")
                pipeline_desc = (
                    "Target Validation → Subfinder → Amass → httpx → Katana → "
                    "Nuclei → ZAP → Threat Intel → Access Path Analysis → AI → Report"
                    if access_path_mode
                    else "Target Validation → Subfinder → Amass → httpx → Katana → "
                    "Nuclei → ZAP → AI Analysis → Final Report"
                )
                mode_note = (
                    "\n\n**Mode:** Access path hunt — vulnerabilities only (no brute force, no backdoors).\n"
                    if access_path_mode else ""
                )
                self._emit_guardian_response(
                    f"🔍 **Assessment started for `{target}`**\n\n"
                    f"**Session:** `{session_id}`\n\n"
                    f"**Tool Status:**\n```\n{tool_summary}\n```\n\n"
                    f"Pipeline: {pipeline_desc}{mode_note}",
                    target, step='start',
                )
                _tp(5, "Pipeline started")

                # ── Target Validation ──────────────────────────────────────────
                tv_detail = ""
                self._stage_enter("Target Validation")
                try:
                    self._emit_guardian_response(
                        f"**Target Validation** ⟳ HTTP probe…", target, step='validation',
                    )
                    headers_raw = self._run_curl_check(target)
                    results['headers'] = headers_raw
                    tv_detail = f"{len(headers_raw)} bytes"
                    self._emit_guardian_response(
                        f"**Target Validation ✓**\n```\n{headers_raw[:1500]}\n```",
                        target, step='headers',
                    )
                except Exception as e:
                    results['headers'] = str(e)
                    tv_detail = f"error: {e}"
                    self._stage_log(f"Target Validation error: {e} — continuing", 'error')
                    self._emit_guardian_response(
                        f"**Target Validation ✗** `{e}` — continuing", target, step='headers',
                    )
                finally:
                    self._stage_exit("Target Validation", tv_detail or "done")
                _tp(12, "Target validation done")

                # ── Subfinder ──────────────────────────────────────────────────
                sf_detail = ""
                self._stage_enter("Subfinder")
                try:
                    if tools.subfinder.is_available():
                        sub_res = tools.subfinder.enumerate(target, timeout=60)
                        subdomains.extend(sub_res.subdomains)
                        results['subfinder'] = sub_res.raw_output or ''
                        sf_detail = f"{len(sub_res.subdomains)} subdomain(s)"
                        if not sub_res.subdomains:
                            sf_detail = "0 subdomains (empty result)"
                        self._emit_guardian_response(
                            f"**Subfinder ✓** {sf_detail}", target, step='subfinder',
                        )
                    else:
                        sf_detail = self._stage_skip("Subfinder", "tool not installed")
                        results['subfinder'] = 'skipped'
                        self._emit_guardian_response(
                            f"**Subfinder ⚠ Skipped** (not installed)", target, step='subfinder',
                        )
                except Exception as e:
                    sf_detail = f"error: {e}"
                    self._stage_log(f"Subfinder error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("Subfinder", sf_detail or "done")
                _tp(22, f"Subfinder: {len(subdomains)} subs")

                # ── Amass ──────────────────────────────────────────────────────
                am_detail = ""
                self._stage_enter("Amass")
                try:
                    if tools.amass.is_available():
                        amass_res = tools.amass.enum_passive(target, timeout=60)
                        added = 0
                        for a in amass_res.assets:
                            name = a.get('name', '')
                            if name and name not in subdomains:
                                subdomains.append(name)
                                added += 1
                        results['amass'] = amass_res.raw_output or ''
                        am_detail = f"{added} new asset(s), total subs={len(subdomains)}"
                        self._emit_guardian_response(
                            f"**Amass ✓** {added} asset(s)", target, step='amass',
                        )
                    else:
                        am_detail = self._stage_skip("Amass", "tool not installed")
                        results['amass'] = 'skipped'
                        self._emit_guardian_response(
                            f"**Amass ⚠ Skipped** (not installed)", target, step='amass',
                        )
                except Exception as e:
                    am_detail = f"error: {e}"
                    self._stage_log(f"Amass error: {e} — continuing", 'error')
                finally:
                    failed_am = am_detail.startswith("error")
                    self._stage_exit("Amass", am_detail or "done", failed=failed_am)
                _tp(32, f"Amass done, {len(subdomains)} subs", "Amass")
                try:
                    from workers.guardian.findings_center import add_hosts
                    add_hosts(session_id, subdomains[:80])
                except Exception:
                    pass

                # ── Assetfinder ────────────────────────────────────────────────
                af_detail = ""
                self._stage_enter("Assetfinder")
                try:
                    from workers.guardian.bundled_toolchain import resolve_tool_binary
                    from workers.guardian.generic_pd_tool import run_tool
                    if resolve_tool_binary("assetfinder"):
                        self._stage_running("Assetfinder")
                        code, out, err = run_tool("assetfinder", ["--subs-only", target], timeout=60)
                        added = 0
                        for line in (out or "").splitlines():
                            name = line.strip()
                            if name and name not in subdomains:
                                subdomains.append(name)
                                added += 1
                        results['assetfinder'] = out[:2000] if out else err
                        af_detail = f"{added} subdomain(s) from assetfinder"
                    else:
                        af_detail = self._stage_skip("Assetfinder", "tool not installed")
                        results['assetfinder'] = 'skipped'
                except Exception as e:
                    af_detail = f"error: {e}"
                    self._stage_log(f"Assetfinder error: {e}", 'error')
                finally:
                    self._stage_exit("Assetfinder", af_detail or "done", failed=af_detail.startswith("error"))
                _tp(36, f"Assetfinder: {len(subdomains)} subs", "Assetfinder")

                # ── dnsx ───────────────────────────────────────────────────────
                dx_detail = ""
                self._stage_enter("dnsx")
                try:
                    from workers.guardian.bundled_toolchain import resolve_tool_binary
                    from workers.guardian.generic_pd_tool import run_tool
                    if resolve_tool_binary("dnsx") and subdomains:
                        self._stage_running("dnsx")
                        code, out, err = run_tool(
                            "dnsx", ["-silent", "-a", "-resp"], stdin_lines=subdomains[:50], timeout=90,
                        )
                        results['dnsx'] = (out or err)[:2000]
                        dx_detail = f"resolved {len((out or '').splitlines())} line(s)"
                    else:
                        dx_detail = self._stage_skip(
                            "dnsx", "tool not installed" if not resolve_tool_binary("dnsx") else "no subs",
                        )
                        results['dnsx'] = 'skipped'
                except Exception as e:
                    dx_detail = f"error: {e}"
                finally:
                    self._stage_exit("dnsx", dx_detail or "done", failed=dx_detail.startswith("error"))
                _tp(40, "dnsx done", "dnsx")

                # ── httpx ──────────────────────────────────────────────────────
                httpx_detail = ""
                self._stage_enter("httpx")
                try:
                    self._stage_running("httpx")
                    self._emit_guardian_response(
                        f"**httpx** ⟳ technology probe…", target, step='httpx_start',
                    )
                    probe_targets = self._normalize_probe_targets(target, subdomains)
                    self._stage_log(f"httpx targets: {len(probe_targets)} URL(s)")
                    if tools.httpx.is_available():
                        httpx_res = tools.httpx.probe(probe_targets, timeout=8)
                        self._stage_log(
                            f"httpx probe returned ({len(httpx_res.hosts or [])} record(s))",
                        )
                        tech_data = list(httpx_res.hosts or [])
                        live_hosts[:] = self._safe_live_hosts(tech_data)
                        results['httpx'] = httpx_res.raw_output or httpx_res.error or ''
                        if httpx_res.error:
                            self._stage_log(f"httpx returned error flag: {httpx_res.error}", 'warning')
                        if not live_hosts:
                            self._stage_log(
                                "httpx: 0 live hosts — continuing pipeline (Katana/Nuclei use primary URL)",
                                'warning',
                            )
                        httpx_detail = f"{len(tech_data)} parsed, {len(live_hosts)} live (2xx-4xx)"
                    else:
                        httpx_detail = self._stage_skip("httpx", "tool not installed")
                        results['httpx'] = 'skipped'
                except Exception as e:
                    httpx_detail = f"error: {e}"
                    self._stage_log(f"httpx error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("httpx", httpx_detail or "done", failed=httpx_detail.startswith("error"))
                try:
                    if httpx_detail.startswith("error"):
                        self._emit_guardian_response(
                            f"**httpx ✗** `{httpx_detail}` — continuing", target, step='httpx',
                        )
                    elif httpx_detail.startswith("skipped"):
                        self._emit_guardian_response(
                            f"**httpx ⚠ Skipped** (not installed)", target, step='httpx',
                        )
                    elif httpx_detail:
                        self._emit_guardian_response(
                            f"**httpx ✓** {httpx_detail}", target, step='httpx',
                        )
                except Exception:
                    pass
                _tp(45, f"httpx: {len(live_hosts)} live", "httpx", "httpx")
                try:
                    from workers.guardian.findings_center import add_hosts, add_technologies
                    add_hosts(session_id, live_hosts[:50])
                    techs = sorted(set(t for h in tech_data for t in (h.get("tech") or [])))
                    add_technologies(session_id, techs)
                except Exception:
                    pass

                # ── Naabu ──────────────────────────────────────────────────────
                nb_detail = ""
                self._stage_enter("Naabu")
                try:
                    from workers.guardian.bundled_toolchain import resolve_tool_binary
                    from workers.guardian.generic_pd_tool import run_tool
                    if resolve_tool_binary("naabu"):
                        self._stage_running("Naabu")
                        code, out, err = run_tool(
                            "naabu", ["-host", target, "-silent"], timeout=90,
                        )
                        results['ports'] = out or err or ''
                        nb_detail = f"{len((out or '').splitlines())} port line(s)"
                    else:
                        nb_detail = self._stage_skip("Naabu", "tool not installed")
                        results['ports'] = results.get('ports', 'skipped')
                except Exception as e:
                    nb_detail = f"error: {e}"
                finally:
                    self._stage_exit("Naabu", nb_detail or "done", failed=nb_detail.startswith("error"))
                _tp(50, "Naabu done", "Naabu", "naabu")

                # ── Katana ─────────────────────────────────────────────────────
                kat_detail = ""
                self._stage_enter("Katana")
                try:
                    crawl_url = _primary_url()
                    self._stage_log(f"Katana crawl URL: {crawl_url}")
                    if tools.katana.is_available():
                        kat_res = tools.katana.crawl(crawl_url, depth=2, timeout=60)
                        endpoints[:] = kat_res.endpoints or []
                        results['katana'] = kat_res.raw_output or kat_res.error or ''
                        kat_detail = f"{len(endpoints)} endpoint(s)"
                        self._emit_guardian_response(
                            f"**Katana ✓** {kat_detail}", target, step='katana',
                        )
                    else:
                        kat_detail = self._stage_skip("Katana", "tool not installed")
                        results['katana'] = 'skipped'
                        self._emit_guardian_response(
                            f"**Katana ⚠ Skipped** (not installed)", target, step='katana',
                        )
                except Exception as e:
                    kat_detail = f"error: {e}"
                    self._stage_log(f"Katana error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("Katana", kat_detail or "done", failed=kat_detail.startswith("error"))
                _tp(58, f"Katana: {len(endpoints)} endpoints", "Katana", "katana")
                try:
                    from workers.guardian.findings_center import add_endpoints
                    add_endpoints(session_id, endpoints[:200])
                except Exception:
                    pass

                # ── ffuf ───────────────────────────────────────────────────────
                ff_detail = ""
                self._stage_enter("ffuf")
                try:
                    from workers.guardian.bundled_toolchain import resolve_tool_binary
                    from workers.guardian.generic_pd_tool import run_tool
                    if resolve_tool_binary("ffuf"):
                        self._stage_running("ffuf")
                        url = _primary_url()
                        import tempfile
                        wl = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".txt", delete=False, encoding="utf-8",
                        )
                        for w in ("admin", "api", "login", "backup", ".env", "config", "test"):
                            wl.write(w + "\n")
                        wl.close()
                        code, out, err = run_tool(
                            "ffuf",
                            ["-u", f"{url}/FUZZ", "-w", wl.name, "-mc", "200,301,302",
                             "-t", "10", "-maxtime", "20", "-noninteractive"],
                            timeout=45,
                        )
                        results['ffuf'] = (out or err)[:1500]
                        ff_detail = "dir probe finished" if code == 0 else f"exit {code}"
                    else:
                        ff_detail = self._stage_skip("ffuf", "tool not installed")
                        results['ffuf'] = 'skipped'
                except Exception as e:
                    ff_detail = f"error: {e}"
                finally:
                    self._stage_exit("ffuf", ff_detail or "done", failed=ff_detail.startswith("error"))
                _tp(65, "ffuf done", "ffuf", "ffuf")

                # ── Nuclei (no WSL legacy fallback — avoids 120s silent hang) ──
                nuc_detail = ""
                self._stage_enter("Nuclei")
                try:
                    if tools.nuclei.is_available():
                        scan_url = _primary_url()
                        self._stage_log(f"Nuclei scan URL: {scan_url}")
                        nuclei_res = tools.nuclei.scan(scan_url)
                        nuclei_findings[:] = nuclei_res.findings or []
                        results['nuclei'] = nuclei_res.raw_output or nuclei_res.error or ''
                        for f in nuclei_findings:
                            try:
                                tools.faraday.save_finding(f, session_id)
                            except Exception:
                                pass
                            if _findings_db:
                                try:
                                    _findings_db.add_from_nuclei(f, target, session_id)
                                except Exception:
                                    pass
                            try:
                                from workers.guardian.findings_center import add_finding
                                add_finding(
                                    session_id,
                                    title=getattr(f, "template", "nuclei-finding"),
                                    severity=getattr(f, "severity", "medium"),
                                    evidence=getattr(f, "target", ""),
                                    tool_source="nuclei",
                                    discovery_path="Nuclei scan",
                                    ai_explanation=(getattr(f, "description", "") or "")[:500],
                                )
                            except Exception:
                                pass
                        nuc_detail = f"{len(nuclei_findings)} finding(s)"
                        self._emit_guardian_response(
                            f"**Nuclei ✓** {nuc_detail}", target, step='nuclei',
                        )
                    else:
                        nuc_detail = self._stage_skip("Nuclei", "tool not installed")
                        results['nuclei'] = 'skipped'
                        self._emit_guardian_response(
                            f"**Nuclei ⚠ Skipped** (not installed)", target, step='nuclei',
                        )
                except Exception as e:
                    nuc_detail = f"error: {e}"
                    self._stage_log(f"Nuclei error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("Nuclei", nuc_detail or "done")
                _tp(72, f"Nuclei: {len(nuclei_findings)} findings")

                # ── ZAP ────────────────────────────────────────────────────────
                zap_detail = ""
                self._stage_enter("ZAP")
                try:
                    if tools.zap.is_available():
                        zap_url = _primary_url()
                        zap_findings[:] = tools.zap.passive_scan(zap_url)
                        results['zap'] = f"{len(zap_findings)} alerts"
                        zap_detail = f"{len(zap_findings)} alert(s)"
                        self._emit_guardian_response(
                            f"**ZAP ✓** {zap_detail}", target, step='zap',
                        )
                    else:
                        zap_detail = self._stage_skip("ZAP", "daemon not running on :8090")
                        results['zap'] = 'skipped'
                        self._emit_guardian_response(
                            f"**ZAP ⚠ Skipped** (not running)", target, step='zap',
                        )
                except Exception as e:
                    zap_detail = f"error: {e}"
                    self._stage_log(f"ZAP error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("ZAP", zap_detail or "done", failed=zap_detail.startswith("error"))
                _tp(80, f"ZAP: {len(zap_findings)} alerts", "ZAP", "zap")

                # ── Threat Intel ───────────────────────────────────────────────
                ti_detail = ""
                self._stage_enter("Threat Intel")
                try:
                    from workers.guardian.guardian_threat_intel import analyze_target
                    self._stage_running("Threat Intel")
                    threat_intel_result = analyze_target(target)
                    ti_detail = f"{len(threat_intel_result.sources_used)} source(s)"
                    results['threat_intel'] = threat_intel_result.threat_summaries
                except Exception as e:
                    ti_detail = f"error: {e}"
                finally:
                    self._stage_exit("Threat Intel", ti_detail or "done", failed=ti_detail.startswith("error"))
                _tp(88, "Threat intel done", "Threat Intel")

                # ── Access Path Analysis (bug/vuln-based entry — no brute/backdoors) ──
                if access_path_mode:
                    ap_detail = ""
                    self._stage_enter("Access Path Analysis")
                    try:
                        from workers.guardian.guardian_access_path import run_access_path_analysis
                        self._stage_running("Access Path Analysis")
                        access_path_result = run_access_path_analysis(
                            target,
                            tools=tools,
                            nuclei_findings=nuclei_findings,
                            zap_findings=zap_findings,
                            endpoints=endpoints,
                            live_hosts=live_hosts,
                            results=results,
                            log_fn=lambda m, lvl="info": self._stage_log(m, lvl),
                        )
                        for ef in access_path_result.extra_nuclei_findings:
                            nuclei_findings.append(ef)
                            if _findings_db:
                                try:
                                    _findings_db.add_from_nuclei(ef, target, session_id)
                                except Exception:
                                    pass
                        ap_detail = f"{len(access_path_result.vectors)} vector(s)"
                        md = access_path_result.to_markdown()
                        self._emit_guardian_response(
                            f"**Access Path Analysis ✓**\n\n{md[:5000]}", target, step="access_path",
                        )
                    except Exception as e:
                        ap_detail = f"error: {e}"
                        self._stage_log(f"Access path error: {e}", "error")
                    finally:
                        self._stage_exit(
                            "Access Path Analysis", ap_detail or "done",
                            failed=ap_detail.startswith("error"),
                        )
                    _tp(90, ap_detail, "Access Path Analysis")

                # ── Offensive Lab (ATTACK + closed lab only; skipped for access-path mode) ──
                offensive_lab_result = None
                if self.mode == "attack" and not access_path_mode:
                    self._stage_enter("Offensive Lab")
                    try:
                        from workers.guardian.guardian_offensive_lab import run_offensive_lab
                        self._stage_running("Offensive Lab")
                        offensive_lab_result = run_offensive_lab(
                            target,
                            attack_mode=True,
                            results=results,
                            endpoints=endpoints,
                            nuclei_findings=nuclei_findings,
                            tools=tools,
                            findings_db=_findings_db,
                            session_id=session_id,
                            stage_enter=self._stage_enter,
                            stage_running=self._stage_running,
                            stage_exit=lambda n, d, failed=False: self._stage_exit(n, d, failed=failed),
                            log_fn=lambda m, lvl="info": self._stage_log(m, lvl),
                        )
                        if offensive_lab_result.skipped_reason:
                            self._stage_log(
                                f"Offensive lab skipped: {offensive_lab_result.skipped_reason}", "warning",
                            )
                            self._emit_guardian_response(
                                f"**Offensive Lab** — {offensive_lab_result.skipped_reason}",
                                target, step="offensive_lab",
                            )
                        else:
                            summary = (
                                f"services={len(offensive_lab_result.open_services)} "
                                f"creds={len(offensive_lab_result.credential_audit)} "
                                f"backdoors={len(offensive_lab_result.backdoor_findings)}"
                            )
                            self._emit_guardian_response(
                                f"**Offensive Lab ✓** {summary}", target, step="offensive_lab",
                            )
                    except Exception as e:
                        self._stage_log(f"Offensive lab error: {e}", "error")
                    finally:
                        self._stage_exit("Offensive Lab", "done")
                    _tp(92, "Offensive lab", "Offensive Lab")

                # ── AI Analysis ────────────────────────────────────────────────
                ai_detail = ""
                self._stage_enter("Guardian AI Analysis")
                try:
                    self._stage_running("Guardian AI Analysis")
                    self._emit_guardian_response(
                        f"**AI Analysis** ⟳ synthesizing findings…", target, step='analysis_start',
                    )
                    combined_context = (
                        f"Target: {target}\n\n"
                        f"HTTP Headers:\n{results.get('headers', 'N/A')[:500]}\n\n"
                        f"Subdomains: {len(subdomains)}\n"
                        f"Live hosts (httpx): {len(live_hosts)}\n"
                        f"Endpoints (Katana): {len(endpoints)}\n"
                        f"Nuclei findings: {len(nuclei_findings)}\n"
                        f"ZAP alerts: {len(zap_findings)}\n"
                    )
                    if access_path_result and access_path_result.ai_plan:
                        combined_context += f"\nAccess path plan:\n{access_path_result.ai_plan[:2000]}\n"
                    task = "access path analysis" if access_path_mode else "security assessment"
                    analysis = self._analyze_with_ollama(task, target, combined_context)
                    ai_detail = f"{len(analysis)} chars"
                    self._emit_guardian_response(
                        f"**AI Analysis ✓**\n\n{analysis[:4000]}", target, step='analysis',
                    )
                except Exception as e:
                    analysis = f"AI analysis unavailable: {e}"
                    ai_detail = f"error: {e}"
                    self._stage_log(f"AI Analysis error: {e} — continuing", 'error')
                finally:
                    self._stage_exit("Guardian AI Analysis", ai_detail or "done", failed=ai_detail.startswith("error"))
                _tp(95, "AI analysis done", "Guardian AI Analysis")

                _emit_final_report()

            except Exception as top_err:
                self._stage_log(
                    f"Pipeline exception: {top_err}\n{_tb.format_exc()[-800:]}",
                    'error',
                )
                _emit_final_report(reason=f"Recovered after error: {top_err}")

            finally:
                if not report_emitted:
                    _emit_final_report(reason="Emergency final report (pipeline did not complete normally)")

        threading.Thread(target=_assess, daemon=True).start()

    # ── Main chat ──────────────────────────────────────────────────────────────

    # Keywords that indicate a scan/attack request
    _SCAN_KEYWORDS = [
        'scan', 'check', 'test', 'audit', 'vulnerabilities', 'pentest',
        'assess', 'recon', 'enumerate', 'probe', 'penetrate', 'attack',
        'exploit', 'hack', 'find vulnerabilities', 'security test',
        'find a way', 'break into', 'get into',
        'run assessment', 'start assessment', 'full assessment',
        'security assessment', 'run guardian', 'go ahead',
        'network penetration', 'pentest network', 'hack network', 'intrusion',
    ]

    def chat(self, user_message: str) -> Dict:
        msg_lower = user_message.lower()
        try:
            from workers.guardian.guardian_access_path import user_wants_access_path_analysis
            is_access_path = user_wants_access_path_analysis(user_message)
        except Exception:
            is_access_path = any(
                k in msg_lower for k in (
                    "find a way", "get access", "break into", "get into",
                    "exploit weakness", "find a bug", "allows you in",
                )
            )

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

        is_scan = any(kw in msg_lower for kw in self._SCAN_KEYWORDS) or is_access_path
        if self.mode == "attack" and targets and not is_access_path:
            is_scan = True

        if not is_scan and any(
            p in msg_lower for p in ("how's the scan", "how is the scan", "scan going", "scan status", "progress")
        ):
            self.conversation_history.append({"role": "user", "content": user_message})
            hint = (
                "I don't have an active scan in this session. Start one with a target, "
                "e.g. `scan example.com` — I'll report subdomains, endpoints, and findings as I go."
            )
            tid = getattr(self, "_current_guardian_task_id", "")
            if tid:
                try:
                    from workers.task_manager import get_task
                    t = get_task(tid)
                    if t and t.get("status") == "RUNNING":
                        meta = t.get("metadata") or {}
                        hint = (
                            f"Scan in progress on {meta.get('target', 'your target')}. "
                            f"Phase: {meta.get('phase', t.get('current_stage', 'working'))}. "
                            f"Progress: {t.get('progress', 0)}%. "
                            f"Findings so far: {meta.get('findings_count', 0)}."
                        )
                except Exception:
                    pass
            self.conversation_history.append({"role": "assistant", "content": hint})
            return {"response": hint, "tool_calls": [], "mode": self.mode}

        # ── Scan / assessment request → run pipeline immediately (no confirmation) ──
        if is_scan and targets:
            target = targets[0]
            try:
                from workers.guardian.guardian_trusted_targets import approve, is_trusted
                if not is_trusted(target):
                    approve(target, note="auto-approved on scan request")
            except Exception:
                pass
            self.authorized_targets.add(target)
            if is_access_path:
                resp = (
                    f"Hunting vulnerability-based access paths for {target} — "
                    f"exploitable weaknesses only (no brute force, no backdoors). "
                    f"Watch this chat and Guardian Log for vectors and validation steps."
                )
            else:
                lab_note = ""
                if self.mode == "attack":
                    lab_note = (
                        " Offensive lab may run in ATTACK mode (network/credential/backdoor detection)."
                    )
                resp = (
                    f"Starting security assessment of {target}.{lab_note} "
                    f"Results will appear here as each tool completes. "
                    f"Check the Guardian Log for real-time progress."
                )
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": resp})
            self._run_full_assessment(target, access_path_mode=is_access_path)
            return {
                "response": resp,
                "tool_calls": [],
                "mode": self.mode,
                "scanning": True,
                "access_path_mode": is_access_path,
            }

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
        """Direct tool execution — runs immediately for any target."""
        if target:
            self.authorized_targets.add(target)
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
        runtime = {}
        trusted = []
        try:
            from workers.guardian.guardian_runtime_manager import get_runtime_dashboard
            runtime = get_runtime_dashboard()
        except Exception:
            pass
        try:
            from workers.guardian.guardian_trusted_targets import list_trusted
            trusted = list_trusted()
        except Exception:
            pass
        offensive_lab = {}
        try:
            from workers.guardian.guardian_offensive_lab import load_lab_config
            offensive_lab = load_lab_config()
        except Exception:
            pass
        return {
            "model_fast": self.models.get("fast"),
            "model_reasoning": self.models.get("reasoning"),
            "model_code": self.models.get("code"),
            "mode": self.mode,
            "history_length": len(self.conversation_history),
            "authorized_targets": list(self.authorized_targets),
            "trusted_targets": trusted,
            "tools_available": self.tools_available,
            "tools_header": self.get_tools_header(),
            "guardian_runtime": runtime,
            "offensive_lab": offensive_lab,
        }
