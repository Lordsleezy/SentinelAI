# Builder Maturity Report

**Date:** 2026-06-02  
**Scope:** Sentinel Builder / Forge engine — outcome-based execution

---

## Vision Alignment

| Criteria | Required | Current |
|----------|----------|---------|
| Files generated | Step only | **Done** |
| Dependencies verified | Before build | **Done** (`CapabilityManager`) |
| Build completed | Compile/bundle where applicable | **Partial** (scaffold-heavy) |
| Launch attempted | Always for forge complete | **Done** (`launch_verifier`) |
| Launch verified | Required for `forge_complete.success` | **Done** (Godot path strong) |
| Self repair | On verify fail | **Done** (Aider/Python fallback) |
| User manual install | Never for Tier 1/2 | **Partial** (Node if missing on host) |

**Verdict:** Architecture direction is **correct**. Maturity is **~70%** for GAME, **~50%** for WEB/DESKTOP, **~30%** for ANDROID.

---

## Lifecycle Stage Matrix

| Stage | Implementation | Gap |
|-------|----------------|-----|
| 1 Planning | `route_build` / classify | None |
| 2 Dependency check | `capability_manager` | Validator fallthrough for unknown caps |
| 3 Dependency install | `runtime_installer` | Node/Android manual |
| 4 Generation | Template builders + OpenHands stub | LLM game quality limited |
| 5 Build | Logged stage; no real compile for GAME | Godot export not automated |
| 6 Verification | `verify_build` | WEB/DESKTOP structure-only |
| 7 Launch | `launch_verifier` + artifact | WEB 4s heuristic weak |
| 8 Self repair | Python/Aider | May not fix Godot projects |
| 9 Complete | Register + `forge_complete` | **Fixed** — no fake Launch Ready |

---

## Build Type Readiness

| Type | Generator | Launch | Auto-install |
|------|-----------|--------|--------------|
| GAME (Godot) | Template scaffold | Godot `--path` | Godot bundled/download |
| WEB (Next) | Scaffold | npm dev probe | npm/node Tier 1 |
| DESKTOP (Electron) | Scaffold | Electron launch | npm + electron |
| PYTHON | Aider | python entry | venv |
| ANDROID | Gradle scaffold | N/A | Tier 3 stub |

---

## Anti-Patterns Removed (recent)

- ✗ `VerificationResult(True, "...Godot binary not in PATH")`
- ✗ `forge_complete.success` without launch
- ✗ “Launch Ready” as user-facing completion

---

## Remaining Gaps (roadmap)

### P0 — Outcome fidelity

1. **WEB:** Real `npm run build` + health check URL before complete.
2. **DESKTOP:** `npm start` or `electron .` with process alive check.
3. **Launch repair loop:** On launch fail, one automated repair pass then re-launch (forge stage 8).

### P1 — Generation quality

4. Wire **Aider** for GAME when template insufficient (optional).
5. Complete or remove **OpenHands** from hot path.

### P2 — Platform

6. Godot **export** pipeline for distributable exe (not just editor open).
7. Android SDK Tier-2 bootstrap.

### P3 — UX

8. Tasks tab shows all 9 stages with timestamps.
9. Builder Status Center from `/api/capabilities/status` in orb Tasks panel.

---

## Validation Commands

```bash
python run_capability_validation.py
# Manual: Build Flappy Bird → APPROVE → Godot window opens
# Manual: Build calculator → Electron/npm path
```

---

## Conclusion

Continue the **existing** `ForgeBuildEngine` + capability system. Do not fork a second builder. Next engineering focus: **WEB/Electron launch verification** and **repair-on-launch-fail**.
