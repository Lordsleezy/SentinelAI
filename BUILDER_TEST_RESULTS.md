# Builder Test Results

**Date:** 2026-06-02  
**Command:** `python run_builder_tests.py`  
**Result:** 18/18 PASSED

## Tests

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | Router classifications (5) | PASS | GAME, DESKTOP, WEB, ANDROID, PYTHON |
| 2 | Build calculator | PASS | Electron scaffold, verified |
| 3 | Build Flappy Bird | PASS | Godot `project.godot`, not Tkinter |
| 4 | Build website | PASS | Next.js `app/page.tsx` |
| 5 | Build Android app | PASS | Gradle + Compose scaffold |
| 6 | Artifact + launch metadata | PASS | `builder_used`, launch command |
| 7 | Verification detects broken Godot | PASS | Missing `project.godot` → failed |

## Limitations

- Tests validate **scaffold generation** and verification logic, not full `npm install`, `godot` runtime, or `gradlew assembleDebug` on CI machines without those tools installed.
- Aider fallback is exercised when primary builder returns `success=False`; repair path not timed in this suite (would require mocking Aider).

## Manual validation

1. Restart Sentinel on `feature/specialized-builders`
2. Chat: `Build Flappy Bird` → APPROVE → Log shows `[BUILDER] Route: GAME`
3. Chat: `launch it` → uses Godot launch command from artifact
