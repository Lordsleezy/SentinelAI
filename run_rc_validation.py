#!/usr/bin/env python3
"""Release candidate validation — phases 1–11 automated checks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

RESULTS: dict[str, list] = {"pass": [], "fail": [], "warn": [], "skip": []}


def record(phase: str, status: str, detail: str) -> None:
    RESULTS[status].append(f"[{phase}] {detail}")
    sym = {"pass": "OK", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[status]
    print(f"  {sym}  {phase}: {detail}")


def phase_compile() -> None:
    print("\n=== Phase 1/11: Compile & import ===")
    targets = [
        "desktop_app.py",
        "core/dependency_manager/engine.py",
        "core/model_manager/engine.py",
        "core/onboarding/first_launch.py",
        "core/memory2/engine.py",
        "core/missions/mission_engine.py",
        "core/updater/auto_updater.py",
        "core/sentinelvision/engine.py",
        "workers/guardian/system_monitor.py",
        "workers/licensing/license_manager.py",
    ]
    for t in targets:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(ROOT / t)], capture_output=True, text=True)
        if r.returncode == 0:
            record("compile", "pass", t)
        else:
            record("compile", "fail", f"{t}: {r.stderr[:150]}")


def phase_deps() -> None:
    print("\n=== Phase 2: Dependency manager ===")
    try:
        from core.dependency_manager import get_dependency_manager
        m = get_dependency_manager()
        scan = m.scan_system()
        comps = scan.get("components") or m.list_components()
        if len(comps) >= 5:
            record("deps", "pass", f"scan ok, {len(comps)} components")
        else:
            record("deps", "warn", "few components listed")
    except Exception as e:
        record("deps", "fail", str(e))


def phase_models() -> None:
    print("\n=== Phase 3: Model manager ===")
    try:
        from core.model_manager import get_model_manager
        mm = get_model_manager()
        rec = mm.recommend()
        if rec.get("llama"):
            record("models", "pass", f"recommend llama={rec['llama']}")
        else:
            record("models", "fail", "no llama recommendation")
    except Exception as e:
        record("models", "fail", str(e))


def phase_onboarding() -> None:
    print("\n=== Phase 4: First launch ===")
    try:
        from core.onboarding import get_first_launch
        st = get_first_launch().status()
        if "current_step" in st:
            record("onboarding", "pass", f"step={st.get('current_step')}")
        else:
            record("onboarding", "fail", "invalid status")
    except Exception as e:
        record("onboarding", "fail", str(e))


def phase_supabase() -> None:
    print("\n=== Phase 5: Supabase (schema) ===")
    record("supabase", "skip", "No Supabase backend in repo — website uses SQLite activation DB; Vision uses REST health only")


def phase_stripe() -> None:
    print("\n=== Phase 6: Stripe (website) ===")
    srv = ROOT / "website" / "server.js"
    if not srv.is_file():
        record("stripe", "fail", "website/server.js missing")
        return
    text = srv.read_text(encoding="utf-8")
    checks = ["payment_intent", "stripe/webhook", "createActivationCode"]
    missing = [c for c in checks if c not in text]
    if missing:
        record("stripe", "warn", f"missing patterns: {missing}")
    else:
        record("stripe", "pass", "webhook + payment intent + activation code present")
    if "subscription" not in text.lower():
        record("stripe", "warn", "monthly/annual/lifetime subscriptions not in website server — one-time PI only")


def phase_license() -> None:
    print("\n=== Phase 7: Licensing ===")
    try:
        from workers.licensing.license_manager import get_license_manager
        lm = get_license_manager()
        st = lm.get_status()
        for k in ("restricted_mode", "beta_expires_at", "tier"):
            if k not in st:
                record("license", "fail", f"missing {k}")
                return
        record("license", "pass", f"tier={st['tier']} restricted={st['restricted_mode']}")
    except Exception as e:
        record("license", "fail", str(e))


def phase_updater() -> None:
    print("\n=== Phase 8: Auto-updater ===")
    try:
        from core.updater import get_auto_updater
        u = get_auto_updater()
        st = u.status()
        chk = u.check_for_updates()
        rb = u.rollback_info()
        for k in ("channel", "current_version", "repo"):
            if k not in st:
                record("updater", "fail", f"status missing {k}")
                return
        record("updater", "pass", f"check ok={chk.get('ok')} rollback={rb.get('can_rollback')}")
    except Exception as e:
        record("updater", "fail", str(e))


def phase_guardian() -> None:
    print("\n=== Phase 9: Guardian monitor ===")
    try:
        from workers.guardian.system_monitor import GuardianSystemMonitor
        s = GuardianSystemMonitor().collect_snapshot()
        fake = "fake" in json.dumps(s).lower() and s.get("cpu_percent") == 42.0
        if fake:
            record("guardian", "fail", "fake telemetry detected")
        elif "cpu_percent" in s:
            record("guardian", "pass", f"cpu={s['cpu_percent']}% disks={len(s.get('disks',[]))}")
        else:
            record("guardian", "warn", s.get("error", "psutil missing"))
    except Exception as e:
        record("guardian", "fail", str(e))


def phase_missions() -> None:
    print("\n=== Phase 10: Missions ===")
    try:
        from core.missions import get_mission_engine
        e = get_mission_engine()
        m = e.create_mission("RC Test Mission", goal="Deploy Website")
        e.update_mission(m["mission_id"], progress=50, current_task="testing")
        got = e.get_mission(m["mission_id"])
        if got and got.get("progress") == 50:
            record("missions", "pass", "create/update/persist")
        else:
            record("missions", "fail", "persistence failed")
    except Exception as e:
        record("missions", "fail", str(e))


def phase_vision() -> None:
    print("\n=== Phase 11: Vision ===")
    try:
        from core.sentinelvision import get_vision_engine
        from core.sentinelvision.workflows.workflow_library import WorkflowLibrary
        eng = get_vision_engine()
        lib = WorkflowLibrary().list_templates()
        if eng.onboarding and len(lib) >= 5:
            record("vision", "pass", f"engine+{len(lib)} workflow templates")
        else:
            record("vision", "warn", "engine or templates incomplete")
        from core.sentinelvision.operator.browser import browser_operator
        doc = browser_operator.BrowserOperator.smart_click.__doc__ or ""
        if "OCR" in doc:
            record("vision", "pass", "OCR fallback documented in smart_click")
        else:
            record("vision", "warn", "OCR fallback doc missing")
    except Exception as e:
        record("vision", "fail", str(e))


def main() -> int:
    print("Sentinel AI — Release Candidate Validation")
    phase_compile()
    phase_deps()
    phase_models()
    phase_onboarding()
    phase_supabase()
    phase_stripe()
    phase_license()
    phase_updater()
    phase_guardian()
    phase_missions()
    phase_vision()
    print("\n--- Summary ---")
    print(f"  PASS: {len(RESULTS['pass'])}  FAIL: {len(RESULTS['fail'])}  WARN: {len(RESULTS['warn'])}  SKIP: {len(RESULTS['skip'])}")
    out = ROOT / "data" / "release" / "rc_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"  Written {out}")
    return 1 if RESULTS["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
