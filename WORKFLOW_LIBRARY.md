# Workflow Library

**Module:** `core/sentinelvision/workflows/workflow_library.py`  
**Storage:** `data/sentinelvision/workflows/` (JSON playbooks)  
**Recorder:** `core/sentinelvision/playbooks/recorder.py`

## Built-in templates

| ID | Objective | Provider |
|----|-----------|----------|
| `connect_supabase` | Connect Supabase | supabase |
| `connect_stripe` | Set up Stripe | stripe |
| `connect_netlify` | Connect Netlify | netlify |
| `deploy_sentinel` | Deploy Sentinel AI | netlify |
| `create_github_repo` | Create GitHub Repo | github |
| `configure_cloudflare` | Configure Cloudflare | cloudflare |
| `connect_resend` | Connect Resend | resend |
| `connect_google` | Connect Google | google |
| `connect_amazon` | Connect Amazon | amazon |

## Behavior

- **Templates** — `WorkflowLibrary.list_templates()` marks each template with `has_playbook` if a saved JSON exists.
- **Saved runs** — Successful goals call `save_playbook()`; files named `playbook_{provider}_{slug}.json`.
- **Reuse** — `SentinelVisionEngine._pipeline_once` loads matching playbook on attempt 0 (skips re-research when present).
- **Legacy paths** — Also scans `data/sentinelvision/playbooks/` and `data/sentinelscrub/playbooks/`.

## API

```http
GET /api/sentinelvision/workflows
```

Returns `{ "workflows": [ { "id", "objective", "provider_id", "has_playbook", "saved" }, ... ] }`.

Playbooks listing (same files):

```http
GET /api/sentinelvision/playbooks
```

## Natural language

`WorkflowLibrary.resolve_template(message)` and onboarding `resolve_onboarding_objective()` map user phrases like “Connect Sentinel AI to Supabase” to the closest template.

## Long-term goal

User utterance → research → plan → execute → verify → repair → complete, with approvals only for purchases and sensitive account actions. Templates accumulate from every successful run.
