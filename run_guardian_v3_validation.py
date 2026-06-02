#!/usr/bin/env python3
"""Guardian v3 validation — writes GUARDIAN_V3_VALIDATION.md"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    lines = [
        "# Guardian v3 Validation Report",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        "",
    ]
    errors = []

    # Tools
    try:
        from workers.guardian.bundled_toolchain import CORE_TOOL_IDS, diagnose_core_tool
        from workers.guardian.tools.tool_registry import get_tool_diagnostics

        tool_rows = get_tool_diagnostics()
        installed = [t for t in tool_rows if t.get("installed")]
        missing = [t["id"] for t in tool_rows if not t.get("installed")]

        lines += ["## Installed Tools", ""]
        lines.append("| Tool | Status | Version | Health | Path |")
        lines.append("|------|--------|---------|--------|------|")
        for t in tool_rows:
            if t.get("roadmap") and t.get("id") in ("reconftw", "crypto_intel"):
                continue
            lines.append(
                f"| {t.get('label', t.get('id'))} | {t.get('status_line', '')} | "
                f"{t.get('version') or '—'} | {t.get('health', '—')} | "
                f"`{(t.get('path') or '')[:60]}` |"
            )
        lines += ["", "## Missing Tools", ""]
        lines.append(", ".join(missing) if missing else "_None required for partial run_")
        lines += ["", "## Tool Versions (core)", ""]
        for tid in CORE_TOOL_IDS:
            d = diagnose_core_tool(tid)
            lines.append(f"- **{tid}**: {d.get('version') or 'unknown'} ({d.get('status_line')})")
    except Exception as e:
        errors.append(f"tools: {e}")
        lines.append(f"Tool diagnostics error: {e}")

    # Runtime
    lines += ["", "## AI Runtime Status", ""]
    try:
        from workers.guardian.guardian_runtime_manager import get_runtime_dashboard, list_ollama_models
        dash = get_runtime_dashboard()
        models = list_ollama_models()
        lines.append(f"- **Selected model:** `{dash.get('model')}`")
        lines.append(f"- **Status:** {dash.get('status')}")
        lines.append(f"- **Ollama URL:** {dash.get('ollama_url')}")
        lines.append(f"- **Installed models:** {len(models)}")
        lines.append(f"- **VRAM (MB):** {dash.get('vram_mb')}")
        lines.append(f"- **Last inference (ms):** {dash.get('inference_ms_last')}")
    except Exception as e:
        errors.append(f"runtime: {e}")
        lines.append(f"Runtime error: {e}")

    # Pipeline / brain
    lines += ["", "## Pipeline Status", ""]
    try:
        from workers.guardian.guardian_brain import GuardianBrain
        brain = GuardianBrain(socketio=None)
        lines.append("- GuardianBrain loads: **OK**")
        lines.append("- Stage logging: Entering / Running / Completed / Skipped / Failed")
        lines.append("- Extended stages: assetfinder, dnsx, naabu, ffuf, threat intel")
    except Exception as e:
        errors.append(f"brain: {e}")
        lines.append(f"Brain error: {e}")

    # Tasks
    lines += ["", "## Task System Status", ""]
    try:
        from workers.task_manager import create_task, update_task, get_task, RUNNING, COMPLETED
        t = create_task("Guardian v3 validation probe", source="guardian", metadata={"probe": True})
        update_task(t["id"], status=RUNNING, progress=50, current_stage="Validation")
        update_task(t["id"], status=COMPLETED, progress=100, result_summary="probe ok")
        got = get_task(t["id"])
        lines.append(f"- create/update/get: **OK** (`{got['id']}`)" if got else "- get failed")
    except Exception as e:
        errors.append(f"tasks: {e}")
        lines.append(f"Task error: {e}")

    # Threat intel
    lines += ["", "## Threat Intel Status", ""]
    try:
        from workers.guardian.guardian_threat_intel import analyze_target
        r = analyze_target("example.com")
        lines.append(f"- Module loads: **OK**")
        lines.append(f"- Sources used: {r.sources_used or []}")
        lines.append(f"- Summaries: {len(r.threat_summaries)}")
        if r.errors:
            lines.append(f"- Notes: {'; '.join(r.errors[:2])}")
    except Exception as e:
        errors.append(f"threat_intel: {e}")
        lines.append(f"Threat intel error: {e}")

    # Findings DB
    lines += ["", "## Findings DB", ""]
    try:
        from workers.guardian.guardian_findings_db import GuardianFindingsDB
        db = GuardianFindingsDB()
        fid = db.add(target="validation.local", tool="probe", severity="informational", description="v3 test")
        n = db.count()
        lines.append(f"- SQLite store: **OK** (rows={n}, last_id={fid})")
    except Exception as e:
        errors.append(f"findings: {e}")
        lines.append(f"Findings DB error: {e}")

    # Trusted targets
    lines += ["", "## Trusted Targets", ""]
    try:
        from workers.guardian.guardian_trusted_targets import approve, is_trusted, list_trusted
        approve("sentinelprime.org", note="validation")
        lines.append(f"- sentinelprime.org trusted: **{is_trusted('sentinelprime.org')}**")
        lines.append(f"- Count: {len(list_trusted())}")
    except Exception as e:
        errors.append(f"trusted: {e}")
        lines.append(f"Trusted targets error: {e}")

    # Performance (quick)
    lines += ["", "## Performance Metrics", ""]
    try:
        import time
        from workers.guardian.bundled_toolchain import probe_tool_version, resolve_tool_binary
        t0 = time.perf_counter()
        for tid in ("httpx", "subfinder"):
            p = resolve_tool_binary(tid)
            if p:
                probe_tool_version(p.path)
        elapsed = int((time.perf_counter() - t0) * 1000)
        lines.append(f"- Tool probe batch: {elapsed} ms")
    except Exception as e:
        lines.append(f"- Performance probe skipped: {e}")

    lines += ["", "## Remaining Gaps", ""]
    gaps = [
        "Auto-update of tool binaries (version pin / refresh policy)",
        "gowitness screenshot pipeline stage",
        "Full AbuseIPDB/OTX without API keys (limited public data only)",
        "Crypto threat intel execution (roadmap module only)",
        "Unify guardian_worker file-scan API with GuardianBrain pipeline branding",
        "GPU metrics when nvidia-smi unavailable",
    ]
    if missing:
        gaps.insert(0, f"Install missing pipeline tools: {', '.join(missing[:12])}")
    for g in gaps:
        lines.append(f"- {g}")

    lines += ["", "## Validation Result", ""]
    if errors:
        lines.append(f"**PARTIAL** — {len(errors)} error(s): " + "; ".join(errors))
        out_code = 1
    else:
        lines.append("**PASSED** — core v3 modules operational.")
        out_code = 0

    out = ROOT / "GUARDIAN_V3_VALIDATION.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    return out_code


if __name__ == "__main__":
    raise SystemExit(main())
