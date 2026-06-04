# Sentinel AI — Release Audit Report

**Audit date:** 2026-06-02  
**Target version:** `1.0.0-beta.1`  
**Scope:** Full codebase RC audit (Phases 1–14)

---

## Executive summary

Sentinel AI is **approaching beta readiness** for a technical preview distributed via GitHub Releases and SentinelPrime.org. Core desktop subsystems (Vision, Memory 2.0, Missions, Guardian monitor, Auto-updater, Licensing, Dependency/Model managers) compile, import, and pass automated RC validation.

**Launch blockers (must fix before public beta):**

1. Produce and upload **`SentinelAISetup.exe`** (installer pipeline not verified in this audit).
2. Generate **`build_info.py`** on every release build (`scripts/generate_build_info.ps1 -BuildType beta -Version 1.0.0-beta.1`).
3. **Supabase auth backend missing** — Phase 5 requirements (signup, profiles, subscriptions tables) are **not implemented** in this repository.
4. **Stripe subscriptions** — website supports one-time PaymentIntent + webhook; monthly/annual/lifetime Checkout flows not implemented.
5. **End-to-end purchase → install** requires live Stripe, SMTP, and deployed `website/` — not validated live in CI.

---

## Phase 1 — Full system audit

### Imports and startup

| Check | Result |
|-------|--------|
| `desktop_app.py` py_compile | PASS |
| Subsystem imports (memory2, missions, vision, updater, deps, models) | PASS |
| Documented boot SyntaxError (`global _pending_godot_install`) | FIXED per prior reports — re-verify on branch |
| Non-fatal subsystem init | PASS pattern — failures log warnings |

**Top-level imports:** Flask, workers, orchestration, memory v1/v2, licensing, guardian paths. Heavy optional: chromadb, langgraph, crewai — degrade if missing.

### Dependencies (`requirements.txt`)

- **Present:** playwright, httpx, psutil, ollama client, cryptography, flask-socketio
- **Missing for product spec:** `stripe` (Python), `supabase` (Python) — intentional; website uses Node `stripe`; Vision uses httpx REST
- **Risk:** Full `pip install -r requirements.txt` on Windows may require build tools for native wheels

### APIs (desktop `:5001`)

| Domain | Routes | Status |
|--------|--------|--------|
| Memory 2.0 | `/api/memory2/*` | Implemented |
| Missions | `/api/missions/*` | Implemented |
| Guardian monitor | `/api/guardian/dashboard`, `/alerts` | Implemented |
| Vision | `/api/sentinelvision/*` + scrub aliases | Implemented |
| Updates | `/api/updates/*`, `/api/version` | Implemented |
| License | `/license/*`, `/api/trial/status` | Implemented |
| Dependencies | `/api/dependencies/*` | Implemented (RC) |
| Models | `/api/models/*` | Implemented (RC) |
| Onboarding | `/api/onboarding/*` | Implemented (RC) |
| Stripe/Supabase (Flask) | None dedicated | BY DESIGN — Vision provider health only |

### Authentication

- Desktop: license key + machine_id → `sentinelprime.org/api/validate` (and local `/license/activate`)
- Website: SQLite `activation_codes` — **not** Supabase Auth
- No JWT session store in desktop app

### Licensing

- Remote validation, grace period, offline cache, beta expiration, restricted mode
- **No file deletion** on expiry — verified in code paths
- Killswitch: `workers/licensing/killswitch_checker.py` → remote API

### Security concerns

| Risk | Severity | Mitigation |
|------|----------|------------|
| License API trust | Medium | HTTPS only; offline grace bounded |
| Website admin token | Medium | Requires `ADMIN_TOKEN` env |
| Vault secrets in process | Medium | Never returned in list APIs |
| Guardian offensive tools | High | Approval gates + trusted targets |
| Raw Stripe webhook | Medium | Requires `STRIPE_WEBHOOK_SECRET` |

### Stale references

- Docs still mention `core/sentinelscrub/` paths — use `core/sentinelvision/`
- `sentinelscrub` compat shim only: `core/sentinelscrub/__init__.py`
- Root `artifact_registry.py` deleted — use `workers/artifacts/artifact_registry.py`

---

## Phase 2 — Dependency manager

**Module:** `core/dependency_manager/engine.py`  
**UI:** Settings → Downloads  
**State:** `data/dependencies/state.json`

| Component | Auto-install | Notes |
|-----------|--------------|-------|
| python_runtime | Detect | — |
| playwright + chromium | Yes | pip + `playwright install` |
| ollama | **Manual** | Opens ollama.com — Windows installer required |
| guardian_tools | Yes | bootstrap_manager |
| vision_stack | Partial | Playwright + optional OCR pip |
| builder_godot | On demand | godot_runtime |
| update_service | Yes | httpx |

**Gaps:** Resume interrupted downloads not byte-level (re-run install). Node/Electron not auto-installed inside Python manager (Electron installer bundle separate).

---

## Phase 3 — Model manager

**Module:** `core/model_manager/engine.py`  
**Policy:** Installs only recommended **Llama** + **Dolphin** (not full catalog).  
**Additional models:** Settings → Models (existing routes) + `/api/models/pull|remove`

---

## Phase 4 — First launch wizard

| Surface | Status |
|---------|--------|
| Electron `desktop-shell/setup_wizard.html` | Exists |
| Python `core/onboarding/first_launch.py` | RC — API steps |
| Completion state | `data/onboarding/first_launch.json` |

**Gap:** Electron wizard and Python orchestrator should be wired to same API (`/api/onboarding/step`) — integration test recommended.

---

## Phase 5 — Supabase validation

**Result: NOT IMPLEMENTED in repository**

Expected tables (`profiles`, `subscriptions`, `activation_codes`, `product_licenses`, `payment_history`) — **not found**. Website uses SQLite for activation codes only.

**Action for launch:** Either implement Supabase backend on SentinelPrime or **descope** beta to license-key + SQLite flow and document in marketing.

---

## Phase 6 — Stripe validation

**Website:** `website/server.js`

| Flow | Status |
|------|--------|
| PaymentIntent checkout | Implemented |
| Webhook → activation code email | Implemented (needs SMTP) |
| Monthly / Annual / Lifetime | **NOT IMPLEMENTED** |
| Subscription sync | **NOT IMPLEMENTED** |

**Action:** Extend `server.js` with Stripe Checkout sessions + Customer Portal or document one-time Pro only for beta.

---

## Phase 7 — Licensing

| Check | Status |
|-------|--------|
| Activation code generation | Website SQLite |
| Desktop activate | `/license/activate` |
| Remote validate | `sentinelprime.org` |
| Offline grace | 7 days Pro |
| Beta expiration / restricted | Implemented |
| Restart persistence | `~/.sentinelai/license.json` |

---

## Phase 8 — Auto-updater

| Check | Status |
|-------|--------|
| GitHub Releases API | Implemented |
| beta / stable channels | Implemented |
| Background download | Implemented |
| SHA-256 verify | Implemented (release notes / sidecar) |
| Rollback metadata | Implemented |
| Apply in-app | **Restart + manual installer** — OS-specific |

---

## Phase 9 — Guardian

| Check | Status |
|-------|--------|
| psutil CPU/RAM/disk/network | PASS |
| Process top-N | PASS |
| Service probe :5001 | PASS |
| Fake telemetry | None detected |
| Offensive scan tools | Separate from monitor — requires Playwright/tools |

---

## Phase 10 — Missions

| Check | Status |
|-------|--------|
| SQLite persistence | PASS |
| Vision attach | Implemented in `engine.py` |
| Progress / blockers | PASS |

---

## Phase 11 — Vision

| Check | Status |
|-------|--------|
| Pipeline research/plan/execute/verify/repair | Implemented |
| Provider onboarding engine | Implemented |
| Workflow library | Implemented |
| OCR fallback | In `smart_click` |
| Live E2E Connect Supabase/Stripe | Requires Playwright + credentials — manual QA |

---

## Phase 12 — Beta download portal

| Item | Status |
|------|--------|
| pricing.html, download.html | Present |
| `/api/beta/release` | Added RC |
| Beta section on download page | Added RC |
| SentinelAISetup.exe link | **Placeholder** until CI artifact |

---

## Phase 13 — Admin dashboard

| Item | Status |
|------|--------|
| Full admin UI | **NOT IN REPO** |
| API stubs | `GET /api/admin/users`, `/audit`, `POST /grant-license` with `ADMIN_TOKEN` |

**Action:** Build admin SPA or use protected routes + Retool for beta ops.

---

## Phase 14 — End-to-end test

**Cannot fully automate without live Stripe, SMTP, Supabase, and installer artifact.**

Recommended manual script in `BETA_TESTER_GUIDE.md`.

---

## Warnings (non-blocking)

- Version `0.0.0` if `build_info.py` not generated
- ChromaDB / sentence-transformers optional weight
- Dual memory systems (v1 hot/warm + memory2) — operational overlap
- Electron requires `venv\Scripts\python.exe`
- Guardian findings DB v3 + legacy paths
- Documentation drift (SentinelScrub naming)

---

## Validation commands

```powershell
.\scripts\generate_build_info.ps1 -BuildType beta -Version 1.0.0-beta.1
python run_beta_validation.py
python run_rc_validation.py
python -m py_compile desktop_app.py
```

Results written to `data/release/rc_validation.json`.

---

## Release risks summary

| Risk | Impact |
|------|--------|
| No installer EXE | Beta users cannot one-click install |
| Supabase/Stripe spec mismatch | Marketing vs implementation gap |
| Ollama manual step | Support burden |
| Network dependency for license | Offline beta limited |
| Large dependency install time | First-run abandonment |

**Audit completed:** All in-repo subsystems inspected; failures documented above.
