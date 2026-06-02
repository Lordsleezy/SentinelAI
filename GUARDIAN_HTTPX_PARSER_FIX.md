# Guardian HTTPX Parser Fix

## Problem

ProjectDiscovery **httpx** was executing successfully and writing valid URLs to stdout (plain text, one URL per line), but Guardian logged:

```
httpx: 0 hosts parsed
```

**Root cause:** `httpx_compat._parse_json_lines()` only accepted JSON lines starting with `{`. Plain/silent output (no `-json`, or default URL-only lines) was ignored. The old plain-text fallback required a `[status]` suffix (`https://host [200]`), which PD httpx often does not emit in silent mode.

### Example stdout (unparsed before fix)

```
https://sentinelprime.org
https://www.sentinelprime.org
https://crm.sentinelprime.org
```

## Solution

`workers/guardian/tools/httpx_compat.py` now uses a multi-mode parser:

| Mode | Detection | Example |
|------|-----------|---------|
| `json_array` | stdout starts with `[` | `[{"url":"..."}]` |
| `jsonl` | one JSON object per line | `{"url":"...","status-code":200}` |
| `plain_status` | URL + `[code]` on same line | `https://foo.com [200]` |
| `plain_text` | one URL (or host) per line | `https://sentinelprime.org` |
| `regex_fallback` | URLs in stdout but structured parse empty | logs + extracts `https?://…` |

### Diagnostics (`[GUARDIAN]`)

- `raw stdout bytes: N`
- `parser mode selected: <mode>`
- `hosts parsed: N`
- `httpx parsed hosts: N`

If structured parsing returns zero but stdout contains URLs, **regex fallback always runs** — never reports 0 when valid URLs exist.

### Pipeline

`guardian_brain._safe_live_hosts()` now treats `status_code == 0` (plain URL lines) as chainable hosts so Katana/Nuclei can proceed.

## Files changed

- `workers/guardian/tools/httpx_compat.py` — `parse_httpx_stdout()`, fallbacks, logging
- `workers/guardian/tools/httpx_tool.py` — `httpx parsed hosts: N` log line
- `workers/guardian/guardian_brain.py` — plain URL hosts count as live for chaining

**Not modified:** Earn, Builder, Memory.

## Validation

```bash
python run_guardian_httpx_parser_tests.py
```

## Before / after logs

### Before (parser)

```
[GUARDIAN] httpx stdout: https://sentinelprime.org
https://www.sentinelprime.org
https://crm.sentinelprime.org
[GUARDIAN] httpx: 0 hosts parsed (87 stdout bytes) — pipeline continues
```

### After (parser)

```
[GUARDIAN] httpx stdout: https://sentinelprime.org ...
[GUARDIAN] raw stdout bytes: 87
[GUARDIAN] parser mode selected: plain_text
[GUARDIAN] hosts parsed: 3
[GUARDIAN] httpx parsed hosts: 3
[GUARDIAN] httpx: 3 host(s) from ProjectDiscovery
```

### sentinelprime.org scan (expected pipeline)

```
Subfinder: 3 subdomain(s)
[GUARDIAN] raw stdout bytes: …
[GUARDIAN] parser mode selected: plain_text
[GUARDIAN] httpx parsed hosts: 3
httpx ✓ 3 parsed, 3 live (2xx-4xx)
Katana / Nuclei continue with primary + parsed URLs
```

Live validation (2026-06-02, bundled `tools/httpx/httpx.exe` v1.9.0):

```
[GUARDIAN] httpx stdout: https://sentinelprime.org
https://crm.sentinelprime.org
https://www.sentinelprime.org
[GUARDIAN] raw stdout bytes: 86
[GUARDIAN] parser mode selected: plain_text
[GUARDIAN] hosts parsed: 3
[GUARDIAN] httpx parsed hosts: 3
```

```bash
python run_guardian_httpx_parser_tests.py
python -c "from workers.guardian.tools.httpx_compat import run_httpx; r=run_httpx(['sentinelprime.org','www.sentinelprime.org','crm.sentinelprime.org'], timeout=10, log=print); print(len(r.hosts))"
```
