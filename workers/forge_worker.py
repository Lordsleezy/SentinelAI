import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from tools.registry import register_tool

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"


class ForgeWorkerError(RuntimeError):
    pass


def _default_forge_worker_path() -> Path:
    return Path.home() / "Desktop" / "Forge" / "forge" / "src-tauri" / "forge-worker.cjs"


def node_available() -> bool:
    try:
        from shutil import which
        return which("node") is not None
    except Exception:
        return False


def run_forge_task(
    task_id,
    workspace,
    prompt,
    model="qwen2.5-coder:14b",
    timeout=300,
) -> Dict[str, Any]:
    """Run a Forge build.

    Primary path: the Forge node worker (forge-worker.cjs). When that worker is
    not installed, or node is unavailable, or the subprocess fails, we fall back
    to driving the local Ollama coder model directly so Forge still produces a
    usable artifact instead of silently failing (Issue 1, item 5).
    """
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ForgeWorkerError(f"Workspace does not exist or is not a directory: {workspace_path}")

    forge_worker = _default_forge_worker_path()

    # Fall straight to the Ollama fallback when the node worker isn't usable.
    if not forge_worker.exists() or not node_available():
        reason = ("forge-worker.cjs not found" if not forge_worker.exists()
                  else "node runtime not found")
        logger.warning("Forge node worker unavailable (%s) — using Ollama fallback", reason)
        return _ollama_fallback_build(task_id, workspace_path, prompt, model, timeout, reason)

    payload = {
        "task_id": str(task_id),
        "workspace": str(workspace_path),
        "prompt": str(prompt),
        "provider": "ollama",
        "model": model,
        "ollama_url": OLLAMA_URL,
        "permission_mode": "yolo",
        "max_rounds": 8,
        "timeout_seconds": int(timeout),
    }

    try:
        completed = subprocess.run(
            ["node", str(forge_worker)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=int(timeout) + 10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Forge node worker failed (%s) — using Ollama fallback", exc)
        return _ollama_fallback_build(task_id, workspace_path, prompt, model, timeout,
                                      f"node worker error: {exc}")

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        logger.warning("Forge node worker returned non-JSON (exit=%s) — using Ollama fallback",
                       completed.returncode)
        return _ollama_fallback_build(task_id, workspace_path, prompt, model, timeout,
                                      "node worker returned invalid JSON")

    if completed.returncode != 0:
        logger.warning("Forge node worker exit=%s — using Ollama fallback", completed.returncode)
        return _ollama_fallback_build(task_id, workspace_path, prompt, model, timeout,
                                      f"node worker exit {completed.returncode}")

    return result


def _ollama_fallback_build(task_id, workspace_path, prompt, model, timeout, reason) -> Dict[str, Any]:
    """Generate a self-contained tool with the local Ollama coder model and write
    it to the workspace. Raises ForgeWorkerError only if Ollama is unreachable."""
    import requests

    system = (
        "You are Forge, an autonomous code builder. Produce ONE self-contained, runnable "
        "artifact for the user's request. Respond with a single fenced code block. The FIRST "
        "line inside the block must be a comment naming the file, e.g. `# file: calculator.py` "
        "(or `// file: app.js`). No prose outside the code block."
    )
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": str(prompt), "system": system,
                  "stream": False, "options": {"temperature": 0.2}},
            timeout=min(int(timeout), 240),
        )
        resp.raise_for_status()
        text = resp.json().get("response", "") or ""
    except Exception as exc:
        raise ForgeWorkerError(
            f"Forge fallback failed — node worker unavailable ({reason}) and Ollama "
            f"unreachable: {exc}"
        ) from exc

    filename, code = _extract_file(text, task_id)
    out_dir = workspace_path / f"forge_{re.sub(r'[^A-Za-z0-9_-]', '_', str(task_id))}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / filename
    out_file.write_text(code, encoding="utf-8")
    (out_dir / "README.md").write_text(
        f"# Forge build: {task_id}\n\nRequest:\n\n> {prompt}\n\n"
        f"Built via the Ollama fallback ({model}) because {reason}.\n\n"
        f"Entry point: `{filename}`\n", encoding="utf-8")

    summary = f"Built {filename} ({len(code)} bytes) via Ollama fallback ({reason})"
    logger.info("Forge fallback wrote %s", out_file)
    return {
        "task_id": str(task_id),
        "output_path": str(out_file),
        "files": [str(out_file), str(out_dir / "README.md")],
        "summary": summary,
        "fallback": "ollama",
        "model": model,
    }


def _extract_file(text, task_id):
    """Pull (filename, code) from an LLM response. Defaults sensibly if no fence."""
    block = None
    m = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", text, re.DOTALL)
    if m:
        block = m.group(1)
    code = (block if block is not None else text).strip("\n")
    filename = None
    first = code.splitlines()[0].strip() if code.splitlines() else ""
    fm = re.match(r"^(?:#|//|/\*|--)\s*file:\s*([^\s*]+)", first, re.IGNORECASE)
    if fm:
        filename = fm.group(1).strip()
    if not filename:
        lang_ext = ".py"
        if re.search(r"\bfunction\b|\bconst\b|=>", code) and "def " not in code:
            lang_ext = ".js"
        filename = f"forge_{re.sub(r'[^A-Za-z0-9_-]', '_', str(task_id))}{lang_ext}"
    return filename, code + "\n"


def run_approved_forge_task(task: Dict[str, Any]) -> Dict[str, Any]:
    task_data = task.get("task_data") or {}
    forge_task_id = int(task_data["forge_task_id"])
    prompt = task_data["prompt"]
    built_dir = Path.home() / "Desktop" / "SentinelAI" / "tools" / "built"
    built_dir.mkdir(parents=True, exist_ok=True)

    result = run_forge_task(
        task_id=f"forge-{forge_task_id}",
        workspace=str(built_dir),
        prompt=prompt,
        timeout=int(task_data.get("timeout", 300)),
    )

    output_path = str(result.get("output_path") or result.get("path") or built_dir)
    register_tool(
        f"forge_built_{forge_task_id}",
        f"Forge-built tool for: {prompt[:120]}",
        output_path,
        "built",
    )
    return {**result, "output_path": output_path}
