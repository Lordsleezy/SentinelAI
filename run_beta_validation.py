#!/usr/bin/env python3
"""Beta readiness validation — compile, import, and subsystem smoke checks."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAILURES: list[str] = []


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    FAILURES.append(msg)


def compile_check() -> None:
    print("\n[compile]")
    targets = [
        "desktop_app.py",
        "core/memory2/engine.py",
        "core/missions/mission_engine.py",
        "core/updater/auto_updater.py",
        "core/release/release_manager.py",
        "workers/guardian/system_monitor.py",
        "workers/licensing/license_manager.py",
        "core/sentinelvision/engine.py",
    ]
    for t in targets:
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / t)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            ok(t)
        else:
            fail(f"{t}: {r.stderr[:200]}")


def import_check() -> None:
    print("\n[import]")
    sys.path.insert(0, str(ROOT))
    modules = [
        ("core.memory2", "get_memory2_engine"),
        ("core.missions", "get_mission_engine"),
        ("core.updater", "get_auto_updater"),
        ("core.release", "get_release_manager"),
        ("workers.guardian.system_monitor", "get_guardian_monitor"),
        ("workers.licensing.license_manager", "get_license_manager"),
        ("core.sentinelvision", "get_vision_engine"),
    ]
    for mod, attr in modules:
        try:
            m = __import__(mod, fromlist=[attr])
            fn = getattr(m, attr)
            fn()
            ok(f"{mod}.{attr}")
        except Exception as e:
            fail(f"{mod}.{attr}: {e}")


def memory_check() -> None:
    print("\n[memory2]")
    try:
        from core.memory2 import get_memory2_engine
        eng = get_memory2_engine()
        eid = eng.remember("preference", "beta validation test", key="beta_test")
        hits = eng.retrieve("beta validation")
        h = eng.health()
        if not eid or h.get("total_entries", 0) < 1:
            fail("memory remember/health")
        else:
            ok(f"entries={h.get('total_entries')} retrieve={len(hits)}")
    except Exception as e:
        fail(str(e))


def mission_check() -> None:
    print("\n[missions]")
    try:
        from core.missions import get_mission_engine
        eng = get_mission_engine()
        m = eng.create_mission("Connect Supabase", goal="Connect Supabase")
        eng.attach_vision_goal(m["mission_id"], "test-goal-id", "Connect Supabase")
        listed = eng.list_missions()
        if not listed:
            fail("mission list empty")
        else:
            ok(f"missions={len(listed)}")
    except Exception as e:
        fail(str(e))


def updater_check() -> None:
    print("\n[updater]")
    try:
        from core.updater import get_auto_updater
        u = get_auto_updater()
        st = u.status()
        if "current_version" not in st:
            fail("updater status missing version")
        else:
            ok(f"version={st['current_version']} channel={st['channel']}")
    except Exception as e:
        fail(str(e))


def release_check() -> None:
    print("\n[release]")
    try:
        from core.release import get_release_manager
        mgr = get_release_manager()
        v = mgr.verify_build()
        if not v.get("ok"):
            fail(f"verify_build: {v.get('errors')}")
        else:
            ok("verify_build")
    except Exception as e:
        fail(str(e))


def license_check() -> None:
    print("\n[license]")
    try:
        from workers.licensing.license_manager import get_license_manager
        lm = get_license_manager()
        st = lm.get_status()
        if "restricted_mode" not in st:
            fail("status missing restricted_mode")
        else:
            ok(f"tier={st['tier']} restricted={st['restricted_mode']}")
    except Exception as e:
        fail(str(e))


def guardian_check() -> None:
    print("\n[guardian]")
    try:
        from workers.guardian.system_monitor import GuardianSystemMonitor
        mon = GuardianSystemMonitor(sample_interval=60)
        snap = mon.collect_snapshot()
        if "cpu_percent" not in snap and "error" not in snap:
            fail("snapshot missing metrics")
        else:
            ok(f"healthy={snap.get('healthy')} cpu={snap.get('cpu_percent')}")
    except Exception as e:
        fail(str(e))


def main() -> int:
    print("Sentinel AI — beta validation")
    compile_check()
    import_check()
    memory_check()
    mission_check()
    updater_check()
    release_check()
    license_check()
    guardian_check()
    print("\n" + ("PASSED" if not FAILURES else f"FAILED ({len(FAILURES)})"))
    for f in FAILURES:
        print(f"  - {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
