# Boot Failure — Root Cause & Fix

**Date:** 2026-06-02  
**Status:** Resolved (hotfix applied)

---

## Root cause

**`SyntaxError` in `desktop_app.py`** — invalid placement of `global _pending_godot_install` in forge launch and chat handlers introduced during the Godot install / capability work.

Python exits with **code 1** while **importing** the module, so Electron sees immediate crash → restart loop → splash hang.

This is **not** a failure of SentinelCapabilityRouter, ModelRouter, memory sync, Guardian, Earn, or UI merge code.

---

## Files changed

| File | Change |
|------|--------|
| `desktop_app.py` | `_run_forge_build`: `global _pending_godot_install` at function top; removed duplicate `global` before nested `if` |
| `desktop_app.py` | `api_chat`: `global _pending_godot_install` at function top (before read at line ~4789) |

---

## Fix implemented

```python
# _run_forge_build — top of function
global _pending_godot_install

# api_chat — top of function (before _godot_confirm read)
global _pending_godot_install
```

Removed redundant second `global _pending_godot_install` inside `_run_forge_build` failure branch (was line 3859).

---

## Validation performed

1. `python -m py_compile desktop_app.py` → exit 0  
2. `python desktop_app.py` → backend starts, binds `127.0.0.1:5001`  
3. Log line: `SentinelAI is now running. Check system tray for controls.`  
4. HTTP `GET /api/workers/status` → 200  
5. No `SyntaxError` on startup  

**User verification:** Restart Sentinel from Electron; splash should clear when backend is healthy.

---

## Prevention

- Pre-flight: `python -m py_compile desktop_app.py` before packaging or Electron launch  
- Avoid `global` mid-function after assignments; declare once at function entry  
- See also: `STARTUP_FAILURE_REPORT.md` (full traceback and stage audit)

---

## Success criteria

| Criterion | Met |
|-----------|-----|
| Sentinel launches | Yes (Python backend) |
| No code=1 on import | Yes |
| No restart loop from syntax | Yes |
| Backend healthy | Yes |
| Feature work paused | Per emergency directive — resume only after user confirms Electron boot |
