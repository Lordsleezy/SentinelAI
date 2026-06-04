# SentinelScrub Architecture

**Subsystem path:** `core/sentinelscrub/`  
**UI:** Settings → **SentinelScrub**  
**API prefix:** `/api/sentinelscrub/*`

---

## Purpose

SentinelScrub turns Sentinel from a passive assistant into an **active digital operator** that completes multi-step goals across browser, desktop, accounts, and cloud providers — with research, planning, verification, and repair.

---

## Module layout

```
core/sentinelscrub/
├── engine.py              # Orchestrator: full goal pipeline
├── goal_engine.py         # SQLite goals + execution feed
├── audit.py               # Append-only audit log (no secrets)
├── types.py               # GoalStatus, Plan, Approval types
├── planner/
│   ├── research.py        # HTTP/docs/provider research
│   └── planner.py         # Research → ExecutionPlan
├── operator/
│   ├── browser/           # Playwright BrowserOperator
│   └── desktop/           # DesktopOperator (subprocess + optional pyautogui)
├── vault/
│   └── account_vault.py   # Encrypted provider credentials (SecretsStore)
├── memory/
│   └── scrub_memory.py    # Workflow + preference reuse
├── verification/
│   └── verifier.py        # Post-task verification
├── repair/
│   └── repair_engine.py   # Failure analysis + retry limits
├── approval/
│   └── approval_gate.py   # Sensitive action gate
└── providers/
    ├── base.py            # Provider interface
    ├── registry.py        # Amazon, Supabase, Stripe, …
    └── *_provider.py
```

---

## Goal pipeline

```
Goal (queued)
  → Researching   (ResearchEngine + provider.research + URL fetch)
  → Planning      (ScrubPlanner → ExecutionPlan)
  → Executing     (BrowserOperator / DesktopOperator / provider.execute)
  → [awaiting_approval] if purchase/payment/credential change
  → Verifying     (VerificationEngine + provider.verify)
  → [repairing]   on failure (RepairEngine, max 3 retries)
  → completed | failed
```

Every goal has: `goal_id`, `objective`, `status`, `created_at`, `completed_at`.

---

## Integration points

| Layer | Integration |
|-------|-------------|
| **desktop_app.py** | Safe init at boot; REST API; Socket.IO `sentinelscrub_event` |
| **orb.html** | Settings hub panel — feed, goals, approvals |
| **sentinel_security** | Vault via `SecretsStore` (DPAPI / AES) |
| **Chat** | Goals can be started from SentinelScrub UI; chat routing extension is roadmap |

Boot is **non-fatal**: SentinelScrub failure logs a warning and Sentinel still starts.

---

## Data stores

| Store | Path |
|-------|------|
| Goals + feed + approvals | `data/sentinelscrub/goals.db` |
| Workflow memory | `data/sentinelscrub/workflow_memory.json` |
| Audit | `data/sentinelscrub/audit.jsonl` |
| Screenshots | `data/sentinelscrub/screenshots/` |

---

## Operators

- **Browser:** Playwright Chromium (real). Install: `pip install playwright && playwright install chromium`
- **Desktop:** `subprocess` commands (real); mouse/keyboard via optional `pyautogui`

---

## See also

- `SENTINELSCRUB_PROVIDER_SPEC.md`
- `SENTINELSCRUB_SECURITY_MODEL.md`
- `SENTINELSCRUB_APPROVAL_SYSTEM.md`
- `SENTINELSCRUB_ROADMAP.md`
