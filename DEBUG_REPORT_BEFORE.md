# DEBUG REPORT — BEFORE FIXES
**Branch:** fix/post-session-stability  
**Date:** 2026-06-02  

---

## ISSUE 1 — Guardian Authorization Works But Assessment Never Returns

### Current Behavior
User sends scan request → Guardian asks authorization → User confirms → Guardian says "assessment started" → Nothing more appears.

### Root Causes (3 compounding)

**Root Cause A — Silent thread crash:**  
`_run_full_assessment()` in `workers/guardian/guardian_brain.py` (line 264) launches a daemon thread running `_assess()`. The `_assess()` function has NO top-level try/except. If any unhandled exception occurs (e.g., malformed target string, unexpected nmap output, Unicode decode error), the thread dies silently — no error is emitted to the UI.

**Root Cause B — Missing `broadcast=True` on socket emit:**  
`_emit_guardian_response()` (line 243) calls `socketio.emit('guardian_response', {...})` **without** `broadcast=True`. In Flask-SocketIO threading mode, calling `socketio.emit()` from a background thread started inside an HTTP request handler (not a socket event handler) may not reach all connected clients without explicit broadcast. The `_guardian_log()` function emits to `'log_event'` which is consumed by a global listener that always works, masking the difference.

**Root Cause C — Per-tool missing-tool handling is not emitted:**  
`_run_tool_direct()` (line 149) returns a string ("nmap not installed...") when a tool is missing. But the `_assess()` thread wraps each tool call and emits the result — meaning the tool-not-found string IS emitted. However, if nmap IS found via WSL but hangs for 90 seconds, step 2 blocks the entire thread before step 1's emit can be seen (sequential, not parallel).

### Files Involved
- `workers/guardian/guardian_brain.py` — `_assess()`, `_emit_guardian_response()`, `_run_tool_direct()`

---

## ISSUE 2 — Earn Accept & Work Stalls

### Current Behavior
Log shows: `[EARN] Earn job accepted` → `[EARN] Analyzing bounty` → then nothing visible in the Earn window.

### Root Causes (2 compounding)

**Root Cause A — No progress events emitted from analysis stages:**  
`api_earn_accept()` in `desktop_app.py` (line 4564) calls `engine.analyze_bounty()` in a background thread. `analyze_bounty()` (line 419 of `workers/aider_engine.py`) emits Aider output lines to the LOG tab (source="earn"), but never explicitly emits stage-level progress: no "ENTER scope extraction", no "Recommendations generated", no "COMPLETE". The Earn window (`desktop-shell/earn_window.html`) has **no socket listener** — it never receives any progress events from the backend.

**Root Cause B — No timeout protection and no failure message:**  
If Aider stalls (Ollama slow, model unavailable), the only protection is the 30-second no-output watchdog inside `_run_aider()`. But Aider can keep producing output (e.g., model thinking aloud) indefinitely without completing the task. The `MAX_RUNTIME = 180s` Aider kill exists, but `analyze_bounty()` itself has no wrapper timeout. If Aider is killed, the error is logged but never surfaced to the Earn window as a visible failure message.

### Files Involved
- `desktop_app.py` — `api_earn_accept()` (line 4564)
- `workers/aider_engine.py` — `analyze_bounty()` (line 419)
- `desktop-shell/earn_window.html` — missing socket listener

---

## ISSUE 3 — Build Works But Launch Does Not

### Current Behavior
"build calculator" → Aider runs → `forge_complete` socket event fires → `window.pendingLaunch` is set in orb.html (line 3475). User says "launch it" → `sendChatWithPurchase()` sends "launch it" to `/api/chat` → `is_conversational_input("launch it")` returns `True` → `_canned_response("launch it")` returns "I'm here and ready to help!" → No launch occurs.

### Root Cause
**No launch intent handler in the chat route.**  
`api_chat()` in `desktop_app.py` does not check for launch keywords ("launch it", "run it", "open it", "start it"). The message falls through to `is_conversational_input()` which returns `True`, returning a generic canned response. `window.pendingLaunch` is set in the frontend but the frontend's `sendChatWithPurchase()` never checks it when receiving the chat response. There is no `artifact_registry.py` to persist build history across sessions — if the window is refreshed, `window.pendingLaunch` is lost.

### Files Involved
- `desktop_app.py` — `api_chat()` (line 4107), missing launch keyword routing
- `desktop-shell/orb.html` — `sendChatWithPurchase()` (line 3562), does not check `window.pendingLaunch`
- Missing: `artifact_registry.py`

---

## ISSUE 4 — Claude/GPT Connect Flow Is Incomplete

### Current Behavior
Connect button in Memory panel → calls `connectClaude()` / `connectChatGPT()` in orb.html → hits `/api/login/connect/claude` → if no credentials: returns `needs_credentials` status → shows "Claude credentials not set. Go to Settings to add them." → Nothing happens.

### Root Cause
**No inline credential modal in the main orb UI.**  
The credential save flow exists in `desktop-shell/login_window.html` (the initial setup screen), and the API endpoint `/api/login/save` (line 592 of `desktop_app.py`) correctly encrypts and stores credentials. But in the main orb UI (Memory panel → Connections section), pressing "Connect" when no credentials are saved only shows a plain text warning message — there is no modal or inline form to enter credentials. The user has no way to save credentials from within the running application's Memory panel without going back to the login screen.

### Files Involved
- `desktop-shell/orb.html` — `connectClaude()` (line 2781), `connectChatGPT()` (line 2805)
- `desktop_app.py` — `/api/login/connect/claude` (line 649), `/api/login/save` (line 592)

---

## Summary Table

| Issue | File(s) | Root Cause | Fix |
|-------|---------|------------|-----|
| 1 — Guardian no return | `guardian_brain.py` | No top-level try/except in thread; missing `broadcast=True` | Wrap entire `_assess()`, add `broadcast=True`, per-stage error handling |
| 2 — Earn stalls | `aider_engine.py`, `earn_window.html`, `desktop_app.py` | No progress events emitted; no socket listener in earn window; no timeout wrapper | Add stage logs, socket listener in earn window, 120s timeout |
| 3 — Launch fails | `desktop_app.py`, `orb.html` | No launch keyword routing in chat; `pendingLaunch` never used | `artifact_registry.py`, launch routing in chat, `pendingLaunch` check in orb |
| 4 — Connect incomplete | `orb.html` | No inline credential modal in Memory panel | Add AI Account Setup Modal triggered on Connect press |
