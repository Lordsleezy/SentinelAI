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
            logger.error("[Guardian] Failed to emit guardian_response: %s", e)

    def _run_full_assessment(self, target: str) -> None:
        """
        Run a full security assessment in a background thread.
        Emits incremental guardian_response events after each tool so the
        user sees results as they arrive instead of waiting for Ollama.
        """
        import threading

        def _assess():
            results: Dict[str, str] = {}

            self._guardian_log(f"Starting security assessment: {target}", 'info')

            # 1. HTTP headers (always available — emit immediately)
            self._guardian_log("Step 1/4: HTTP header check...", 'info')
            results['headers'] = self._run_curl_check(target)
            self._emit_guardian_response(
                f"**Step 1 — HTTP Headers for {target}:**\n```\n{results['headers'][:1500]}\n```",
                target, step='headers'
            )

            # 2. Port scan
            self._guardian_log("Step 2/4: Port scan (nmap)...", 'info')
            results['ports'] = self._run_nmap(target)
            self._emit_guardian_response(
                f"**Step 2 — Port Scan:**\n```\n{results['ports'][:1500]}\n```",
                target, step='ports'
            )

            # 3. Vulnerability scan
            self._guardian_log("Step 3/4: Vulnerability scan (nuclei)...", 'info')
            results['vulns'] = self._run_nuclei(target)
            self._emit_guardian_response(
                f"**Step 3 — Vulnerability Scan:**\n```\n{results['vulns'][:1500]}\n```",
                target, step='vulns'
            )

            # 4. Final AI analysis
            self._guardian_log("Step 4/4: AI analysis of findings...", 'info')
            combined = (
                f"HTTP Headers:\n{results['headers']}\n\n"
                f"Port Scan:\n{results['ports']}\n\n"
                f"Vulnerability Scan:\n{results['vulns']}"
            )
            analysis = self._analyze_with_ollama('security assessment', target, combined)

            self._guardian_log("Assessment complete", 'success')
            self._emit_guardian_response(
                f"**Assessment complete for {target}:**\n\n{analysis}",
                target, step='final'
            )

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
        logger.info("[Guardian/%s] %s", level, message)

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
