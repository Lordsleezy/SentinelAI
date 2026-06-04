# SentinelScrub Security Model

## Principles

1. **Credentials never in chat** — vault API returns metadata only (`fields_configured`, never values).
2. **Encrypted at rest** — `AccountVault` uses `sentinel_security.secrets_store.SecretsStore` (Windows DPAPI or PBKDF2+AES-GCM).
3. **Encrypted in memory** — secrets loaded only inside backend process for operator use.
4. **Audit everything** — `audit.jsonl` records events; secret field names only, never values.
5. **Role-based access** — vault read roles: `operator`, `admin`, `read_metadata` (extend for multi-user later).

## Vault key format

```
scrub:vault:{provider_id}:{field_name}
scrub:vault:{provider_id}:__meta__
```

## Sensitive actions (require approval)

Defined in `types.SENSITIVE_ACTION_TYPES`:

- `purchase`, `payment`, `account_create`, `subscription`, `credential_change`, `financial`

## Forbidden without approval

- Financial transactions  
- Purchases  
- Account deletions  
- Credential changes  

## Trusted providers

User may opt in to “always approve” per provider via approval resolve `trust_provider: true` (stored in-memory per session; persist roadmap).

## Logging

- All vault writes: `vault_field_set` (field name only)  
- All goals: `goal_created`, `goal_status`, `goal_completed`  
- Repairs: `repair_attempt`  
- Approvals: `approval_requested`, `approval_resolved`

## Reversibility

- Desktop file ops: copy-based where possible  
- Browser: no destructive auto-actions without approval  
- Audit trail supports manual rollback investigation

## Boot safety

SentinelScrub init wrapped in try/except — **subsystem failure does not crash Sentinel**.
