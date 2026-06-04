# Repair Memory (Phase 2B)

**Database:** `data/sentinelscrub/repair_memory.db`  
**Module:** `core/sentinelscrub/self_correction/repair_memory.py`

## Schema

| Column | Description |
|--------|-------------|
| provider | Provider id (supabase, netlify, stripe, …) |
| failure_signature | Normalized error snippet |
| root_cause | Failure class / cause label |
| repair_action | Action Sentinel applied |
| success_count / fail_count | Outcomes |
| success_rate | Rolling success ratio |
| last_used | ISO timestamp |

## Seeded patterns (real)

| Provider | Signature | Repair action |
|----------|-----------|---------------|
| supabase | policy already exists | DROP POLICY IF EXISTS … |
| supabase | relation does not exist | CREATE TABLE / migration |
| netlify | missing env | netlify env:set / dashboard |
| stripe | webhook | Create webhook endpoint |
| cloudflare | dns | Add DNS record |
| github | repository not found | Fix token / create repo |
| browser | playwright | pip install playwright |

## Lookup

`RepairMemoryStore.find_repair(provider_id, signature, failure_class)`  
Returns best match when score ≥ 0.45.

## Learning loop

After each repair attempt: `record_outcome(..., success=True|False)`  
Success rate updates — future failures search memory **before** web research.

## API

`GET /api/sentinelscrub/repair-memory` — top patterns for Settings/diagnostics.
