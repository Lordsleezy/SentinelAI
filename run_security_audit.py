#!/usr/bin/env python3
"""Run full Sentinel security audit and write SECURITY_HEALTH_REPORT.md."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-baseline", action="store_true")
    parser.add_argument("--rebuild-manifest", action="store_true")
    args = parser.parse_args()

    if args.rebuild_baseline:
        from sentinel_security.self_protection import build_baseline
        build_baseline()
        print("Integrity baseline rebuilt")

    if args.rebuild_manifest:
        from sentinel_security.module_signing import build_manifest
        build_manifest()
        print("Module manifest rebuilt")

    from sentinel_security.orchestrator import get_security
    from sentinel_security.module_signing import build_manifest

    if not args.rebuild_manifest:
        build_manifest()

    sec = get_security()
    report = sec.full_audit_report()
    health_md = report.get("health_markdown", "")

    out = ROOT / "SECURITY_HEALTH_REPORT.md"
    out.write_text(health_md + "\n\n---\n\n## Audit JSON\n\n```json\n" +
                   json.dumps({k: v for k, v in report.items() if k != "health_markdown"}, indent=2)[:12000] +
                   "\n```\n", encoding="utf-8")

    print(f"Wrote {out}")
    print(f"Health score: {report.get('health', {}).get('score')}")
    print(f"Local-first passed: {report.get('bootstrap', {}).get('local_first_passed')}")
    print(f"Audit chain valid: {report.get('audit_chain_valid')}")
    failed = [m for m in report.get("module_verify", []) if not m.get("ok")]
    if failed:
        print(f"Module verify failures: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
