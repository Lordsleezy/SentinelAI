#!/usr/bin/env python3
"""Guardian httpx stdout parser validation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers.guardian.tools.httpx_compat import parse_httpx_stdout, _ensure_hosts_from_stdout


def ok(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    failed = 0

    # User-reported case: plain URLs, one per line (no JSON, no [status])
    plain = """https://sentinelprime.org
https://www.sentinelprime.org
https://crm.sentinelprime.org
"""
    hosts, mode = parse_httpx_stdout(plain)
    failed += 0 if ok("plain_text URLs", mode == "plain_text" and len(hosts) == 3, f"mode={mode} n={len(hosts)}") else 1

    hosts2, mode2 = _ensure_hosts_from_stdout(plain, [], "none")
    failed += 0 if ok("regex fallback never needed for plain", len(hosts2) == 3, f"n={len(hosts2)}") else 1

    # JSONL (ProjectDiscovery -json)
    jsonl = (
        '{"url":"https://a.example.com","status-code":200,"title":"A"}\n'
        '{"input":"https://b.example.com","status_code":301,"title":"B"}\n'
    )
    h3, m3 = parse_httpx_stdout(jsonl)
    failed += 0 if ok("jsonl", m3 == "jsonl" and len(h3) == 2, f"{m3} {len(h3)}") else 1

    # Plain with status brackets
    ps = "https://foo.com [200] https://bar.com [404]\n"
    h4, m4 = parse_httpx_stdout(ps)
    failed += 0 if ok("plain_status", m4 == "plain_status" and len(h4) >= 1, f"{m4} {len(h4)}") else 1

    # Garbage + URLs → regex
    messy = "INFO: probe done\nhttps://x.test/path\nnoise\n"
    h5, m5 = parse_httpx_stdout(messy)
    failed += 0 if ok("regex from messy stdout", len(h5) >= 1, f"{m5} {len(h5)}") else 1

    # Zero structured but URLs exist — forced fallback
    fake_empty = "https://only-url.example\n"
    h6, m6 = _ensure_hosts_from_stdout(fake_empty, [], "none")
    failed += 0 if ok("forced fallback", len(h6) == 1 and m6 == "regex_fallback", f"{m6}") else 1

    print(f"\n{'ALL PASSED' if failed == 0 else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
