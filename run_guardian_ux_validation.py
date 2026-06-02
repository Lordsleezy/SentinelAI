#!/usr/bin/env python3
"""Guardian UX professionalization validation."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

errors = []

def check(name, fn):
    try:
        fn()
        print(f"OK  {name}")
    except Exception as e:
        errors.append(f"{name}: {e}")
        print(f"FAIL {name}: {e}")


def main():
    check("bootstrap_manager", lambda: __import__("workers.guardian.bootstrap_manager", fromlist=["run_bootstrap"]))
    check("runtime_manager", lambda: __import__("workers.guardian.runtime_manager", fromlist=["get_brain_status"]).get_brain_status())
    check("tool_registry", lambda: __import__("workers.guardian.guardian_tool_registry_store", fromlist=["refresh_registry"]).refresh_registry())
    check("findings_center", lambda: __import__("workers.guardian.findings_center", fromlist=["start_session"]).start_session("test.local", "test-sess"))
    check("guardian_ux", lambda: __import__("workers.guardian.guardian_ux", fromlist=["humanize_progress"]).humanize_progress("subfinder", "**Subfinder ✓** 3 subs"))
    check("guardian_brain", lambda: __import__("workers.guardian.guardian_brain", fromlist=["GuardianBrain"]).GuardianBrain())
    print("---")
    if errors:
        print("FAILED", len(errors))
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
