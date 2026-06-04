# Memory Sync Audit

**Date:** 2026-06-02  
**Scope:** Claude/ChatGPT login, session persistence, extraction, indexing

---

## Flow Map

| Step | Module | Status |
|------|--------|--------|
| Save credentials | `workers/identity/identity_manager.py` | **Works** — Fernet encrypted `~/.sentinelai/identity.enc` |
| Connect API | `desktop_app.py` `/api/login/connect/*` | **Works** — background Playwright login |
| Browser session | `workers/identity/browser_sessions.py` + `stealth_browser.py` | **Partial** — persistent profile; selectors fragile |
| Sync scheduler | `conversation_sync.py` | **Works** — 60m + manual `/sync/trigger` |
| Extract metadata | `_extract_claude_async` / `_extract_chatgpt_async` | **Partial** — titles/URLs only, **no message bodies** |
| Vault JSON | `memory/vault/conversations/*.json` | **Works** |
| Index Memory V2 | `_process_into_memory` → `process_conversation` | **Fixed** — was broken legacy call |
| UI status | `/api/memory/sync/diagnostics` | **Implemented** — honest states + counts |

---

## State Machine (UI)

| State | Meaning |
|-------|---------|
| OFFLINE | No credentials / no session |
| AUTHENTICATING | Login thread running (UI manual connect) |
| AUTHENTICATED | Browser session valid, not yet imported to MemV2 |
| IMPORTING | Conversation JSON saved to vault |
| SYNCING | `sync_all` in progress |
| SYNCED | Memories indexed in V2 + last_sync set |
| FAILED | Login or sync error |

**Connected ≠ Synced** — UI now shows separate authenticated flag, imported conversation count, memory_count, last_sync.

---

## Cookie / Session Persistence

- Profile dir: `~/.sentinelai/browser_data/`
- In-memory `claude_logged_in` flags reset on restart until `startup_login()` runs
- **Gap:** Consultation uses SentinelWeb (`localhost:8766`), not browser session

---

## Broken / Missing (unchanged)

| Item | Severity |
|------|----------|
| Message body extraction from Claude/ChatGPT | High — sync metadata only |
| Unified federation memory merge index | Missing |
| `thread_manager.py` | Unwired |
| Health `claude_reachable` vs browser login | Misleading (documented in AI_FEDERATION_AUDIT) |

---

## Fixes Applied This Sprint

1. `conversation_sync._process_into_memory` → Memory V2 first.
2. `GET /api/memory/sync/diagnostics` — provider breakdown.
3. Memory panel — provider cards, “View sync status”, no false “Connected ✓” without import counts.
4. Socket event `memory_sync_state` during sync (optional UI hook).

---

## Recommended Next Steps

1. Extract message bodies in Playwright extractors → `process_conversation`.
2. Emit AUTHENTICATING during `/api/login/connect/*` background thread.
3. Wire `memory_sync_state` listener in orb Memory panel for live SYNCING indicator.
