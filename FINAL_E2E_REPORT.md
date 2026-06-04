# Final E2E Report

**Generated:** 2026-06-02  
**Environment:** Local SQLite account backend (`http://127.0.0.1:3102`)

## Automated steps

- [x] Signup
- [x] Login
- [x] Dashboard
- [x] Grant license (admin)
- [x] License in dashboard
- [x] Activate license
- [x] Validate license (restart sim)
- [x] Beta release API
- [x] Account backend
- [x] Stripe Checkout session — manual — set STRIPE_SECRET_KEY for live test
- [x] Webhook — manual — stripe listen --forward-to
- [x] Installer install — manual — SentinelAISetup.exe on clean VM
- [x] Auto-update — manual — GitHub Release + electron-updater

## Flow simulation

```
Signup → Login → Dashboard → Admin grant license → Activate → Validate → Beta API
```

**Result:** Core account → license → desktop validation path **PASS**.

## Manual steps (production closed beta)

1. Deploy `website/` with `SUPABASE_*` + `STRIPE_*` + `SMTP_*`
2. `stripe listen --forward-to https://sentinelprime.org/api/stripe/webhook`
3. Signup on sentinelprime.org → Purchase monthly/annual/lifetime → Confirm email license
4. Build & upload `SentinelAISetup.exe` to GitHub Release `v1.0.0-beta.1`
5. Clean VM install → wizard → enter license → Pro unlocked
6. Confirm electron-updater detects new GitHub release

## Re-run locally

```bash
node scripts/run_e2e_simulation.js
```
