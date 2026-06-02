"""
Earn analysis failure diagnostics — explicit [EARN] logs and vault persistence.

Saves session artifacts to memory/vault/earn_logs/ for post-mortem debugging.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sentinel.earn")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MAX_RUNTIME_DEFAULT = 180
STUCK_TIMEOUT_DEFAULT = 30


def earn_log(socketio: Any, message: str, level: str = "info") -> None:
    """Emit [EARN] prefixed log to UI and Python logger."""
    if not message.startswith("[EARN]"):
        message = f"[EARN] {message}"
    logger.log(
        logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
        message,
    )
    if socketio:
        try:
            socketio.emit("log_event", {
                "type": "earn",
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass


def _model_tag_from_aider_model(model: str) -> str:
    """ollama/qwen2.5-coder:7b -> qwen2.5-coder:7b"""
    m = (model or "").strip()
    if m.startswith("ollama/"):
        return m.split("/", 1)[1]
    return m


def check_ollama_running(host: str = OLLAMA_HOST, timeout: float = 3.0) -> Tuple[bool, str]:
    try:
        import urllib.request
        req = urllib.request.Request(f"{host.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, ""
            return False, f"Ollama HTTP {resp.status}"
    except Exception as e:
        err = str(e).lower()
        if "refused" in err or "10061" in err or "connection" in err:
            return False, "Ollama connection refused"
        if "timed out" in err:
            return False, "Ollama health check timed out"
        return False, str(e)


def check_model_available(model: str, host: str = OLLAMA_HOST) -> Tuple[bool, str]:
    """Return (ok, detail) for whether Ollama has the model tag."""
    tag = _model_tag_from_aider_model(model)
    if not tag:
        return False, "No model tag configured"
    ok, err = check_ollama_running(host)
    if not ok:
        return False, err
    try:
        import urllib.request
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        names = {m.get("name", "") for m in data.get("models", [])}
        # Ollama may report "qwen2.5-coder:7b" or with :latest
        if tag in names or f"{tag}:latest" in names:
            return True, tag
        for n in names:
            if n.split(":")[0] == tag.split(":")[0]:
                return True, n
        return False, f"Model missing: {tag} (ollama pull {tag.split(':')[0]})"
    except Exception as e:
        return False, str(e)


def parse_output_stats(output: str) -> Dict[str, Any]:
    """Extract token hints and response size from aider/ollama stdout."""
    stats: Dict[str, Any] = {
        "tokens_received": None,
        "ollama_response_length": len(output or ""),
        "output_lines": len((output or "").splitlines()),
    }
    if not output:
        return stats

    for line in (output or "").splitlines():
        lower = line.lower()
        for pat in (
            r"(\d+)\s+tokens?",
            r"tokens?\s*[:=]\s*(\d+)",
            r"total\s+tokens?\s*[:=]\s*(\d+)",
            r"completion\s+tokens?\s*[:=]\s*(\d+)",
        ):
            m = re.search(pat, line, re.I)
            if m:
                try:
                    stats["tokens_received"] = int(m.group(1))
                except ValueError:
                    pass
                break
        if "usage" in lower and stats["tokens_received"] is None:
            nums = re.findall(r"\b(\d{2,})\b", line)
            if nums:
                stats["tokens_received"] = int(nums[-1])

    return stats


def classify_earn_failure(
    result: Any,
    *,
    preflight_error: Optional[str] = None,
    max_runtime: int = MAX_RUNTIME_DEFAULT,
    stuck_timeout: int = STUCK_TIMEOUT_DEFAULT,
) -> Tuple[str, str]:
    """
    Return (failure_category, user_message) for [EARN] FAIL logs.

    Categories: model_missing | ollama_down | empty_response | timeout |
                watchdog_kill | loop_kill | exception | aider_missing | unknown
    """
    if preflight_error:
        pe = preflight_error.lower()
        if "connection refused" in pe or "ollama" in pe and "refused" in pe:
            return "ollama_down", "Ollama connection refused"
        if "model missing" in pe:
            return "model_missing", preflight_error
        if "timed out" in pe:
            return "timeout", preflight_error
        return "preflight", preflight_error

    diag = getattr(result, "diagnostics", None) or {}
    err = (getattr(result, "error", None) or "").strip()
    out = (getattr(result, "output", None) or "").strip()
    combined = f"{err}\n{out}".lower()

    kill = diag.get("kill_reason") or ""
    if kill == "timeout" or "timeout after" in err.lower() or err.lower().startswith("killed: timeout"):
        secs = diag.get("runtime_seconds") or max_runtime
        return "timeout", f"Timeout after {int(secs)}s"
    if kill == "stuck" or "watchdog kill" in err.lower() or err.lower().startswith("killed: stuck"):
        st = diag.get("stuck_timeout") or stuck_timeout
        return "watchdog_kill", f"Watchdog kill: no output for {st}s"
    if kill == "loop" or "loop detected" in err.lower():
        return "loop_kill", "Aider loop detected in model output"

    if "aider not found" in combined or "file not found" in combined and "aider" in combined:
        return "aider_missing", "Aider CLI not installed"

    if "connection refused" in combined or "failed to connect" in combined and "ollama" in combined:
        return "ollama_down", "Ollama connection refused"

    if any(x in combined for x in (
        "model not found", "does not exist", "pull model", "can't find", "cannot find",
        "unknown model", "404",
    )) and "model" in combined:
        return "model_missing", "Model missing — run ollama pull for the configured tag"

    exit_code = diag.get("exit_code")
    out_len = diag.get("ollama_response_length") or len(out)
    if not getattr(result, "success", False):
        if out_len < 80 and (exit_code is None or exit_code != 0):
            return "empty_response", "Empty model response"
        if "empty" in err.lower():
            return "empty_response", "Empty model response"

    if err:
        return "exception", err[:500]

    if not getattr(result, "success", False):
        return "unknown", "Analysis failed (see earn_logs for raw output)"

    return "unknown", "Unknown failure"


def persist_earn_log(
    work_dir: str,
    title: str,
    payload: Dict[str, Any],
) -> str:
    """Write JSON + raw output text under memory/vault/earn_logs/. Returns base path."""
    vault = Path(work_dir) / "memory" / "vault" / "earn_logs"
    vault.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]+", "_", title)[:48].strip("_") or "earn"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = vault / f"{safe}_{ts}"
    json_path = base.with_suffix(".json")
    txt_path = Path(str(base) + "_output.txt")

    try:
        json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("earn_logs json write failed: %s", e)

    raw = payload.get("raw_output") or payload.get("output") or ""
    if raw:
        try:
            txt_path.write_text(raw, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("earn_logs output write failed: %s", e)

    return str(json_path)


def log_stage_diagnostics(
    socketio: Any,
    *,
    model: str,
    prompt: str,
    result: Any = None,
    preflight_error: Optional[str] = None,
    max_runtime: int = MAX_RUNTIME_DEFAULT,
    stuck_timeout: int = STUCK_TIMEOUT_DEFAULT,
) -> Dict[str, Any]:
    """Emit standard [EARN] diagnostic lines; return payload for vault."""
    earn_log(socketio, f"Model selected: {model}")
    prompt_bytes = len((prompt or "").encode("utf-8"))
    earn_log(socketio, f"Prompt size: {prompt_bytes} bytes ({len((prompt or '').split())} words)")

    payload: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "prompt_size_bytes": prompt_bytes,
        "preflight_error": preflight_error,
    }

    if preflight_error:
        category, msg = classify_earn_failure(
            None, preflight_error=preflight_error, max_runtime=max_runtime, stuck_timeout=stuck_timeout,
        )
        payload["failure_category"] = category
        payload["failure_message"] = msg
        earn_log(socketio, f"FAIL: {msg}", "error")
        return payload

    if result is None:
        return payload

    diag = getattr(result, "diagnostics", None) or {}
    stats = parse_output_stats(getattr(result, "output", "") or "")

    tokens = stats.get("tokens_received")
    earn_log(socketio, f"Tokens received: {tokens if tokens is not None else 'n/a'}")
    earn_log(socketio, f"Ollama response length: {stats.get('ollama_response_length', 0)} chars")
    earn_log(socketio, f"Exit code: {diag.get('exit_code', 'n/a')}")

    exc_text = getattr(result, "error", None) or diag.get("exception_text")
    if exc_text:
        earn_log(socketio, f"Exception text: {exc_text[:800]}", "error")

    payload.update({
        "success": getattr(result, "success", False),
        "raw_output": getattr(result, "output", "") or "",
        "error": getattr(result, "error", None),
        "diagnostics": diag,
        "tokens_received": tokens,
        "ollama_response_length": stats.get("ollama_response_length"),
        "exit_code": diag.get("exit_code"),
        "kill_reason": diag.get("kill_reason"),
        "runtime_seconds": diag.get("runtime_seconds"),
    })

    if not getattr(result, "success", False):
        category, msg = classify_earn_failure(
            result, max_runtime=max_runtime, stuck_timeout=stuck_timeout,
        )
        payload["failure_category"] = category
        payload["failure_message"] = msg
        earn_log(socketio, f"FAIL: {msg}", "error")

    return payload
