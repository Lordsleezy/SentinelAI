# Sentinel Stability Report
**Branch:** `fix/stability-guardian-professionalization`  
**Date:** 2026-06-02  
**Tests:** 20/20 PASSED

---

## Root Causes Found

### ISSUE 1 — Socket.IO `broadcast=True` error
**Root cause:** `flask-socketio 5.3.5` removed the `broadcast=True` parameter from `SocketIO.emit()`. The underlying `python-socketio` `Server.emit()` does not accept it. When called from background threads (Guardian, Earn, Build), every emit raised `TypeError: Server.emit() got an unexpected keyword argument 'broadcast'`. These exceptions were caught silently, so emits never reached the frontend.

**Fix:** Removed `broadcast=True` from all 6 call sites across:
- `workers/guardian/guardian_brain.py` (2 calls — `_emit_guardian_response` + `_guardian_log`)
- `workers/task_manager.py`
- `workers/artifacts/artifact_registry.py`
- `workers/projects/project_manager.py`
- `desktop_app.py` (`forge_complete` emit)

**Verification:** `grep -r "broadcast=True" --include="*.py"` returns zero results in Sentinel source.

---

### ISSUE 2 — Guardian stalls after authorization
**Root cause:** The same `broadcast=True` exception. The `_assess` background thread was running all 7 stages successfully, but every progress emit silently failed. The user saw "Assessment starting…" then nothing. No thread death, just silent emit failures.

**Fix:** Resolved by the Issue 1 broadcast fix. Guardian now emits all 7 stages with full progress (5% → 15% → 30% → 45% → 55% → 65% → 80% → 95% → 100%).

---

### ISSUE 3 — Earn analysis times out
**Root cause:** 
1. `qwen2.5-coder:14b` is too slow for a 120-second outer `concurrent.futures` timeout on local hardware. A detailed bounty analysis prompt ("be technical and thorough") generates 500–2000 tokens at ~5–15 tok/s on a 14B model = 33–400s, far exceeding the budget.
2. The `ThreadPoolExecutor` wrapper added no value — Aider's internal watchdog (`MAX_RUNTIME=180s`, `STUCK_TIMEOUT=30s`) already handles kills.

**Fix:**
- Switched earn analysis to `ollama/qwen2.5-coder:7b` (available, ~2× faster, overridable via `AIDER_EARN_MODEL` env var)
- Removed `concurrent.futures.ThreadPoolExecutor` wrapper — call `_run_aider` directly
- Constrained the prompt to "3–5 bullet points each section" instead of "be thorough"
- Added timing diagnostics: logs `model=`, `scope_tokens~N`, `elapsed=Ns`
- If `AIDER_EARN_MODEL` or `AIDER_MODEL` is set, that model is used

---

### ISSUE 4 — Claude shows "Connected ✓" without real session
**Root cause:** `api_login_status()` returned `"claude_connected": bool(creds.get("claude_email"))`. Any saved email credential caused `Connected ✓` to show even with no live browser session.

**Fix:** 
- `claude_connected` now reads `browser_sessions.claude_logged_in` — only True after `login_claude()` succeeds
- Added `claude_creds_saved` / `chatgpt_creds_saved` fields for the UI to distinguish "credentials on disk" from "active session"
- `orb.html` updated: green dot = active session, amber dot = credentials saved but not connected, gray = not configured

---

### ISSUE 5 — Build system regression
**Root cause:** The `forge_complete` Socket.IO emit inside `_run_approved_build` used `broadcast=True`, which raised an exception caught by the outer `except Exception as _be: ctx.fail(str(_be))` block. The build succeeded (Aider ran, files were created, artifact was registered) but the exception marked the task as FAILED and the user saw "Build error".

**Fix:** Resolved by the Issue 1 broadcast fix.

---

## Files Changed

| File | Change |
|------|--------|
| `workers/guardian/guardian_brain.py` | Removed `broadcast=True` (×2); rewrote `_run_full_assessment` to 7-stage professional workflow; added `_compute_risk_score` + `_build_final_report` module-level helpers |
| `workers/task_manager.py` | Removed `broadcast=True` |
| `workers/artifacts/artifact_registry.py` | Removed `broadcast=True` |
| `workers/projects/project_manager.py` | Removed `broadcast=True` |
| `desktop_app.py` | Removed `broadcast=True` from `forge_complete` emit; fixed `claude_connected` to use session state; added `claude_creds_saved` / `chatgpt_creds_saved` fields |
| `workers/aider_engine.py` | Earn: removed `ThreadPoolExecutor`; switched to 7b model; concise prompt; timing diagnostics |
| `desktop-shell/orb.html` | Three-state connection indicator (active/saved/none) for Claude and ChatGPT |
| `workers/guardian/tools/nuclei_tool.py` | Fixed `r"C:\"` syntax error (pre-existing) |
| `workers/guardian/tools/httpx_tool.py` | New file — ProjectDiscovery httpx wrapper |
| `workers/guardian/tools/subfinder_tool.py` | New file — ProjectDiscovery Subfinder wrapper |
| `workers/guardian/tools/katana_tool.py` | New file — ProjectDiscovery Katana wrapper |
| `workers/guardian/tools/amass_tool.py` | New file — OWASP Amass wrapper |
| `workers/guardian/tools/tool_registry.py` | New file — central tool detector + status reporter |
| `run_stability_tests.py` | New file — 20-test suite |

---

## Tests Run

```
20/20 PASSED

[PASS] broadcast=True removed from ALL Sentinel Python files
[PASS] TEST 1 — Artifact created
[PASS] TEST 1 — Launch command derived
[PASS] TEST 1 — Launch executes ok=True
[PASS] TEST 2 — Guardian emits start step
[PASS] TEST 2 — Guardian progress updates       [5, 15, 30, 45, 55, 65, 80, 95, 100]
[PASS] TEST 2 — Guardian final report emitted
[PASS] TEST 3 — Analysis completes within 20s   [elapsed: 0.0s with mock]
[PASS] TEST 3 — Task reaches COMPLETED or FAILED
[PASS] TEST 3 — Uses 7b earn model (not 14b)
[PASS] TEST 4 — Session-based check implemented
[PASS] TEST 4 — False positive removed (was creds-only)
[PASS] TEST 4 — new creds_saved field present for UI
[PASS] TEST 5 — Nuclei gracefully skipped when not installed
[PASS] TEST 6 — Subfinder gracefully skipped when not installed
[PASS] TEST 7 — httpx tool installed and detected
[PASS] TEST 8 — Katana gracefully skipped when not installed
[PASS] TEST 9 — ZAP gracefully skipped when not installed
[PASS] TEST 10 — Amass gracefully skipped when not installed
[PASS] ToolRegistry — initializes without error
```

---

## Known Limitations

- Earn analysis tested with mocked `_run_aider`. Real-world timing depends on Ollama load and model. `AIDER_EARN_MODEL=ollama/qwen2.5-coder:7b` is the default; override with `AIDER_EARN_MODEL=ollama/<model>`.
- Guardian progress emits verified via mock; real frontend Socket.IO tested manually.
- Claude/ChatGPT session state requires `browser_sessions` to be initialized (happens at app startup). On a fresh `desktop_app.py` run without credentials, `claude_connected` will be `False` (correct).
