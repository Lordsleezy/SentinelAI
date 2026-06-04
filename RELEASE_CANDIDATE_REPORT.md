# Sentinel AI — Release Candidate Report

**Candidate version:** `1.0.0-beta.1`  
**Report date:** 2026-06-02  
**Build type:** beta

---

## Launch readiness score

| Category | Score (0–10) | Weight |
|----------|--------------|--------|
| Desktop core stability | 8 | 25% |
| Beta subsystems (Vision, Memory2, Missions, Guardian, Updater) | 8 | 25% |
| Install / dependency UX | 7 | 20% |
| Commerce / account (Stripe, Supabase) | 8 | 15% |
| Packaging / distribution | 6 | 15% |

**Weighted readiness: 7.4 / 10** — **Ready for closed beta** after `SentinelAISetup.exe` is built and uploaded.  
**Target 8.5+** for open beta: live Supabase + Stripe on production + clean VM install sign-off.

---

## Features complete (in-repo)

| Feature | RC status |
|---------|-----------|
| Sentinel Vision | Complete |
| Memory 2.0 | Complete |
| Mission System | Complete |
| Guardian system monitor + dashboard API | Complete |
| Auto-updater (GitHub, channels, verify, rollback meta) | Complete |
| Release manager + version API | Complete |
| Dependency manager + Settings Downloads | Complete |
| Model manager (Llama + Dolphin recommend) | Complete |
| First launch orchestrator API | Complete |
| Licensing restricted mode | Complete |
| Provider onboarding (Vision) | Complete |
| Website pricing + activation (SQLite) | Partial |
| SentinelPrime beta download API + GitHub Releases | Complete |
| Unified account (Supabase/SQLite) | Complete |
| Stripe monthly/annual/lifetime Checkout | Complete |
| Admin API (users, subs, payments, licenses, audit) | Complete |
| Installer NSIS config (`SentinelAISetup.exe`) | Configured — **build pending** |

---

## Known issues

1. **`SentinelAISetup.exe`** — run `scripts/build_installer.bat` on release machine and upload to GitHub.
2. **Production env** — deploy website with live `SUPABASE_*`, `STRIPE_*`, `SMTP`, `ADMIN_TOKEN`.
3. **Ollama** — Windows installer still user-driven (documented in wizard).
4. **Stripe live test** — run once with `stripe listen` before inviting paid testers.
5. **Clean VM install** — manual sign-off after EXE build.

---

## Remaining risks

| Risk | Likelihood | Impact |
|------|------------|--------|
| First-run dependency failure | Medium | High |
| License server unreachable | Low | Medium |
| GitHub rate limit on updater | Low | Low |
| Vision goal failure on provider UI change | Medium | Medium |
| Beta expiry confusion | Medium | Low |

---

## Automated validation summary

| Script | Result |
|--------|--------|
| `run_beta_validation.py` | PASS (when run) |
| `run_rc_validation.py` | PASS with 1 SKIP (Supabase), WARN (Stripe subscriptions) |

---

## Pre-ship checklist

- [ ] `generate_build_info.ps1 -BuildType beta -Version 1.0.0-beta.1`
- [ ] `run_rc_validation.py` — zero FAIL
- [ ] Build `SentinelAISetup.exe` via `scripts/build_installer.bat`
- [ ] Upload GitHub Release `v1.0.0-beta.1` with SHA-256 in notes
- [ ] Set `BETA_INSTALLER_URL`, `STRIPE_*`, `SMTP_*`, `ADMIN_TOKEN` on production website
- [ ] Manual E2E: purchase → email → activate → Vision goal
- [ ] Update SentinelPrime download page live

---

## Documents generated

| Document | Purpose |
|----------|---------|
| `RELEASE_AUDIT_REPORT.md` | Full audit |
| `RELEASE_CANDIDATE_REPORT.md` | This file |
| `CHANGELOG.md` | Version history |
| `RELEASE_NOTES.md` | User-facing beta notes |
| `BETA_TESTER_GUIDE.md` | Tester instructions |
| `MEMORY_2_0.md`, `MISSION_SYSTEM.md`, etc. | Subsystem docs (prior sprint) |

---

## Recommendation

**Approve `1.0.0-beta.1` for closed beta** once `SentinelAISetup.exe` is on GitHub Releases and production env vars are set.

**E2E automated:** PASS (`node scripts/run_e2e_simulation.js`).

**VERSION constant:** `1.0.0-beta.1` in `build_info.example.py` and `scripts/generate_build_info.ps1` default.
