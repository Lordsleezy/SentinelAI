# Provider Onboarding Engine

**Module:** `core/sentinelvision/provider_onboarding/onboarding_engine.py`  
**Class:** `ProviderOnboardingEngine`

## Supported providers

Supabase, Stripe, GitHub, Cloudflare, Netlify, Resend, Google, Amazon.

## Capabilities

| Step | Behavior |
|------|----------|
| Detect missing config | `detect_missing()` → `ProviderWorkflowRunner.health_check()` |
| Guide setup | Submits onboarding goal; browser steps via planner |
| Store credentials | `AccountOperator.setup_account()` → vault (`vision:vault:`) |
| Verify connection | HTTP health checks in `providers/workflows.py` |
| Create playbook | Successful goals saved via `playbooks/recorder.py` |

## Example: “Set up Stripe”

1. User starts goal or `POST /api/sentinelvision/onboard` with `provider_id: stripe`.
2. Engine detects Stripe not connected (missing API keys / dashboard session).
3. Optional `fields` in POST body stored in vault (never returned in API).
4. `submit_goal("Set up Stripe", provider_id=stripe)` runs research → plan → execute.
5. Workflow steps create products/webhooks where planned; verification confirms API reachability.
6. Playbook written to `data/sentinelvision/workflows/playbook_stripe_*.json`.

## API

```http
POST /api/sentinelvision/onboard
Content-Type: application/json

{
  "provider_id": "stripe",
  "objective": "Set up Stripe",
  "fields": { "api_key": "sk_...", "webhook_secret": "whsec_..." }
}
```

Legacy route: `/api/sentinelscrub/onboard`.

## Template objectives

Defined in `TEMPLATE_OBJECTIVES` (e.g. `Connect Supabase`, `Configure Cloudflare`).  
`resolve_onboarding_objective(message)` maps natural language to a provider id.

## Wiring

`SentinelVisionEngine.onboarding` is constructed with the engine instance and shares vault, goals, and operators.
