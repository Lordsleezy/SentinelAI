# UI Debug Elements Removed

**Date:** 2026-06-02  
**File:** `desktop-shell/orb.html`  
**Scope:** Visual cleanup only — no backend, routing, or worker changes.

---

## Problem

The main screen showed internal implementation details above **STATUS: ONLINE**:

- `intent:repair`, `intent:search`, `intent:monitor`
- `repair_worker_1`, `repair_worker_2`, `forge_worker_1`

These came from `#status-line`, filled every 3s by `updateWorkerStatus()` calling `GET /api/workers/status` and rendering `.worker-badge` chips.

---

## Removed from main UI

| Element | Action |
|---------|--------|
| `#status-line` container | Deleted from HTML |
| `#status-line` CSS (margin, flex row) | Removed |
| Worker/intent badges on home screen | No longer rendered |
| Theme override for `#status-line` | Removed |
| `status_msg` on consultation flow | Routed to chat via `showChatResponse()` instead of status line |

**Layout after cleanup:**

```
[ Input field ] [ Send ]
STATUS: ONLINE
💬 CHAT | ⚙
```

---

## Preserved (unchanged behavior)

| Behavior | How |
|----------|-----|
| Worker polling | `setInterval(updateWorkerStatus, 3000)` still runs |
| `/api/workers/status` | Same fetch; data stored in `window._workerDiagnosticsCache` |
| Intent routing | Backend / orchestrator — untouched |
| Task execution | Unchanged |
| `openWorker()` / IPC | Unchanged |

---

## Optional location (implemented)

**Settings → Advanced → Diagnostics**

- Tab alongside Market / Scalp
- Shows worker IDs, intents, and states
- **Refresh** button re-fetches status
- Hidden during normal use

`.worker-badge` styles are scoped to `#diagnostics-workers-panel` only.

---

## Success criteria

- [x] No intent chips on main screen
- [x] No worker chips on main screen
- [x] No routing labels on main screen
- [x] No empty row where status-line was
- [x] Backend functionality unchanged
- [x] Diagnostics available under Settings → Advanced

---

## Verification

1. Launch Sentinel orb UI.
2. Confirm no badge row between input and **STATUS: ONLINE**.
3. Open **Settings → Advanced → Diagnostics** — worker/intent list appears.
4. Send a chat message — routing still works; no chips reappear on home screen.
