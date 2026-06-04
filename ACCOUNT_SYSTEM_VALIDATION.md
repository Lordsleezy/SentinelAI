# Account System Validation — Unified Auth + Billing + License

**Store:** `website/lib/account_store.js`  
**Schema:** `website/supabase/schema.sql` (production)  
**Dev fallback:** SQLite `sentinel_account.sqlite` (same tables, no split-brain)

## Design

When `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set → **Supabase** is the single source of truth.

Otherwise → **SQLite mirror** with identical tables for local dev and E2E (no separate `activation_codes.sqlite` for new flows).

Legacy `activation_codes` rows are still read for validate/activate compatibility during migration.

## Tables

| Table | Purpose |
|-------|---------|
| `profiles` | User identity (linked to Supabase Auth `id` in production) |
| `subscriptions` | Stripe subscription sync |
| `product_licenses` | Desktop license keys |
| `payment_history` | Purchases and renewals |
| `audit_logs` | Admin audit trail |

## Flows

| Flow | API | Status |
|------|-----|--------|
| Signup | `POST /api/auth/signup` | PASS (E2E) |
| Login | `POST /api/auth/login` | PASS (E2E) |
| Dashboard | `GET /api/dashboard?user_id=` | PASS (E2E) |
| Purchase → license | Stripe webhook → `createLicense` | Implemented |
| Desktop activate | `POST /api/activate` | PASS (E2E) |
| Desktop validate | `GET /api/validate` | PASS (E2E) |
| Password reset | Supabase Auth dashboard / future route | Use Supabase hosted reset in production |

## Pages

- `signup.html` — create account
- `login.html` — session stored in localStorage (`sentinel_user_id`)
- `dashboard.html` — licenses, subscriptions, payments
- `pricing.html` / `checkout.html` — linked to same `user_id` when logged in

## Production setup

1. Run `website/supabase/schema.sql` in Supabase SQL editor.
2. Enable Email auth in Supabase dashboard.
3. Set env vars on SentinelPrime deployment (see `website/.env.example`).
4. Point `https://sentinelprime.org/api/validate` (already used by desktop `license_manager`).

## Admin

Token-protected (`ADMIN_TOKEN`):

- `GET /api/admin/users`
- `GET /api/admin/subscriptions`
- `GET /api/admin/payments`
- `GET /api/admin/licenses`
- `GET /api/admin/audit`
- `POST /api/admin/grant-license`

## Split-brain removed

| Before | After |
|--------|-------|
| SQLite `activation_codes` only | Licenses in `product_licenses` + legacy read |
| No user accounts | Signup/login/dashboard |
| Purchase disconnected from profile | `user_id` on license + subscription |

## Validation result

**Automated E2E:** PASS (signup → login → dashboard → grant license → activate → validate)

**Supabase live:** Run schema + env on staging, repeat E2E against production URL.
