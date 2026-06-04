# Provider Workflows (Phase 2D / 2F)

**Module:** `core/sentinelscrub/providers/workflows.py`

## Real operations (not placeholders)

### Supabase
- `supabase_check_env` — vault + env for URL/keys  
- `supabase_verify_rest` — HTTP GET `{SUPABASE_URL}/rest/v1/` with apikey  
- Autonomous verify: env + REST reachable  

### Stripe
- `stripe_verify_api` — GET `api.stripe.com/v1/balance`  
- `stripe_list_webhooks` — count webhook endpoints  
- Autonomous verify: API key + webhooks (if objective mentions webhooks)  

### Netlify
- `netlify_verify_token` — GET `api.netlify.com/api/v1/sites`  
- `netlify_deploy_check` — `netlify status` CLI  
- Autonomous verify: auth token  

### GitHub
- `github_verify_token` — GET `api.github.com/user`  

### Amazon
- `amazon_search` — Playwright open search URL  
- `purchase` — blocked until approval gate  
- Autonomous verify: receipt / order id in context  

### Health checks (Phase 2E)
`GET /api/sentinelscrub/providers/health` — per-provider `connected` flag for Settings UI.

## Planner integration

`ScrubPlanner._default_steps()` emits workflow `action_type` values per provider.

## Execution path

`SentinelScrubEngine._execute_step` → `ProviderWorkflowRunner.execute_step` first, then browser/desktop fallback.

## Autonomous testing (2F)

`VerificationEngine.verify_goal(..., autonomous=True)` → `verify_autonomous()` with multi-check `checks[]` array.  
**Task not complete** until all checks pass.

## Multi-step (2G)

`decompose_objective()` — e.g. "Launch Sentinel AI" → 10 ordered sub-goals (GitHub → Supabase → Stripe → …).  
Parent goal tracks completion of entire chain.

## Shopping (2H)

Amazon plan: search → compare → approval → checkout → receipt → verify.  
Purchases always require `ApprovalGate`.

## Playbooks (2I)

On success: `data/sentinelscrub/playbooks/playbook_{provider}_{slug}.json`  
Next run reuses plan when playbook exists.
