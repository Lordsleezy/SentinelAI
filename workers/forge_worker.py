import json
import subprocess
from pathlib import Path
from typing import Any, Dict


class ForgeWorkerError(RuntimeError):
    pass


def _default_forge_worker_path() -> Path:
    return Path.home() / "Desktop" / "Forge" / "forge" / "src-tauri" / "forge-worker.cjs"


def run_forge_task(
    task_id,
    workspace,
    prompt,
    model="qwen2.5-coder:14b",
    timeout=300,
) -> Dict[str, Any]:
    forge_worker = _default_forge_worker_path()
    if not forge_worker.exists():
        raise ForgeWorkerError(f"Forge worker not found: {forge_worker}")

    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ForgeWorkerError(f"Workspace does not exist or is not a directory: {workspace_path}")

    payload = {
        "task_id": str(task_id),
        "workspace": str(workspace_path),
        "prompt": str(prompt),
        "provider": "ollama",
        "model": model,
        "ollama_url": "http://127.0.0.1:11434",
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
    except subprocess.TimeoutExpired as exc:
        raise ForgeWorkerError(f"Forge worker subprocess timed out after {timeout}s") from exc
    except OSError as exc:
        raise ForgeWorkerError(f"Failed to launch Forge worker: {exc}") from exc

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ForgeWorkerError(
            "Forge worker returned invalid JSON. "
            f"exit_code={completed.returncode}, stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        ) from exc

    if completed.returncode != 0:
        raise ForgeWorkerError(
            "Forge worker failed. "
            f"exit_code={completed.returncode}, result={result}, stderr={completed.stderr!r}"
        )

    return result
