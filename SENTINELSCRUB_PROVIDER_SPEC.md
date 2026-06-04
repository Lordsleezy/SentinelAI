# SentinelScrub Provider Spec

## Interface (`ProviderBase`)

Every provider implements:

| Method | Purpose |
|--------|---------|
| `research(objective)` | Structured requirements: actions, env vars, docs |
| `login(vault_secrets)` | Authenticate using vault (in-process only) |
| `execute(step, operators)` | Run one plan step with browser/desktop bundle |
| `verify(objective, context)` | Confirm outcome (env vars, API state, etc.) |
| `repair(failure, context)` | Optional repair plan steps |
| `match_objective(objective)` | 0–1 confidence score for auto-routing |

## Registered providers (v1)

| ID | Display | Keywords |
|----|---------|----------|
| `amazon` | Amazon | buy, order, purchase |
| `supabase` | Supabase | supabase, postgres |
| `stripe` | Stripe | stripe, payment, billing |
| `cloudflare` | Cloudflare | cloudflare, dns, domain |
| `github` | GitHub | github, repo, deploy |
| `netlify` | Netlify | netlify, deploy |
| `google` | Google | google, workspace |
| `resend` | Resend | resend, email |

## Adding a provider

1. Create `core/sentinelscrub/providers/my_provider.py` subclassing `ProviderBase`.
2. Register in `providers/registry.py` `_register()` list.
3. Implement `research()` with real `required_actions` and `environment_variables`.
4. Implement `verify()` with measurable checks.
5. Implement `execute()` only where automation is real (Playwright/API/CLI).

**Do not** register mock executors that return success without work.

## Resolution

`resolve_provider(objective)` picks highest `match_objective` score if ≥ 0.3.

Override with explicit `provider_id` in `POST /api/sentinelscrub/goals`.

## Shopping workflow (Amazon)

1. Research → search/filter/compare steps in plan  
2. Sensitive steps → `purchase` action type → approval gate  
3. After approval → browser session + checkout (Playwright required)  
4. Receipt stored as artifact (roadmap: artifact registry link)
