#!/usr/bin/env python3
"""Run onboarding steps outside Electron — prints timing and writes onboarding_debug.log."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _run_step(name: str, fn) -> dict:
    t0 = time.perf_counter()
    print(f"[START] {name}")
    try:
        out = fn()
        ms = (time.perf_counter() - t0) * 1000
        print(f"[OK]    {name} ({ms:.0f} ms)")
        if isinstance(out, dict):
            print(json.dumps(out, indent=2, default=str)[:2000])
        return {"ok": True, "ms": ms, "result": out}
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        print(f"[FAIL]  {name} ({ms:.0f} ms): {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "ms": ms, "error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug Sentinel first-run onboarding")
    parser.add_argument("--simulate-no-ollama", action="store_true")
    parser.add_argument("--simulate-no-gpu", action="store_true")
    parser.add_argument("--simulate-offline", action="store_true")
    parser.add_argument("--no-background", action="store_true", help="Skip background Ollama/model install")
    args = parser.parse_args()

    if args.simulate_no_ollama:
        os.environ["SENTINEL_SIMULATE_NO_OLLAMA"] = "1"
    if args.simulate_no_gpu:
        os.environ["SENTINEL_SIMULATE_NO_GPU"] = "1"
    if args.simulate_offline:
        os.environ["SENTINEL_SIMULATE_OFFLINE"] = "1"

    _banner("1. Hardware probe (must finish < 10s)")
    from core.onboarding.hardware_probe import probe_machine_profile

    _run_step("probe_machine_profile", probe_machine_profile)

    _banner("2. Machine scanner cache")
    from workers.setup.machine_scanner import get_machine_scanner

    _run_step("machine_scanner.scan", get_machine_scanner().scan)

    _banner("3. Onboarding pipeline fast scan + background start")
    from core.onboarding.pipeline import get_onboarding_pipeline

    pipe = get_onboarding_pipeline()

    def _scan():
        p = pipe.run_fast_scan()
        if not args.no_background:
            pipe.start_background_setup(p)
        return {"profile_keys": list(p.keys()), "progress": pipe.progress()}

    _run_step("pipeline.scan+background", _scan)

    _banner("4. Quick readiness (non-blocking)")
    from core.model_runtime import get_model_runtime

    _run_step("readiness_quick", lambda: get_model_runtime().readiness_quick())

    _banner("5. First launch orchestrator (all steps, non-blocking)")
    from core.onboarding.first_launch import get_first_launch

    _run_step("first_launch.run_all", get_first_launch().run_all)

    _banner("6. Force complete (always allow chat)")
    _run_step("pipeline.force_complete", lambda: pipe.force_complete(allow_degraded=True))

    log_path = _ROOT + "/data/onboarding/onboarding_debug.log"
    print(f"\nDebug log: {log_path}")
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
        print(f"Last {min(8, len(lines))} log entries:")
        for line in lines[-8:]:
            print(" ", line.rstrip())

    print("\nDone — Sentinel should allow chat (allow_degraded=True).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
