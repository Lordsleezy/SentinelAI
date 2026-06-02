"""
workers/guardian/tools/httpx_compat.py

Compatibility layer for ProjectDiscovery httpx vs Python's httpx CLI (pip).
Never assumes flags — probes -help output and builds a supported command line.

Public API:
    run_httpx(targets, timeout, log) -> HttpxRunResult
    find_projectdiscovery_httpx() -> Optional[HttpxBinaryInfo]
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("sentinel.guardian.httpx")

# Prefer explicit PD installs before PATH (PATH often has Python httpx)
_CANDIDATE_PATHS = [
    r"C:\Tools\httpx.exe",
    r"C:\Program Files\httpx\httpx.exe",
    r"C:\Users\pgg12\go\bin\httpx.exe",
]

# Flags we want, mapped to probe patterns in help text
_FLAG_CANDIDATES: List[Tuple[str, Optional[str]]] = [
    ("-json",            r"-json\b"),
    ("-silent",          r"-silent\b"),
    ("-nc",              r"-nc\b"),
    ("-no-color",        r"-no-color\b"),
    ("-tech-detect",     r"-tech-detect\b"),
    ("-status-code",     r"-status-code\b"),
    ("-sc",              r"(?:^|\s)-sc\b"),
    ("-title",           r"-title\b"),
    ("-follow-redirects", r"-follow-redirects\b"),
    ("-fr",              r"(?:^|\s)-fr\b"),
    ("-timeout",         r"-timeout\b"),
    ("-u",               r"(?:^|\s)-u\b"),
    ("-l",               r"(?:^|\s)-l\b"),
]

LogFn = Callable[[str, str], None]


@dataclass
class HttpxBinaryInfo:
    path: str
    flavor: str  # projectdiscovery | python_client | unknown
    version: str = ""
    supported_flags: Set[str] = field(default_factory=set)
    help_excerpt: str = ""


@dataclass
class HttpxRunResult:
    success: bool
    hosts: List[Dict] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    command: List[str] = field(default_factory=list)
    binary: Optional[HttpxBinaryInfo] = None
    error: Optional[str] = None
    used_fallback: bool = False


def _default_log(msg: str, level: str = "info") -> None:
    logger.log(
        logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
        msg,
    )


def _run_capture(cmd: List[str], timeout: int = 15, stdin: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _classify_help(path: str, stdout: str, stderr: str) -> HttpxBinaryInfo:
    combined = f"{stdout}\n{stderr}"
    lower = combined.lower()

    if "projectdiscovery" in lower or "project discovery" in lower:
        flavor = "projectdiscovery"
    elif re.search(r"httpx[/\\]_main\.py", lower) or "option '-h' requires" in lower:
        flavor = "python_client"
    elif re.search(r"usage:.*httpx", lower) and ("url" in lower or "method" in lower) and "file" in lower:
        flavor = "python_client"
    elif re.search(r"usage:.*httpx\.exe.*options.*url", lower):
        flavor = "python_client"
    elif "-json" in combined and ("-status-code" in combined or "-sc" in combined):
        flavor = "projectdiscovery"
    elif "-probe" in combined or "-tech-detect" in combined:
        flavor = "projectdiscovery"
    else:
        flavor = "unknown"

    flags: Set[str] = set()
    for flag, pattern in _FLAG_CANDIDATES:
        if re.search(pattern, combined, re.I):
            flags.add(flag)

    version = ""
    for line in combined.splitlines():
        if "version" in line.lower() or re.search(r"v\d+\.\d+", line):
            version = line.strip()[:120]
            break
    if not version:
        m = re.search(r"(?:Current Version|Version):\s*(\S+)", combined, re.I)
        if m:
            version = m.group(1)

    return HttpxBinaryInfo(
        path=path,
        flavor=flavor,
        version=version,
        supported_flags=flags,
        help_excerpt=combined[:1500],
    )


def probe_binary(path: str) -> HttpxBinaryInfo:
    """Fingerprint a single httpx executable."""
    # ProjectDiscovery: -version
    code, out, err = _run_capture([path, "-version"], timeout=12)
    if code == 0 or "projectdiscovery" in (out + err).lower():
        info = _classify_help(path, out, err)
        if info.flavor == "projectdiscovery":
            return info

    # PD help (short -h)
    code, out, err = _run_capture([path, "-h"], timeout=12)
    info = _classify_help(path, out, err)
    if info.flavor == "projectdiscovery":
        return info

    # Python httpx uses --help
    code, out, err = _run_capture([path, "--help"], timeout=12)
    return _classify_help(path, out, err)


def _discover_candidates() -> List[str]:
    seen: Set[str] = set()
    paths: List[str] = []
    for p in _CANDIDATE_PATHS:
        if Path(p).is_file() and p not in seen:
            seen.add(p)
            paths.append(p)
    which = shutil.which("httpx") or shutil.which("httpx.exe")
    if which and which not in seen:
        seen.add(which)
        paths.append(which)
    return paths


def find_projectdiscovery_httpx(log: Optional[LogFn] = None) -> Optional[HttpxBinaryInfo]:
    """Return ProjectDiscovery httpx binary info, or None if only Python httpx / missing."""
    _log = log or _default_log
    for path in _discover_candidates():
        info = probe_binary(path)
        _log(f"[GUARDIAN] httpx probe {path}: flavor={info.flavor} version={info.version or 'unknown'}", "info")
        if info.flavor == "projectdiscovery":
            _log(f"[GUARDIAN] httpx version: {info.version or '(see help)'}", "info")
            return info
        if info.flavor == "python_client":
            _log(
                f"[GUARDIAN] httpx skipped {path}: Python HTTP client (pip), not ProjectDiscovery scanner",
                "warning",
            )
        elif info.flavor == "unknown":
            _log(
                f"[GUARDIAN] httpx skipped {path}: unrecognized httpx binary (not ProjectDiscovery)",
                "warning",
            )
    return None


def _build_pd_command(info: HttpxBinaryInfo, timeout: int) -> List[str]:
    """Assemble argv using only flags confirmed in help text."""
    f = info.supported_flags
    cmd = [info.path]

    def _add(flag: str, value: Optional[str] = None) -> None:
        if flag in f:
            cmd.append(flag)
            if value is not None:
                cmd.append(str(value))

    # Prefer short flags when both exist
    if "-json" in f:
        _add("-json")
    if "-silent" in f:
        _add("-silent")
    elif "-nc" in f:
        _add("-nc")
    if "-no-color" in f:
        _add("-no-color")
    if "-tech-detect" in f:
        _add("-tech-detect")
    if "-status-code" in f:
        _add("-status-code")
    elif "-sc" in f:
        _add("-sc")
    if "-title" in f:
        _add("-title")
    if "-follow-redirects" in f:
        _add("-follow-redirects")
    elif "-fr" in f:
        _add("-fr")
    if "-timeout" in f:
        _add("-timeout", str(timeout))

    return cmd


def _parse_json_lines(stdout: str) -> List[Dict]:
    hosts: List[Dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            hosts.append({
                "url":          d.get("url", ""),
                "status_code":  d.get("status-code", d.get("status_code", 0)),
                "title":        d.get("title", ""),
                "tech":         d.get("tech", []),
                "tls":          d.get("tls", {}),
                "webserver":    d.get("webserver", ""),
                "content_type": d.get("content-type", d.get("content_type", "")),
            })
        except json.JSONDecodeError:
            continue
    return hosts


def _curl_fallback(targets: List[str], timeout: int, log: LogFn) -> HttpxRunResult:
    """Minimal live check when PD httpx is not installed."""
    log("[GUARDIAN] httpx using curl fallback (ProjectDiscovery httpx not found)", "warning")
    hosts: List[Dict] = []
    lines: List[str] = []
    for t in targets[:30]:
        url = t if t.startswith(("http://", "https://")) else f"https://{t}"
        code, out, err = _run_capture(
            ["curl", "-sI", "--max-time", str(timeout), "-L", url],
            timeout=timeout + 5,
        )
        lines.append(out[:500])
        status = 0
        for ln in out.splitlines():
            if ln.upper().startswith("HTTP/"):
                parts = ln.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status = int(parts[1])
        if status:
            hosts.append({"url": url, "status_code": status, "title": "", "tech": [], "tls": {},
                          "webserver": "", "content_type": ""})
    return HttpxRunResult(
        success=True,
        hosts=hosts,
        stdout="\n".join(lines),
        stderr="",
        command=["curl", "fallback"],
        used_fallback=True,
    )


def run_httpx(
    targets: List[str],
    timeout: int = 10,
    log: Optional[LogFn] = None,
) -> HttpxRunResult:
    """
    Run ProjectDiscovery httpx with version-safe flags, or curl fallback.

    Logs:
      [GUARDIAN] httpx version: ...
      [GUARDIAN] httpx command: ...
      [GUARDIAN] httpx stdout: ... (truncated)
      [GUARDIAN] httpx stderr: ... (truncated)
    """
    _log = log or _default_log
    targets = [t.strip() for t in targets if t and t.strip()]
    if not targets:
        return HttpxRunResult(success=False, error="no targets")

    info = find_projectdiscovery_httpx(_log)
    if not info:
        return _curl_fallback(targets, timeout, _log)

    base_cmd = _build_pd_command(info, timeout)
    if "-json" not in info.supported_flags:
        _log("[GUARDIAN] httpx: -json not in help — output may not parse", "warning")

    # Target delivery: prefer -u per URL; else stdin list
    cmd = list(base_cmd)
    stdin_body: Optional[str] = None
    if "-u" in info.supported_flags:
        for t in targets[:50]:
            url = t if t.startswith(("http://", "https://")) else f"https://{t}"
            cmd.extend(["-u", url])
    else:
        stdin_body = "\n".join(
            t if t.startswith(("http://", "https://")) else f"https://{t}"
            for t in targets
        )

    _log(f"[GUARDIAN] httpx command: {' '.join(cmd)}", "info")
    if stdin_body:
        _log(f"[GUARDIAN] httpx stdin: {len(targets)} target(s)", "info")

    per_target = max(timeout, 5) * len(targets) + 20
    run_timeout = min(max(per_target, 30), 120)

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_body else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, stderr = proc.communicate(input=stdin_body, timeout=run_timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _log(f"[GUARDIAN] httpx stderr: timed out after {run_timeout}s", "error")
        return HttpxRunResult(
            success=False, error=f"timed out ({run_timeout}s)",
            command=cmd, binary=info, stderr="timeout",
        )
    except Exception as e:
        _log(f"[GUARDIAN] httpx stderr: {e}", "error")
        return HttpxRunResult(success=False, error=str(e), command=cmd, binary=info)

    _log(f"[GUARDIAN] httpx stdout: {(stdout or '')[:800]}", "info")
    if stderr and stderr.strip():
        _log(f"[GUARDIAN] httpx stderr: {stderr.strip()[:800]}", "warning")

    # Invalid usage (wrong binary or bad flags) — do not treat as success
    err_lower = (stderr or "").lower()
    if "no such option" in err_lower or "unknown flag" in err_lower or "usage:" in err_lower:
        _log("[GUARDIAN] httpx rejected flags — trying curl fallback", "warning")
        return _curl_fallback(targets, timeout, _log)

    hosts = _parse_json_lines(stdout or "")
    if not hosts and stdout:
        # Plain-text lines: URL [status]
        for line in (stdout or "").splitlines():
            m = re.search(r"(https?://\S+).*?\[(\d+)\]", line)
            if m:
                hosts.append({"url": m.group(1), "status_code": int(m.group(2)),
                              "title": "", "tech": [], "tls": {}, "webserver": "", "content_type": ""})

    return HttpxRunResult(
        success=True,
        hosts=hosts,
        stdout=stdout or "",
        stderr=stderr or "",
        command=cmd,
        binary=info,
    )
