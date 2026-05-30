from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


EICAR = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
AWS_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GITHUB_RE = re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")
ANTHROPIC_RE = re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")


def _result(status: str, task_id: str, data=None, error: Optional[str] = None) -> Dict:
    return {"status": status, "task_id": task_id, "data": data, "error": error}


def scan_file(path) -> Dict:
    file_path = Path(path)
    threats = []
    details = []
    data = file_path.read_bytes()
    text = data.decode("utf-8", errors="ignore")

    if EICAR in text:
        threats.append("EICAR-Test-File")
        details.append("Standard antivirus test signature detected")
    if re.search(r"powershell\s+-enc|invoke-expression|curl\s+http|wget\s+http", text, re.I):
        threats.append("Suspicious-Script-Pattern")
        details.append("Suspicious command execution or download pattern")
    if data[:2] == b"MZ" and file_path.suffix.lower() not in {".exe", ".dll"}:
        threats.append("Executable-Masquerade")
        details.append("Executable header in non-executable file")

    return {"clean": not threats, "threats": threats, "details": details}


def check_api_key_exposure(text) -> List[Dict[str, str]]:
    value = str(text)
    detections = []
    patterns = [
        ("aws_access_key", AWS_RE),
        ("github_token", GITHUB_RE),
        ("anthropic_key", ANTHROPIC_RE),
    ]
    for name, pattern in patterns:
        for match in pattern.finditer(value):
            detections.append({"type": name, "match": match.group(0)})
    return detections


def run_guardian_task(task_id, task_description, target) -> Dict:
    try:
        lower = str(task_description).lower()
        if "api" in lower or "key" in lower or "secret" in lower:
            return _result("ok", task_id, check_api_key_exposure(target))
        if "scan" in lower or "virus" in lower or "malware" in lower:
            return _result("ok", task_id, scan_file(target))
        return _result("error", task_id, None, "Unknown guardian task")
    except Exception as exc:
        return _result("error", task_id, None, str(exc))
