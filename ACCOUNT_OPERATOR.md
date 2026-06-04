# Account Operator

**Module:** `core/sentinelvision/operator/account_operator.py`  
**Class:** `AccountOperator`

## Capabilities

| Method | Purpose |
|--------|---------|
| `login(provider_id, operators)` | Open provider login URL; `smart_fill` / `smart_click` using vault creds (in-process only) |
| `logout(provider_id, operators)` | Audit logout; session cleared in browser context |
| `setup_account(provider_id, fields, label)` | Register encrypted fields in `AccountVault` |
| `configure_environment(provider_id, env_vars)` | Set `os.environ` for deploy helpers (keys listed in audit, not values) |
| `rotate_credential(provider_id, field, new_value)` | Update single vault field |
| `connection_status(provider_id)` | Delegate to workflow health check |

## Security

- Credentials read via `AccountVault.get_credentials()` — **never** serialized to chat or REST list endpoints.
- Vault keys: `vision:vault:{provider}:{field}` (legacy `scrub:vault:` still readable).
- All mutations audited via `audit_log()`.

## Provider login URLs

Built-in map for Amazon, Stripe, GitHub, Supabase, Netlify, Cloudflare, Google, Resend; others fall back to `https://{provider}.com/login`.

## Usage from goals

Planner steps with `action_type` browser_navigate + provider plugins can call account flows. Onboarding engine uses `setup_account` before verification.

## Requirements

- Playwright for interactive login flows.
- SecretsStore (`sentinel_security.secrets_store`) for persistence.
