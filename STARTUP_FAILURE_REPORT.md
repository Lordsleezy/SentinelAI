# Startup Failure Report

**Date:** 2026-06-02  
**Symptom:** Electron splash hang; backend `Exited code=1`; restart loop.

---

## Step 1 — Direct run traceback

**Command:** `python desktop_app.py`

```
  File "C:\Users\pgg12\Desktop\SentinelAI\desktop_app.py", line 3859
    global _pending_godot_install
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
SyntaxError: name '_pending_godot_install' is assigned to before global declaration
```

After fixing line 3859, compile revealed a second error:

```
  File "desktop_app.py", line 4793
    global _pending_godot_install
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
SyntaxError: name '_pending_godot_install' is used prior to global declaration
```

---

## Exception summary

| Field | Value |
|-------|--------|
| **Type** | `SyntaxError` |
| **File** | `desktop_app.py` |
| **Lines** | 3859 (primary), 4793 (secondary) |
| **Stage** | **Import / parse** — Python never executed `if __name__ == "__main__"` |

---

## Call stack (parse time)

1. Python loads `desktop_app.py` as module
2. Parser compiles function `_run_forge_build` → fails on invalid `global` placement
3. Process exits with code **1** before Flask, Socket.IO, or routers start

No runtime stack — failure is **static syntax**, not orchestration/router/memory/guardian init.

---

## Root cause

Godot install hotfix added `global _pending_godot_install` **after** assignments to `_pending_godot_install` in the same function scope.

Python requires `global` to appear **before** any use/assignment of that name in the function.

**Affected functions:**

- `_run_forge_build()` — `global` at 3825, duplicate `global` at 3859 after `_pending_godot_install = False` at 3840
- `api_chat()` — read `_pending_godot_install` at 4789, `global` at 4793 inside `if` block

---

## Audit of suspected systems (Step 2–5)

| Area | Startup impact |
|------|----------------|
| `workers/sentinel/capability_router.py` | Not reached (parse failed first) |
| `ModelRouter` | Not reached |
| Memory / Earn / Guardian integrations | Not reached |
| Socket registrations | Not reached |
| UI (orb.html) | N/A — Electron waits on Python |
| `FloatingConversationLayer` | Frontend only — not involved |

**Conclusion:** UI/router merge did not break Python imports; a **syntax error in forge/Godot chat paths** blocked the entire backend from loading.

---

## Step 3 — Startup stages (post-fix observation)

After fix, `python desktop_app.py` logs in order:

1. License load  
2. Socket.IO enabled  
3. Scalp routes, capability tools, learning memory, task queue  
4. Orchestration runtime, crash recovery, worker manager (3 workers)  
5. Watchdog, health monitor, RAG (optional deps warn only)  
6. Flask serving `http://127.0.0.1:5001`  
7. Memory Manager V2, tray icon — **SentinelAI is now running**

No crash at any stage.

---

## Step 6 — Safe mode

Not required for this incident: the process failed at **parse time**, before any subsystem could initialize. Subsystem safe-mode would not run.

Recommendation: run `python -m py_compile desktop_app.py` in CI or pre-launch script to catch `SyntaxError` before Electron starts.

---

## Validation (Step 7)

| Check | Result |
|-------|--------|
| `python -m py_compile desktop_app.py` | Pass |
| `python desktop_app.py` | Runs; listens on 5001 |
| API requests | `GET /api/workers/status` 200 |
| Backend log | "SentinelAI is now running" |

Electron should connect once this build is used; no backend restart loop from code=1.
