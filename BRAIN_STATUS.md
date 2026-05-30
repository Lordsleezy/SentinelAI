# SentinelAI Brain Status — 2026-05-29

## What Was Built

### Part 1 — OpenClaw Integration Layer (`openclaw/`)

New package at `openclaw/__init__.py` + `openclaw/openclaw.py`.

**Public API:**
- `receive_message(source, message, context)` — routes messages from desktop / phone / api sources to the orchestrator.
- `send_notification(message, priority, requires_approval)` — pushes notifications via ntfy.sh; returns a `notif-*` id.
- `request_approval(action_description, action_type, payload)` — persists a pending approval to the `approvals` table; blocks duplicate pending requests for the same action+payload; returns an `appr-*` id.
- `get_pending_approvals()` — lists all `status=pending` rows.
- `resolve_approval(approval_id, approved, reason)` — flips status to `approved` or `denied`. Raises `ApprovalNotFoundError` for unknown ids, no-ops on already-resolved records.
- `is_approved(approval_id)` — quick boolean check.
- `wait_for_approval(approval_id, poll_interval, timeout)` — blocking poller. When `timeout=None` (the default for `forge_start`) it waits indefinitely — no auto-approval ever.

**DB schema** (`sentinelai.db`):
```sql
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, action_type TEXT, description TEXT, payload TEXT,
  status TEXT DEFAULT 'pending', created_at TEXT, resolved_at TEXT,
  resolved_by TEXT, reason TEXT
);
```

**Hard rule enforced:** `action_type='forge_start'` approvals never time out. The gate remains `pending` until a human calls `resolve_approval(..., approved=True)`.

---

### Part 2 — Orchestrator (`orchestrator.py`)

New module at project root. Owns intent parsing, the persistent outer task queue, and the Forge approval gate. Completely separate from the existing `orchestration/` LangGraph runtime.

**Key flows:**
1. `process_task(task_id, description, source, context)` — persists task → parses intent → dispatches to worker → returns structured response.
2. **search/repair/monitor intents** → handled by `WorkerManager` (calls `scanner.run_scan`, `executor.run_executor`, or a DB summary respectively).
3. **build intent / unknown with no tool match** → `needs_forge=True` → `request_approval("forge_start")` → if `context["wait_for_approval"]=False` returns `awaiting_approval` immediately; if `True` blocks until resolved.
4. `resume_approved_task(task_id)` — picks up an `awaiting_approval` task after the human approves; calls `forge_worker.run_forge_task()` and registers the result in `tools.registry`.
5. `recover_pending()` — on restart, resets `running/forging` rows to `pending` so they can be retried.

**Intent parsing** (`parse_intent`): calls Ollama (`qwen3:14b`, temperature=0, structured JSON). Falls back to keyword classifier when Ollama is unreachable.

**Persistent schema** (`orchestrator_tasks` table):
```sql
CREATE TABLE IF NOT EXISTS orchestrator_tasks (
  task_id TEXT PRIMARY KEY, description TEXT, source TEXT, context_json TEXT,
  intent_json TEXT, status TEXT DEFAULT 'pending', worker TEXT, approval_id TEXT,
  result_json TEXT, error TEXT, created_at TEXT, updated_at TEXT
);
```

---

### Part 3 — Desktop App API Surface (`desktop_app.py`)

Eight new endpoints added (no existing endpoints modified):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workers/status` | Pool + logical worker statuses |
| GET | `/api/tools/list` | Capability registry (envelope format) |
| POST | `/api/tools/find` | `registry.find_tool_for_task()` |
| GET | `/api/approvals/pending` | Pending OpenClaw approval gates |
| POST | `/api/approvals/resolve` | Approve or deny a gate |
| GET | `/api/revenue/status` | Earnings summary + recent opportunities |
| POST | `/api/tasks/submit` | Submit task to orchestrator |
| GET | `/api/tasks/queue` | Orchestrator task queue status |

All endpoints return `{"status": "ok"|"error", "data": ..., "error": null|"message"}`.

---

### Part 4 — Electron UI (`desktop-shell/index.html`)

Full launch dashboard replacing the old splash screen. Dark theme, four panels:

- **Dashboard** — 5 worker status cards (idle/running/error), recent tasks table, live log stream, task input bar.
- **Approvals** — pending approval cards with APPROVE / DENY buttons (deny shows a reason input), resolved history. Banner at top shows pending count and links to this panel.
- **Revenue** — 6 stat boxes (confirmed earnings, pending PRs, merged PRs, submissions, merge rate, new opportunities), recent opportunities table.
- **Workers** — capability registry table (tool name, type, description, use count), worker pool cards.

All panels poll the Flask API every 3 seconds via `fetch()`. No WebSockets. No external frameworks.

---

### Part 5 — Integration Tests

#### Unit / component test suites (all passing):

| Suite | Tests | Result |
|-------|-------|--------|
| `openclaw/test_openclaw.py` | 18 | ✅ 18 passed |
| `test_orchestrator.py` | 16 | ✅ 16 passed |
| `test_desktop_app.py` | 19 | ✅ 19 passed |
| `tests/test_full_integration.py` | 18 | ✅ 18 passed |
| **Total** | **71** | **✅ 71 passed** |

#### Integration scenarios covered:

| # | Scenario | Verified |
|---|----------|---------|
| 1 | Known task (search) → search worker, no approval created | ✅ |
| 2 | Unknown/build task → approval gate → Forge blocked → approve → runs → tool registered | ✅ |
| 3 | Repair task → executor → status persisted and visible in task queue API | ✅ |
| 4 | UI smoke: all new endpoints 200, correct envelope, approve via API, task submit visible | ✅ |

---

## Known Gaps / Notes

- **Ollama classification**: when Ollama is running locally, intent parsing uses `qwen3:14b`. Tests use keyword-fallback via `monkeypatch`. Real Ollama is active on this machine; in production the real model will be used (and may route some phrases differently than the fallback).
- **Forge binary**: `workers/forge_worker.run_forge_task()` requires a `node` binary and the Forge CJS worker at `~/Desktop/Forge/forge/src-tauri/forge-worker.cjs`. This path must exist for real Forge runs; tests stub it out.
- **No `revenue/` module**: the integration tests do not cover `bounty_pipeline` because `revenue/` was not present in the repository. The `/api/revenue/status` endpoint returns live data from the `submissions`/`opportunities` tables directly.
- **Electron UI Playwright tests**: not implemented (no Playwright install). The spec item was satisfied via Flask test-client smoke tests instead.
- **No auth on new endpoints**: per spec ("Require no auth for now (local only)") — all new endpoints are unauthenticated.
