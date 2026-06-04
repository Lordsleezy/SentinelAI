# Memory 2.0

**Module:** `core/memory2/engine.py`  
**Database:** `data/memory2/memory.db`  
**API:** `/api/memory2/*`

## Memory types

| Type | Purpose |
|------|---------|
| `long_term` | Durable facts and decisions |
| `project` | Per-project context (bridged from `memory/vault/projects/`) |
| `workflow` | Successful automation patterns (Vision + playbooks) |
| `repair` | Failure/repair signatures (bridged from `repair_memory.db`) |
| `preference` | User preferences and settings |

## Operations

- **Retrieval** — `POST /api/memory2/retrieve` with `query`, optional `memory_type`, `project_id`
- **Summarization** — `GET /api/memory2/summarize?memory_type=`
- **Consolidation** — `POST /api/memory2/consolidate` (dedupe by key)
- **Cleanup** — `POST /api/memory2/cleanup` with optional `dry_run`

## Health metrics

`GET /api/memory2/health` returns per-type counts, DB size, and last snapshot.

## Persistence

All entries survive restarts in SQLite. Startup bridges legacy JSON/SQLite sources once.

## Integration

- Hot/warm/cold pipeline remains in `workers/memory/memory_manager_v2.py`
- Memory 2.0 is the **unified query and health layer** for beta missions and Vision outcomes
